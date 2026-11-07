// OWNER: UI & demo
import React, { useEffect, useState } from 'react';
import { api } from './api.js';
import ScanForm from './components/ScanForm.jsx';
import ExposureCard from './components/ExposureCard.jsx';
import PolicyFlags from './components/PolicyFlags.jsx';
import AliasPanel from './components/AliasPanel.jsx';
import DraftModal from './components/DraftModal.jsx';
import OutboundLog from './components/OutboundLog.jsx';

export default function App() {
  const [health, setHealth] = useState(null);
  const [companies, setCompanies] = useState([]);
  const [user, setUser] = useState(null);
  const [exposures, setExposures] = useState([]);
  const [policies, setPolicies] = useState([]);
  const [ranked, setRanked] = useState({});
  const [inbox, setInbox] = useState(null);
  const [draft, setDraft] = useState(null);
  const [status, setStatus] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth({ ok: false }));
    api.companies().then(setCompanies).catch(() => {});
    api.inbox().then(setInbox).catch(() => {});
  }, []);

  async function runScan(form) {
    setError('');
    setUser(form);
    try {
      setStatus('Searching brokers and analyzing pages locally…');
      const [{ exposures }, pol, br] = await Promise.all([
        api.scan(form),
        form.companyIds.length ? api.policies(form.companyIds) : { policies: [] },
        form.companyIds.length ? api.breaches(form.companyIds) : { breaches: [] },
      ]);
      setExposures(exposures);
      setPolicies(pol.policies);
      setStatus('Ranking likely sources…');
      const { ranked } = await api.rank({ exposures, breaches: br.breaches, policies: pol.policies });
      setRanked(Object.fromEntries(ranked.map((r) => [r.exposureId, r.likelySources])));
      setStatus('');
    } catch (err) {
      setError(err.message);
      setStatus('');
    }
  }

  async function draftOptOut(exposure) {
    try {
      setDraft({ loading: true, title: `Opt out of ${exposure.broker}` });
      const { optOut, draft } = await api.resolveBroker(user, exposure);
      setDraft({ title: `Opt out of ${exposure.broker}`, link: optOut.url, linkSource: optOut.source, text: draft });
    } catch (err) {
      setDraft({ title: 'Error', text: err.message });
    }
  }

  return (
    <div className="layout">
      <main>
        <header>
          <h1>Hack1984</h1>
          <p className="tagline">
            Find where your data is exposed, which company most likely leaked it, and get it taken down,
            without handing your data to yet another company.
          </p>
          {health && (
            <p className="health">
              Local LLM: {health.ollama?.running ? (health.ollama.pulled ? `✓ ${health.ollama.model}` : `model ${health.ollama.model} not pulled`) : '✗ Ollama not running'}
              {' · '}Exa key: {health.keys?.exa ? '✓' : '✗'} · Tavily key: {health.keys?.tavily ? '✓' : '✗'}
            </p>
          )}
        </header>

        <ScanForm companies={companies} onScan={runScan} busy={Boolean(status)} />
        {status && <p className="status">{status}</p>}
        {error && <p className="error">{error}</p>}

        {exposures.length > 0 && <h2>Exposures ({exposures.length})</h2>}
        <div className="cards">
          {exposures.map((e) => (
            <ExposureCard key={e.id} exposure={e} likelySources={ranked[e.id] ?? []} onDraft={() => draftOptOut(e)} />
          ))}
        </div>

        <PolicyFlags policies={policies} />
        <AliasPanel inbox={inbox} />
      </main>

      <OutboundLog />
      {draft && <DraftModal draft={draft} onClose={() => setDraft(null)} />}
    </div>
  );
}
