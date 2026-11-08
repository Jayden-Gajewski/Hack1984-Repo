"use client";

import { useEffect, useRef, useState } from "react";
import { api, type OutboundEntry } from "@/lib/api";

const SERVICE_LABEL: Record<string, string> = {
  tavily: "Tavily",
  exa: "Exa",
  wayback: "Wayback",
  ollama: "Ollama",
  hibp: "Have I Been Pwned",
  smtp: "Email (SMTP)",
};
const serviceLabel = (s: string) => SERVICE_LABEL[s] ?? s.charAt(0).toUpperCase() + s.slice(1);

// The backend logs each purpose as an instruction ("Ask the Wayback Machine when…").
// Rows read better as what already happened. Anything unrecognized shows as logged.
const TITLE_RULES: [RegExp, string][] = [
  [/^Ask the Wayback Machine when the (.+) listing was first archived$/, "Checked when a $1 listing was archived"],
  [/^Look for (.+)$/, "Looked for $1"],
  [/^Find (.+)$/, "Searched for $1"],
  [/^Discover (.+)$/, "Searched for $1"],
  [/^Read (.+)$/, "Read $1"],
  [/^Re-check (.+)$/, "Re-checked $1"],
  [/^Check (.+)$/, "Checked $1"],
  [/^Build (.+)$/, "Built $1"],
  [/^Flag (.+)$/, "Flagged $1"],
  [/^Download (.+)$/, "Downloaded $1"],
  [/^Send (.+)$/, "Sent $1"],
];

function shortTitle(purpose: string) {
  for (const [pattern, replacement] of TITLE_RULES) {
    if (pattern.test(purpose)) return purpose.replace(pattern, replacement);
  }
  return purpose;
}

function clock(time: string) {
  const d = new Date(time);
  return Number.isNaN(d.getTime())
    ? time
    : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
}

// Who received the request, plus the query parameters decoded so people can read them.
function parseUrl(url: string) {
  try {
    const u = new URL(url);
    return { host: u.host, base: `${u.origin}${u.pathname}`, params: [...u.searchParams.entries()] };
  } catch {
    return { host: url, base: url, params: [] as [string, string][] };
  }
}

