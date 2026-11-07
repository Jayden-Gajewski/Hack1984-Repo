// Express API. Each route maps to one pitch stage.
// Personal data (name, city) always goes in the POST body, never in a URL.
import 'dotenv/config';
import express from 'express';
import brokers from './data/brokers.json' with { type: 'json' };
import companies from './data/companies.json' with { type: 'json' };
import { getOutboundLog, clearOutboundLog } from './lib/outbound.js';
import { ollamaHealth } from './lib/ollama.js';
import { findExposures } from './stages/1-exposures.js';
import { dateExposures } from './stages/2-dates.js';
import { breachTimelines } from './stages/3-breaches.js';
import { checkPolicies } from './stages/4-policy.js';
import { rankSources } from './stages/5-rank.js';
import { findOptOut, findPrivacyContact, draftBrokerOptOut, draftCompanyRequest } from './stages/6-resolve.js';
import { generateAlias, checkInbox } from './stages/7-alias.js';

const app = express();
app.use(express.json({ limit: '2mb' }));

// Wraps async handlers so errors come back as JSON instead of crashing the server.
const route = (fn) => async (req, res) => {
  try {
    res.json(await fn(req, res));
  } catch (err) {
    console.error(`[${req.method} ${req.path}]`, err);
    res.status(500).json({ error: err.message });
  }
};

const pickCompanies = (ids = []) => companies.filter((c) => ids.includes(c.id));

app.get('/api/health', route(async () => ({
  ok: true,
  ollama: await ollamaHealth(),
  keys: { exa: Boolean(process.env.EXA_API_KEY), tavily: Boolean(process.env.TAVILY_API_KEY) },
})));

app.get('/api/brokers', route(() => brokers));
app.get('/api/companies', route(() => companies));

// Stage 1 (+2): scan yourself
app.post('/api/scan', route(async (req) => {
  const { name, city, state } = req.body ?? {};
  if (!name || !city) throw new Error('name and city are required');
  const exposures = await findExposures({ name, city, state });
  return { exposures: await dateExposures(exposures) };
}));

// Stage 2 on its own (if exposures came from elsewhere)
app.post('/api/dates', route(async (req) => ({ exposures: await dateExposures(req.body.exposures ?? []) })));

// Stage 3
app.post('/api/breaches', route(async (req) => ({ breaches: await breachTimelines(pickCompanies(req.body.companyIds)) })));

// Stage 4
app.post('/api/policies', route(async (req) => ({ policies: await checkPolicies(pickCompanies(req.body.companyIds)) })));

// Stage 5 (+7 alias matches)
app.post('/api/rank', route((req) => {
  const { exposures, breaches, policies } = req.body ?? {};
  return { ranked: rankSources({ exposures, breaches, policies, aliasMatches: checkInbox().matches }) };
}));

// Stage 6
app.post('/api/resolve/broker', route(async (req) => {
  const { user, exposure } = req.body;
  return { optOut: await findOptOut(exposure.broker, exposure.brokerId), draft: draftBrokerOptOut({ user, exposure }) };
}));

app.post('/api/resolve/company', route(async (req) => {
  const { user, companyId } = req.body;
  const company = companies.find((c) => c.id === companyId);
  if (!company) throw new Error('unknown company');
  return { contact: await findPrivacyContact(company), draft: draftCompanyRequest({ user, company }) };
}));

// Stage 7
app.post('/api/alias', route((req) => ({ alias: generateAlias(req.body.company ?? 'signup') })));
app.get('/api/inbox/check', route(() => checkInbox()));

// Outbound log panel
app.get('/api/outbound', route((req) => getOutboundLog({ includeLocal: req.query.local !== '0' })));
app.delete('/api/outbound', route(() => { clearOutboundLog(); return { ok: true }; }));

const PORT = process.env.PORT || 3001;
app.listen(PORT, () => console.log(`API on http://localhost:${PORT}`));
