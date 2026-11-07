"use client";

import { useState } from "react";
import { api, type ScanResponse } from "@/lib/api";

interface Props {
  onResult: (result: ScanResponse) => void;
}

export default function ScanForm({ onResult }: Props) {
  const [name, setName] = useState("");
  const [city, setCity] = useState("");
  const [state, setState] = useState("");
  const [consent, setConsent] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      onResult(await api.scan({ name, city, state, consent }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Scan failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={submit} className="panel">
      <h2>Scan yourself</h2>
      <label>
        Full name
        <input type="text" value={name} onChange={(e) => setName(e.target.value)} required />
      </label>
      <label>
        City
        <input type="text" value={city} onChange={(e) => setCity(e.target.value)} required />
      </label>
      <label>
        State
        <input
          type="text"
          value={state}
          onChange={(e) => setState(e.target.value.toUpperCase())}
          required
          minLength={2}
          maxLength={2}
          placeholder="MA"
        />
      </label>
      <label className="consent">
        <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
        <span>I&apos;m scanning myself (or a teammate who agreed to it).</span>
      </label>
      <button type="submit" disabled={!consent || loading}>
        {loading ? "Scanning… (the local LLM can take a few minutes)" : "Scan"}
      </button>
      <p className="muted">We search with your name and city only. Never your phone number or email.</p>
      {error && <p className="error">{error}</p>}
    </form>
  );
}
