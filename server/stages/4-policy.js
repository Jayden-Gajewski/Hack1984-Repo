// OWNER: Evidence
// Stage 4: pull each company's privacy policy and have the LOCAL LLM flag sell/share clauses.
// This is the "this wasn't a hack, they sold it" moment.
import * as tavily from '../services/tavily.js';
import { askJSON } from '../lib/ollama.js';
import { POLICY_CLAUSES } from '../prompts/index.js';

const KEYWORDS = /\b(sell|sold|sale|share|sharing|third[- ]part|partner|affiliate|advertis|broker|marketing)/i;

async function findPolicyUrl(company) {
  if (company.policyUrl) return company.policyUrl;
  const { results = [] } = await tavily.search(`${company.name} privacy policy`, {
    include_domains: company.domains,
    max_results: 3,
  });
  return results[0]?.url ?? null;
}

/** Keep only paragraphs that mention selling/sharing so a small model can handle it. */
function relevantExcerpts(text, maxChars = 9000) {
  const paras = text.split(/\n{1,}/).map((p) => p.trim()).filter((p) => p.length > 40 && KEYWORDS.test(p));
  let out = '';
  for (const p of paras) {
    if (out.length + p.length > maxChars) break;
    out += p + '\n\n';
  }
  return out;
}

export async function checkPolicy(company) {
  const policyUrl = await findPolicyUrl(company);
  if (!policyUrl) return { company: company.name, companyId: company.id, policyUrl: null, error: 'policy not found' };

  const { results = [] } = await tavily.extract(policyUrl);
  const text = results[0]?.raw_content;
  if (!text) return { company: company.name, companyId: company.id, policyUrl, error: 'could not extract policy' };

  const analysis = await askJSON(
    POLICY_CLAUSES.system,
    POLICY_CLAUSES.user({ company: company.name, text: relevantExcerpts(text) }),
    { sells: false, sharesForAds: false, sharesWithBrokersOrPartners: false, flags: [] },
  );
  return { company: company.name, companyId: company.id, policyUrl, ...analysis };
}

export async function checkPolicies(companies) {
  return Promise.all(companies.map((c) => checkPolicy(c).catch((err) => ({ company: c.name, companyId: c.id, error: err.message }))));
}
