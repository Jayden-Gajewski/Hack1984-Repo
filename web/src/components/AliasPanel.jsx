import React from 'react';

export default function AliasPanel({ inbox }) {
  if (!inbox) return null;
  return (
    <section>
      <h2>Alias inbox (checked locally)</h2>
      <p className="muted">Each signup gets its own alias. Mail from anyone else to that alias proves who shared it.</p>
      <ul>
        {inbox.aliases.map((a) => (
          <li key={a.alias}><code>{a.alias}</code> → {a.company}</li>
        ))}
      </ul>
      {inbox.matches.map((m, i) => (
        <div key={i} className="alias-match">
          <span className="tier Proven">Proven</span> Your <strong>{m.company}</strong>-only alias got mail from{' '}
          <strong>{m.fromDomain}</strong> on {m.date}: “{m.subject}”
        </div>
      ))}
    </section>
  );
}
