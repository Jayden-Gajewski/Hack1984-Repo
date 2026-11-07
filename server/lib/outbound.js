// OWNER: UI & demo (the panel) + everyone (must use this for ALL external calls)
//
// The privacy core of the app. Every request that leaves the laptop goes through
// outboundFetch, gets logged with exactly what was sent, and is served at GET /api/outbound.
// Calls to local Ollama are logged too, but marked local: true.

const log = [];
let nextId = 1;

const EMAIL_RE = /[^\s@]+@[^\s@]+\.[^\s@]+/;
const PHONE_RE = /(\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}/;

/** Throw if a search query contains an email or phone number. Name + city only. */
export function assertMinimalQuery(text) {
  if (EMAIL_RE.test(text)) throw new Error(`Blocked query with an email address: "${text}"`);
  if (PHONE_RE.test(text)) throw new Error(`Blocked query with a phone number: "${text}"`);
  return text;
}

// Strip secrets before anything gets logged.
function sanitizeHeaders(headers = {}) {
  const out = {};
  for (const [k, v] of Object.entries(headers)) {
    out[k] = /key|authorization|token/i.test(k) ? '[redacted]' : v;
  }
  return out;
}

function sanitizeUrl(url) {
  const u = new URL(url);
  for (const k of [...u.searchParams.keys()]) {
    if (/key|token/i.test(k)) u.searchParams.set(k, '[redacted]');
  }
  return u.toString();
}

/**
 * fetch() wrapper. Use instead of fetch() everywhere in server/.
 * @param {string} service  short label, e.g. 'exa', 'tavily', 'wayback', 'ollama'
 * @param {string} url
 * @param {RequestInit} options
 * @param {{ local?: boolean }} meta
 */
export async function outboundFetch(service, url, options = {}, meta = {}) {
  const entry = {
    id: nextId++,
    time: new Date().toISOString(),
    service,
    local: Boolean(meta.local),
    method: options.method || 'GET',
    url: sanitizeUrl(url),
    headers: sanitizeHeaders(options.headers),
    body: options.body ? safeParse(options.body) : null,
    status: null,
    ms: null,
  };
  log.push(entry);
  const start = Date.now();
  try {
    const res = await fetch(url, options);
    entry.status = res.status;
    return res;
  } catch (err) {
    entry.status = 'error';
    entry.error = err.message;
    throw err;
  } finally {
    entry.ms = Date.now() - start;
  }
}

function safeParse(body) {
  try { return JSON.parse(body); } catch { return String(body); }
}

export function getOutboundLog({ includeLocal = true } = {}) {
  return includeLocal ? log : log.filter((e) => !e.local);
}

export function clearOutboundLog() {
  log.length = 0;
}
