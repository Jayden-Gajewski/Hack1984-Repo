"use client";

import { useEffect, useState } from "react";
import { api, type Status } from "@/lib/api";

// Tells a teammate what's missing from their setup before they hit Scan, one indicator per part.
export default function StatusLine() {
  const [status, setStatus] = useState<Status | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.status().then(setStatus, (err) => setError(err instanceof Error ? err.message : String(err)));
  }, []);

  if (error) return <p className="error">{error}</p>;
  if (!status) return <p className="status-line">Checking setup…</p>;

  const llmOk = status.ollama_running && status.model_pulled;
  const llm = !status.ollama_running
    ? "Local LLM not running (start Ollama)"
    : status.model_pulled
      ? `Local LLM ready (${status.ollama_model})`
      : `Local LLM needs the model: ollama pull ${status.ollama_model}`;
  const missing = Object.entries(status.keys)
    .filter(([, set]) => !set)
    .map(([name]) => name);

  const items: { ok: boolean; text: string }[] = [
    { ok: llmOk, text: llm },
    { ok: status.database, text: status.database ? "Saved scans ready" : "Postgres down (docker compose up -d)" },
    {
      ok: missing.length === 0,
      text: missing.length === 0 ? "Search keys set" : `Missing key: ${missing.join(", ")}`,
    },
  ];

  return (
    <ul className="status-line" aria-label="Setup">
      {items.map((item) => (
        <li key={item.text} className="status-item">
          <span className={`dot ${item.ok ? "ok" : "bad"}`} aria-hidden="true" />
          {item.text}
        </li>
      ))}
    </ul>
  );
}
