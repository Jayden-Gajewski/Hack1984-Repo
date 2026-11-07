// OWNER: Search & extract
// Exa REST API. Docs: https://docs.exa.ai
import { outboundFetch, assertMinimalQuery } from '../lib/outbound.js';

const BASE = 'https://api.exa.ai';

async function post(path, body) {
  const key = process.env.EXA_API_KEY;
  if (!key) throw new Error('EXA_API_KEY missing from .env');
  const res = await outboundFetch('exa', `${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'x-api-key': key },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`Exa ${path} ${res.status}: ${await res.text()}`);
  return res.json();
}

/** Semantic search. opts: { numResults, includeDomains, startPublishedDate, endPublishedDate, text } */
export function search(query, opts = {}) {
  assertMinimalQuery(query);
  const { text = false, ...rest } = opts;
  return post('/search', {
    query,
    type: 'auto',
    numResults: 10,
    ...rest,
    ...(text ? { contents: { text: { maxCharacters: 4000 } } } : {}),
  });
}

/** Pages similar to a known broker listing. */
export function findSimilar(url, opts = {}) {
  return post('/findSimilar', { url, numResults: 10, ...opts });
}
