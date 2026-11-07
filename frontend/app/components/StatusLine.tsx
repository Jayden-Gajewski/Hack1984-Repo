"use client";

import { useEffect, useState } from "react";
import { api, type Status } from "@/lib/api";

// One line that tells a teammate what's missing from their setup before they hit Scan.
export default function StatusLine() {
  const [status, setStatus] = useState<Status | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.status().then(setStatus, (err) => setError(err instanceof Error ? err.message : String(err)));
  }, []);

  if (error) return <p className="error">{error}</p>;
  if (!status) return <p className="muted">Checking setup…</p>;

  const ollama = !status.ollama_running
    ? "not running"
    : status.model_pulled
      ? `${status.ollama_model} ready`
      : `run: ollama pull ${status.ollama_model}`;
  const keys = Object.entries(status.keys)
    .map(([name, set]) => `${name} ${set ? "set" : "missing"}`)
    .join(", ");

  return (
    <p className="muted">
      Local LLM: {ollama} · Postgres: {status.database ? "up" : "down (docker compose up -d)"} · Keys:{" "}
      {keys}
    </p>
  );
}
