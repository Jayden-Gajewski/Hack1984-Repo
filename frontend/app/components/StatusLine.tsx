"use client";

import { useEffect, useState } from "react";
import { api, type Status } from "@/lib/api";
import Skeleton from "./Skeleton";

// Tells a teammate what's missing from their setup before they hit Scan, one indicator per part.
export default function StatusLine() {
  const [status, setStatus] = useState<Status | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.status().then(setStatus, (err) => setError(err instanceof Error ? err.message : String(err)));
  }, []);

  if (error) return <p className="error">{error}</p>;
  if (!status)
    return (
      <div className="status-line">
        <Skeleton label="Checking setup" shape="line" rows={1} />
      </div>
    );

  const llmOk = status.ollama_running; // GEMINI_API_KEY is set (the field is named from before Gemini)
  const llm = llmOk ? `Gemini ready (${status.ollama_model})` : "Gemini not set up (add GEMINI_API_KEY to .env)";
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
