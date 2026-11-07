// OWNER: Evidence
// Stage 3: breach timeline for each company the user picked.
// Queries contain only the company name, nothing about the user.
import * as exa from '../services/exa.js';
import * as tavily from '../services/tavily.js';
import { askJSON } from '../lib/ollama.js';
import { BREACH_TIMELINE } from '../prompts/index.js';

export async function breachTimeline(company) {
  const [news, ag] = await Promise.allSettled([
    tavily.search(`${company.name} data breach`, { topic: 'news', max_results: 8 }),
    exa.search(`${company.name} data breach notification attorney general`, {
      numResults: 8,
      startPublishedDate: '2015-01-01T00:00:00.000Z',
      text: true,
    }),
  ]);

  const results = [];
  if (news.status === 'fulfilled') {
    for (const r of news.value.results ?? []) {
      results.push({ url: r.url, title: r.title, snippet: r.content, date: r.published_date });
    }
  }
  if (ag.status === 'fulfilled') {
    for (const r of ag.value.results ?? []) {
      results.push({ url: r.url, title: r.title, snippet: (r.text ?? '').slice(0, 1500), date: r.publishedDate });
    }
  }
  if (results.length === 0) return { company: company.name, breaches: [] };

  const out = await askJSON(BREACH_TIMELINE.system, BREACH_TIMELINE.user({ company: company.name, results }), {
    breaches: [],
  });
  return { company: company.name, companyId: company.id, breaches: out.breaches ?? [] };
}

export async function breachTimelines(companies) {
  return Promise.all(companies.map(breachTimeline));
}
