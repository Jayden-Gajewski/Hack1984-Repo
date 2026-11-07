"use client";

import { useEffect, useState } from "react";
import { api, type OutboundEntry } from "@/lib/api";

// "Here's everything that left this laptop." Polls the backend's outbound log.
export default function OutboundLog() {
  const [entries, setEntries] = useState<OutboundEntry[]>([]);
  const [includeLocal, setIncludeLocal] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function poll() {
      try {
        const data = await api.outboundLog(includeLocal);
        if (!cancelled) {
          setEntries(data);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Log unavailable");
      }
    }
    poll();
    const timer = setInterval(poll, 1500);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [includeLocal]);

  async function clear() {
    try {
      await api.clearOutboundLog();
      setEntries([]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't clear the log");
    }
  }

  const counts = entries.reduce<Record<string, number>>((acc, e) => {
    acc[e.service] = (acc[e.service] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <aside className="panel">
      <h2>Outbound log</h2>
      <p className="muted">Every request that left this laptop, with exactly what was sent.</p>
      <p className="muted">
        {Object.keys(counts).length === 0
          ? "Nothing sent yet."
          : Object.entries(counts)
              .map(([service, n]) => `${service}: ${n}`)
              .join(" · ")}
      </p>
      <div className="row">
        <label className="consent">
          <input
            type="checkbox"
            checked={includeLocal}
            onChange={(e) => setIncludeLocal(e.target.checked)}
          />
          <span>Show local LLM calls (stayed on this machine)</span>
        </label>
        <button type="button" className="secondary" onClick={clear}>
          Clear
        </button>
      </div>
      {error && <p className="error">{error}</p>}
      <div>
        {[...entries].reverse().map((e) => (
          <details key={e.id} className="log-row">
            <summary>
              <span className={e.local ? "tag-local" : "tag-remote"}>
                {e.local ? "local · stayed on this machine" : e.service}
              </span>
              <span>{e.purpose}</span>
              <span className="muted">
                {e.method} {e.url} · {e.error ? "failed" : (e.status ?? "…")} · {e.ms ?? "…"} ms
              </span>
            </summary>
            <pre>
              {JSON.stringify({ headers: e.headers, body: e.body, error: e.error ?? undefined }, null, 2)}
            </pre>
          </details>
        ))}
      </div>
    </aside>
  );
}
