import React, { useState } from 'react';

export default function ScanForm({ companies, onScan, busy }) {
  const [name, setName] = useState('');
  const [city, setCity] = useState('');
  const [state, setState] = useState('');
  const [companyIds, setCompanyIds] = useState([]);
  const [consent, setConsent] = useState(false);

  const toggle = (id) => setCompanyIds((ids) => (ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id]));

  return (
    <form
      className="scan-form"
      onSubmit={(e) => {
        e.preventDefault();
        onScan({ name: name.trim(), city: city.trim(), state: state.trim(), companyIds });
      }}
    >
      <div className="row">
        <input placeholder="Full name" value={name} onChange={(e) => setName(e.target.value)} required />
        <input placeholder="City" value={city} onChange={(e) => setCity(e.target.value)} required />
        <input placeholder="State" value={state} onChange={(e) => setState(e.target.value)} maxLength={2} className="short" />
      </div>
      <p className="hint">We only search with your name and city, never your phone number or email.</p>

      <fieldset>
        <legend>Which of these companies have your data?</legend>
        <div className="chips">
          {companies.map((c) => (
            <label key={c.id} className={companyIds.includes(c.id) ? 'chip on' : 'chip'}>
              <input type="checkbox" checked={companyIds.includes(c.id)} onChange={() => toggle(c.id)} />
              {c.name}
            </label>
          ))}
        </div>
      </fieldset>

      <label className="consent">
        <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
        I'm scanning myself (or have this person's permission).
      </label>
      <button disabled={!consent || busy}>{busy ? 'Scanning…' : 'Scan'}</button>
    </form>
  );
}
