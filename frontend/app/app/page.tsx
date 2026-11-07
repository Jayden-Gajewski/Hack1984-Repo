"use client";

import { useCallback, useState } from "react";
import { api, type Draft, type RemovalStatus, type ScanRequest, type ScanResponse } from "@/lib/api";
import AccountsPanel from "../components/AccountsPanel";
import AliasPanel from "../components/AliasPanel";
import AuthGate from "../components/AuthGate";
import DraftModal from "../components/DraftModal";
import ExposureCard from "../components/ExposureCard";
import OutboundLog from "../components/OutboundLog";
import ScanForm from "../components/ScanForm";
import StatusLine from "../components/StatusLine";

const message = (err: unknown) => (err instanceof Error ? err.message : String(err));

export default function ScannerPage() {
  const [result, setResult] = useState<ScanResponse | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [draftOpen, setDraftOpen] = useState(false);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [draftLoading, setDraftLoading] = useState(false);
  const [draftError, setDraftError] = useState<string | null>(null);
  const [removals, setRemovals] = useState<Record<string, RemovalStatus>>({});
  const [rescanning, setRescanning] = useState(false);
  const [notes, setNotes] = useState<string[]>([]);
  const [lastRequest, setLastRequest] = useState<ScanRequest | null>(null);
  const [freshScanning, setFreshScanning] = useState(false);

  function showScan(scan: ScanResponse, request?: ScanRequest) {
    setResult(scan);
    setRemovals({});
    setNotes([]);
    setLastRequest(request ?? null);
  }

  // A saved scan came back instead of a new search: run a fresh one for the same person.
  async function scanAgain() {
    if (!lastRequest) return;
    setFreshScanning(true);
    try {
      showScan(await api.scan({ ...lastRequest, refresh: true }), lastRequest);
    } catch (err) {
      setNotes([message(err)]);
    } finally {
      setFreshScanning(false);
    }
  }

  // Demo fallback if the venue Wi-Fi fails: reload the last saved scan from local Postgres.
  async function loadLastScan() {
    setLoadError(null);
    try {
      showScan(await api.latestScan());
    } catch (err) {
      setLoadError(message(err));
    }
  }

  // Stage 5: re-rank after new evidence (breaches, policies, alias hits) comes in.
  const refreshLeads = useCallback(async () => {
    try {
      const leads = await api.leads();
      setResult((prev) => (prev ? { ...prev, exposures: leads.exposures } : prev));
      setNotes(leads.errors);
    } catch (err) {
      setNotes([message(err)]);
    }
  }, []);

  async function openDraft(target: { exposure_id: string } | { company: string }) {
    setDraftOpen(true);
    setDraft(null);
    setDraftError(null);
    setDraftLoading(true);
    try {
      setDraft(await api.optOut(target));
    } catch (err) {
      setDraftError(message(err));
    } finally {
      setDraftLoading(false);
    }
  }

  async function rescan() {
    setRescanning(true);
    try {
      const res = await api.rescan();
      setRemovals(Object.fromEntries(res.results.map((r) => [r.exposure_id, r.status])));
      setNotes(res.errors);
    } catch (err) {
      setNotes([message(err)]);
    } finally {
      setRescanning(false);
    }
  }

  return (
    <AuthGate>
    <main className="scanner">
      <section>
        <h1>Dossier</h1>
        <p className="muted">Find where your personal data is exposed. Analysis runs on this laptop.</p>
        <StatusLine />

        <ScanForm onResult={showScan} />
        <p className="row">
          <button type="button" className="secondary" onClick={loadLastScan}>
            Load last scan
          </button>
          {loadError && <span className="error">{loadError}</span>}
        </p>

        {result && (
          <div className="panel">
            <div className="card-head">
              <h2>
                {result.exposures.length} exposure{result.exposures.length === 1 ? "" : "s"} found
              </h2>
              {result.exposures.length > 0 && (
                <button type="button" className="secondary" onClick={rescan} disabled={rescanning}>
                  {rescanning ? "Re-checking…" : "Re-scan listings"}
                </button>
              )}
            </div>
            {result.saved_at && (
              <p className="row">
                <span className="muted">
                  Loaded your saved scan from {new Date(result.saved_at).toLocaleString()} (local database).
                  Nothing was searched.
                </span>
                {lastRequest && (
                  <button type="button" className="secondary" onClick={scanAgain} disabled={freshScanning}>
                    {freshScanning ? "Scanning… (the local LLM can take a few minutes)" : "Scan again"}
                  </button>
                )}
              </p>
            )}
            {[...result.errors, ...notes].map((err, i) => (
              <p key={i} className="muted">
                {err}
              </p>
            ))}
            {result.exposures.map((exposure) => (
              <ExposureCard
                key={exposure.id}
                exposure={exposure}
                removal={removals[exposure.id]}
                onDraft={(id) => openDraft({ exposure_id: id })}
              />
            ))}
          </div>
        )}

        <AccountsPanel
          onChecked={refreshLeads}
          onDraft={(company) => openDraft({ company })}
          canDraft={result !== null}
        />
        <AliasPanel onChecked={refreshLeads} />
      </section>

      <OutboundLog />

      {draftOpen && (
        <DraftModal draft={draft} loading={draftLoading} error={draftError} onClose={() => setDraftOpen(false)} />
      )}
    </main>
    </AuthGate>
  );
}
