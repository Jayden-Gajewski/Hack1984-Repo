import React, { useState } from 'react';

const FIELD_LABELS = { address: 'Address', phone: 'Phone', email: 'Email', relatives: 'Relatives', age: 'Age', employer: 'Employer' };

export default function ExposureCard({ exposure, likelySources, onDraft }) {
  const [open, setOpen] = useState(false);
  const exposed = Object.entries(exposure.fields).filter(([, on]) => on).map(([f]) => f);
  const top = likelySources[0];

  return (
    <article className="card">
      <header onClick={() => setOpen(!open)}>
        <h3>{exposure.broker}</h3>
        <div className="fields">
          {exposed.map((f) => <span key={f} className="field">{FIELD_LABELS[f] ?? f}</span>)}
        </div>
        {top && <p className="lead"><span className={`tier ${top.tier}`}>{top.tier}</span> likely source: {top.company}</p>}
      </header>

      {open && (
        <div className="details">
          <p><a href={exposure.url} target="_blank" rel="noreferrer">{exposure.url}</a></p>
          <p>
            Public by: <strong>{exposure.publicBy?.date ?? 'unknown'}</strong>{' '}
            <span className="muted">({exposure.publicBy?.source ?? 'unknown'})</span>
            {exposure.publicBy?.url && <> · <a href={exposure.publicBy.url} target="_blank" rel="noreferrer">snapshot</a></>}
          </p>
          {Object.entries(exposure.evidence ?? {}).filter(([, v]) => v).map(([k, v]) => (
            <p key={k} className="muted">{FIELD_LABELS[k] ?? k}: {v}</p>
          ))}
          <p className="muted">Text source: {exposure.textSource === 'extract' ? 'full page' : 'search snippet'} · found via {exposure.foundVia}</p>

          <h4>Likely sources</h4>
          {likelySources.length === 0 && <p className="muted">No leads yet.</p>}
          <ul className="leads">
            {likelySources.map((l, i) => (
              <li key={i}>
                <span className={`tier ${l.tier}`}>{l.tier}</span> {l.reason}
                {l.sourceUrl && <> <a href={l.sourceUrl} target="_blank" rel="noreferrer">source</a></>}
              </li>
            ))}
          </ul>
          <button onClick={onDraft}>Draft opt-out request</button>
        </div>
      )}
    </article>
  );
}
