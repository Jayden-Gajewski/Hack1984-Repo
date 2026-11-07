// OWNER: Search & extract
// Tavily REST API. Docs: https://docs.tavily.com
import { outboundFetch, assertMinimalQuery } from '../lib/outbound.js';

const BASE = 'https://api.tavily.com';

async function post(path, body) {
  const key = process.env.TAVILY_API_KEY;
  if (!key) throw new Error('TAVILY_API_KEY missing from .env');
  const res = await outboundFetch('tavily', `${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${key}` },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`Tavily ${path} ${res.status}: ${await res.text()}`);
  return res.json();
}

/** opts: { include_domains, topic: 'general'|'news', max_results, search_depth, time_range } */
export function search(query, opts = {}) {
  assertMinimalQuery(query);
  return post('/search', { query, max_results: 10, ...opts });
}

/** Pull page text. Returns { results: [{url, raw_content}], failed_results: [...] } */
export function extract(urls, opts = {}) {
  return post('/extract', { urls: [].concat(urls), extract_depth: 'advanced', ...opts });
}