function duration(ms: number | null) {
  if (ms === null) return "not finished";
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${ms} ms`;
}

// Top-level body fields that read as plain values; anything nested stays in the raw JSON.
function simpleFields(body: unknown): [string, string][] {
  if (!body || typeof body !== "object" || Array.isArray(body)) return [];
  return Object.entries(body as Record<string, unknown>)
    .filter(([, v]) => ["string", "number", "boolean"].includes(typeof v))
    .map(([k, v]) => [k, String(v)]);
}

function plural(n: number) {
  return `${n} request${n === 1 ? "" : "s"}`;
}

function RequestRow({ entry }: { entry: OutboundEntry }) {
  const { host, base, params } = parseUrl(entry.url);
  const sent = [...params, ...simpleFields(entry.body)];
  const status = entry.error ? "Failed" : entry.status !== null ? String(entry.status) : "Waiting";

  return (
    <li className="log-row">
      <details>
        <summary>
          <span className="log-title">{shortTitle(entry.purpose)}</span>
          <span className="log-meta">
            {entry.local ? "Stayed on this machine" : host}
            <span className="log-time">{clock(entry.time)}</span>
          </span>
        </summary>
        <div className="log-body">
          <dl className="log-facts">
            <div>
              <dt>Request</dt>
              <dd>
                <span className="log-method">{entry.method}</span> {base}
              </dd>
            </div>
            <div>
              <dt>Status</dt>
              <dd className={entry.error ? "log-failed" : undefined}>{status}</dd>
            </div>
            <div>
              <dt>Duration</dt>
              <dd>{duration(entry.ms)}</dd>
            </div>
          </dl>
          {sent.length > 0 && (
            <>
              <p className="log-label">What was sent</p>
              <dl className="log-facts">
                {sent.map(([k, v], i) => (
                  <div key={`${k}-${i}`}>
                    <dt>{k}</dt>
                    <dd>{v}</dd>
                  </div>
                ))}
              </dl>
            </>
          )}
          {entry.error && <p className="error">{entry.error}</p>}
          <details className="log-raw">
            <summary>Raw headers and body</summary>
            <pre>{JSON.stringify({ headers: entry.headers, body: entry.body }, null, 2)}</pre>
          </details>
        </div>
      </details>
    </li>
  );
}

// The count on the tab pops when new requests leave the laptop, so a live scan visibly sends data.
function bump(el: HTMLElement | null) {
  if (!el) return;
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  el.animate(
    reduce
      ? [{ opacity: 0.4 }, { opacity: 1 }]
      : [{ transform: "scale(1)" }, { transform: "scale(1.28)", offset: 0.3 }, { transform: "scale(1)" }],
    { duration: reduce ? 300 : 420, easing: "cubic-bezier(0.16, 1, 0.3, 1)" },
  );
}

// "What left my laptop?" A card that drops down from the tab at the top left, which always shows
// the live count. Stays mounted so it can slide back up; inert while closed.
export default function OutboundLog() {
  const [entries, setEntries] = useState<OutboundEntry[]>([]);
  const [includeLocal, setIncludeLocal] = useState(false);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const handle = useRef<HTMLButtonElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  const countBadge = useRef<HTMLSpanElement>(null);
  const lastCount = useRef<number | null>(null);

  // Fetch everything, local calls included, so the filter is instant. Counts only use outbound ones.
  useEffect(() => {
    let cancelled = false;
    async function poll() {
      try {
        const data = await api.outboundLog(true);
        if (!cancelled) {
          const sent = data.filter((e) => !e.local).length;
          if (lastCount.current !== null && sent > lastCount.current) bump(countBadge.current);
          lastCount.current = sent;
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
  }, []);

  useEffect(() => {
    if (!open) return;
    closeButton.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  function close() {
    setOpen(false);
    requestAnimationFrame(() => handle.current?.focus());
  }

  async function clear() {
    if (!window.confirm("Clear the outbound log? The record of what was sent so far will be deleted.")) return;
    try {
      await api.clearOutboundLog();
      lastCount.current = 0;
      setEntries([]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't clear the log");
    }
  }

  const outbound = entries.filter((e) => !e.local);
  const counts = outbound.reduce<Record<string, number>>((acc, e) => {
    acc[e.service] = (acc[e.service] ?? 0) + 1;
    return acc;
  }, {});
  const breakdown = Object.entries(counts)
    .map(([service, n]) => `${serviceLabel(service)} ${n}`)
    .join(" · ");
  const list = [...(includeLocal ? entries : outbound)].reverse();

  return (
    <>
      <button
        ref={handle}
        type="button"
        className="drawer-handle"
        aria-expanded={open}
        aria-controls="outbound-drawer"
        onClick={() => setOpen(true)}
      >
        <span className="drawer-handle-inner">
          <span className="drawer-handle-label">Outbound requests</span>
          <span ref={countBadge} className="drawer-handle-count" aria-label={plural(outbound.length)}>
            {outbound.length}
          </span>
        </span>
      </button>

      <div className={open ? "drawer-scrim open" : "drawer-scrim"} onClick={close} aria-hidden="true" />
      <aside
        id="outbound-drawer"
        className={open ? "drawer open" : "drawer"}
        role="dialog"
        aria-modal="true"
        aria-labelledby="log-h"
        inert={!open}
      >
        <div className="drawer-head">
          <div className="card-head">
            <h2 id="log-h" className="log-heading">
              Outbound requests <span className="log-total">{outbound.length}</span>
            </h2>
            <button ref={closeButton} type="button" className="quiet" onClick={close}>
              Close
            </button>
          </div>
          {breakdown && <p className="muted small">{breakdown}</p>}
          <p className="muted small mt">Every request that left this laptop, with exactly what was sent.</p>
          <label className="check ledger-toggle">
            <input type="checkbox" checked={includeLocal} onChange={(e) => setIncludeLocal(e.target.checked)} />
            <span>Show local LLM calls (stayed on this machine)</span>
          </label>
        </div>
        {error && <p className="error ledger-pad">{error}</p>}
        <div className="drawer-body">
          {list.length === 0 ? (
            <p className="ledger-empty">No outbound requests yet.</p>
          ) : (
            <ol className="log-list" aria-label="Requests, newest first">
              {list.map((e) => (
                <RequestRow key={e.id} entry={e} />
              ))}
            </ol>
          )}
        </div>
        <div className="ledger-foot">
          <button type="button" className="quiet" onClick={clear} disabled={entries.length === 0}>
            Clear log
          </button>
        </div>
      </aside>
    </>
  );
}
