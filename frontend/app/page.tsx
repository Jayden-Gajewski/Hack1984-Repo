"use client";

import { useCallback, useEffect, useState } from "react";
import { api, type Draft, type RemovalStatus, type ScanResponse } from "@/lib/api";
import AccountsPanel from "./components/AccountsPanel";
import AliasPanel from "./components/AliasPanel";
import DraftModal from "./components/DraftModal";
import ExposureCard from "./components/ExposureCard";
import OutboundLog from "./components/OutboundLog";
import ScanForm from "./components/ScanForm";
import StarGlobe from "./components/StarGlobe";
import StatusLine from "./components/StatusLine";
import Tabs, { type Tab } from "./components/Tabs";

const message = (err: unknown) => (err instanceof Error ? err.message : String(err));

type TabId = "scan" | "accounts" | "aliases";
const TABS: Tab<TabId>[] = [
  { id: "scan", label: "Scan" },
  { id: "accounts", label: "Accounts" },
  { id: "aliases", label: "Aliases" },
];
const isTab = (v: string): v is TabId => TABS.some((t) => t.id === v);

export default function Home() {
  const [result, setResult] = useState<ScanResponse | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [draftOpen, setDraftOpen] = useState(false);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [draftLoading, setDraftLoading] = useState(false);
  const [draftError, setDraftError] = useState<string | null>(null);
  const [removals, setRemovals] = useState<Record<string, RemovalStatus>>({});
  const [rescanning, setRescanning] = useState(false);
  const [notes, setNotes] = useState<string[]>([]);
  const [scanning, setScanning] = useState(false);
  const closeDraft = useCallback(() => setDraftOpen(false), []);
  const [tab, setTab] = useState<TabId>("scan");

  // The tab lives in the URL hash (#accounts) so a refresh or a shared link lands on the same tab.
  useEffect(() => {
    const fromHash = window.location.hash.slice(1);
    if (isTab(fromHash)) setTab(fromHash);
  }, []);

  function changeTab(id: TabId) {
    setTab(id);
    history.replaceState(null, "", id === "scan" ? window.location.pathname : `#${id}`);
  }

  function showScan(scan: ScanResponse) {
    setResult(scan);
    setRemovals({});
    setNotes([]);
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

  const count = result?.exposures.length ?? 0;

  return (
    <main>
      <div className="work">
        <header>
          <h1>Dossier</h1>
          <p className="lede">Find where your personal data is exposed. Analysis runs on this laptop.</p>
          <StatusLine />
        </header>

        <Tabs tabs={TABS} active={tab} onChange={changeTab} label="Dossier sections" />

        <div className="tabpanel" role="tabpanel" id="panel-scan" aria-labelledby="tab-scan" hidden={tab !== "scan"}>
        <section className="section scan-section" aria-label="Scan">
          <div className="task-panel">
            <ScanForm onResult={showScan} onBusyChange={setScanning} />
            <div className="row mt">
              <button type="button" className="secondary" onClick={loadLastScan} disabled={scanning}>
                Load last scan
              </button>
              <span className="muted small">Reads the last saved scan from this laptop.</span>
            </div>
            {loadError && (
              <p className="error" role="alert">
                {loadError}
              </p>
            )}
          </div>
        </section>

        <section className="section" aria-labelledby="exposures-h" aria-busy={scanning}>
          <div className="section-head">
            <h2 id="exposures-h" aria-live="polite">
              {scanning
                ? "Exposures"
                : result
                  ? `${count} exposure${count === 1 ? "" : "s"} found`
                  : "Exposures"}
            </h2>
            {result && count > 0 && (
              <button type="button" className="secondary" onClick={rescan} disabled={rescanning || scanning}>
                {rescanning ? "Re-checking…" : "Re-scan listings"}
              </button>
            )}
          </div>
          {!result && !scanning && (
            <p className="muted">Run a scan to see which people-search sites list you.</p>
          )}
          {scanning && <p className="muted">Results appear here when the scan finishes.</p>}
          {result && count === 0 && !scanning && (
            <p className="muted">
              None of the broker sites we checked list this name in this city. That covers the sites we
              search, not the whole web.
            </p>
          )}
          {(!result || count === 0) && (
            <div className="exposure-art">
              <StarGlobe />
            </div>
          )}
          {result &&
            [...result.errors, ...notes].map((err, i) => (
              <p key={i} className="notice">
                <strong>Note:</strong> {err}
              </p>
            ))}
          {result && (
            <div className="cards" key={result.scan_id}>
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
        </section>
        </div>

        <div className="tabpanel" role="tabpanel" id="panel-accounts" aria-labelledby="tab-accounts" hidden={tab !== "accounts"}>
          <AccountsPanel
            onChecked={refreshLeads}
            onDraft={(company) => openDraft({ company })}
            canDraft={result !== null}
          />
        </div>

        <div className="tabpanel" role="tabpanel" id="panel-aliases" aria-labelledby="tab-aliases" hidden={tab !== "aliases"}>
          <AliasPanel onChecked={refreshLeads} />
        </div>
      </div>

      <OutboundLog />

      {draftOpen && (
        <DraftModal draft={draft} loading={draftLoading} error={draftError} onClose={closeDraft} />
      )}
    </main>
  );
}
