// OWNER: Search & extract
// Stage 1: find broker listings for the user, pull page text, have the LOCAL LLM list exposed fields.
// Queries use name + city only (assertMinimalQuery enforces no email/phone).
import brokers from '../data/brokers.json' with { type: 'json' };
import * as exa from '../services/exa.js';
import * as tavily from '../services/tavily.js';
import { askJSON } from '../lib/ollama.js';
import { EXPOSED_FIELDS } from '../prompts/index.js';

const hostOf = (url) => new URL(url).hostname.replace(/^www\./, '');
const brokerFor = (url) => brokers.find((b) => hostOf(url).endsWith(b.domain));

export async function findExposures({ name, city, state }) {
  const query = `"${name}" ${city}${state ? ' ' + state : ''}`;

  // 1a. Discover candidate pages from both engines in parallel.
  const [tav, ex] = await Promise.allSettled([
    tavily.search(query, { include_domains: brokers.map((b) => b.domain), max_results: 15 }),
    exa.search(`${name} ${city} people search profile address phone relatives`, { numResults: 10 }),
  ]);

  const candidates = new Map(); // url -> { url, title, snippet, publishedDate, via }
  if (tav.status === 'fulfilled') {
    for (const r of tav.value.results ?? []) {
      candidates.set(r.url, { url: r.url, title: r.title, snippet: r.content, via: 'tavily' });
    }
  } else console.warn('[stage1] tavily failed:', tav.reason.message);
  if (ex.status === 'fulfilled') {
    for (const r of ex.value.results ?? []) {
      if (!candidates.has(r.url)) {
        candidates.set(r.url, { url: r.url, title: r.title, snippet: r.text ?? '', publishedDate: r.publishedDate, via: 'exa' });
      }
    }
  } else console.warn('[stage1] exa failed:', ex.reason.message);

  // TODO(search): exa.findSimilar(<a confirmed broker listing>) to discover brokers not in brokers.json.

  const pages = [...candidates.values()].slice(0, 20);
  if (pages.length === 0) return [];

  // 1b. Extract full text. Brokers that block extraction fall back to the search snippet.
  const textByUrl = new Map();
  try {
    const { results = [] } = await tavily.extract(pages.map((p) => p.url));
    for (const r of results) textByUrl.set(r.url, r.raw_content);
  } catch (err) {
    console.warn('[stage1] extract failed, using snippets:', err.message);
  }

  // 1c. Local LLM decides which fields are exposed. Page text never leaves the machine past this point.
  const exposures = [];
  for (const p of pages) {
    const extracted = textByUrl.get(p.url);
    const text = extracted || p.snippet || '';
    if (!text) continue;
    const result = await askJSON(EXPOSED_FIELDS.system, EXPOSED_FIELDS.user({ name, city, state, text }), null);
    if (!result?.matchesPerson) continue;
    const broker = brokerFor(p.url);
    exposures.push({
      id: Buffer.from(p.url).toString('base64url').slice(0, 16),
      url: p.url,
      title: p.title,
      broker: broker?.name ?? hostOf(p.url),
      brokerId: broker?.id ?? null,
      textSource: extracted ? 'extract' : 'snippet',
      foundVia: p.via,
      publishedDate: p.publishedDate ?? null,
      fields: result.fields ?? {},
      evidence: result.evidence ?? {},
    });
  }
  return exposures;
}
