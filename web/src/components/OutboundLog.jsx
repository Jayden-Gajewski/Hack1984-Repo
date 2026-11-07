// "Here's everything that left this laptop."
import React, { useEffect, useState } from 'react';
import { api } from '../api.js';

export default function OutboundLog() {
  const [entries, setEntries] = useState([]);
  const [showLocal, setShowLocal] = useState(false);
  const [openId, setOpenId] = useState(null);

  useEffect(() => {
    const tick = () => api.outbound().then(setEntries).catch(() => {});
    tick();
    const id = setInterval(tick, 1500);
    return () => clearInterval(id);
  }, []);

  const shown = entries.filter((e) => showLocal || !e.local).slice().reverse();
  const external = entries.filter((e) => !e.local).length;

  return (
    <aside className="outbound">
      <h2>Outbound log</h2>
      <p className="muted">{external} requests left this laptop. Page text and analysis stayed local.</p>
      <label className="muted">
        <input type="checkbox" checked={showLocal} onChange={(e) => setShowLocal(e.target.checked)} /> show local LLM calls
      </label>
      <button className="secondary" onClick={() => api.clearOutbound().then(() => setEntries([]))}>Clear</button>
      <ol>
        {shown.map((e) => (
          <li key={e.id} className={e.local ? 'local' : ''} onClick={() => setOpenId(openId === e.id ? null : e.id)}>
            <div>
              <span className={`svc ${e.service}`}>{e.service}</span> {e.method} {new URL(e.url).pathname}{' '}
              <span className="muted">{e.status} · {e.ms ?? '…'}ms</span>
            </div>
            {openId === e.id && <pre>{JSON.stringify({ url: e.url, body: e.body }, null, 2)}</pre>}
          </li>
        ))}
      </ol>
    </aside>
  );
}
