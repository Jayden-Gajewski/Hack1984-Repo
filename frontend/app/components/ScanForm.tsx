"use client";

import { useEffect, useState } from "react";
import { api, type ScanRequest, type ScanResponse } from "@/lib/api";

interface Props {
  onResult: (result: ScanResponse, request: ScanRequest) => void;
  onBusyChange?: (busy: boolean) => void;
}

function formatElapsed(seconds: number) {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

export default function ScanForm({ onResult, onBusyChange }: Props) {
  const [name, setName] = useState("");
  const [city, setCity] = useState("");
  const [state, setState] = useState("");
  const [consent, setConsent] = useState(false);
  const [loading, setLoading] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState<string | null>(null);

  // A real clock, not a progress bar: the scan is one request and we can't know how far along it is.
  useEffect(() => {
    if (!loading) return;
    setElapsed(0);
    const started = Date.now();
    const timer = setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => clearInterval(timer);
  }, [loading]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    onBusyChange?.(true);
    setError(null);
    try {
      const request = { name, city, state, consent };
      onResult(await api.scan(request), request);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Scan failed");
    } finally {
      setLoading(false);
      onBusyChange?.(false);
    }
  }

  return (
    <form onSubmit={submit} aria-busy={loading}>
      <h2>Scan yourself</h2>
      <div className="fields">
        <label>
          Full name
          <input type="text" value={name} onChange={(e) => setName(e.target.value)} required autoComplete="name" />
        </label>
        <label>
          City
          <input type="text" value={city} onChange={(e) => setCity(e.target.value)} required autoComplete="address-level2" />
        </label>
        <label>
          State
          <input
            type="text"
            value={state}
            onChange={(e) => setState(e.target.value.toUpperCase().replace(/[^A-Z]/g, ""))}
            required
            minLength={2}
            maxLength={2}
            pattern="[A-Z]{2}"
            title="Two-letter state code, like MA"
            placeholder="MA"
            autoComplete="address-level1"
          />
        </label>
      </div>
      <label className="check">
        <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
        <span>I&apos;m scanning myself (or a teammate who agreed to it).</span>
      </label>
      <div className="row">
        <button type="submit" disabled={!consent || loading}>
          {loading ? "Scanning…" : "Scan"}
        </button>
      </div>
      <p className="muted">We search with your name and city only. Never your phone number or email.</p>

      {loading && (
        <div className="progress" role="status">
          <p className="progress-text">
            <span className="elapsed" aria-hidden="true">{formatElapsed(elapsed)}</span>
            <span>Searching broker sites, then reading each page with the local LLM. This can take a few minutes.</span>
          </p>
          <div className="stripe" aria-hidden="true" />
        </div>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </form>
  );
}
