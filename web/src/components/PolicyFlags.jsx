import React from 'react';

export default function PolicyFlags({ policies }) {
  const flagged = policies.filter((p) => p.flags?.length);
  if (!policies.length) return null;
  return (
    <section>
      <h2>Privacy policy check</h2>
      {flagged.length === 0 && <p className="muted">No sell/share clauses found in the policies we could read.</p>}
      {flagged.map((p) => (
        <div key={p.company} className="policy">
          <h3>
            {p.company}{' '}
            {p.sells && <span className="badge sold">This wasn't a hack. They sell it.</span>}
          </h3>
          <ul>
            {p.flags.map((f, i) => (
              <li key={i}>
                <strong>{f.plain}</strong>
                <blockquote>“{f.quote}”</blockquote>
              </li>
            ))}
          </ul>
          {p.policyUrl && <a href={p.policyUrl} target="_blank" rel="noreferrer">Read the policy</a>}
        </div>
      ))}
      {policies.filter((p) => p.error).map((p) => (
        <p key={p.company} className="muted">{p.company}: {p.error}</p>
      ))}
    </section>
  );
}
