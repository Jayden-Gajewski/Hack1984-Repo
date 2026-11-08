"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, type Draft, type Exposure, type RemovalStatus, type ScanRequest, type ScanResponse } from "@/lib/api";
import AccountsPanel from "../components/AccountsPanel";
import AliasPanel from "../components/AliasPanel";
import AuthGate from "../components/AuthGate";
import DraftModal from "../components/DraftModal";
import ExposureCard from "../components/ExposureCard";
import FootprintPanel from "../components/FootprintPanel";
import OutboundLog from "../components/OutboundLog";
import ScanForm from "../components/ScanForm";
import StatusLine from "../components/StatusLine";
import { RISK_LABEL } from "@/lib/display";
import Tabs, { type Tab } from "../components/Tabs";
import SwapLabel from "../components/SwapLabel";

const message = (err: unknown) => (err instanceof Error ? err.message : String(err));

type TabId = "scan" | "accounts" | "aliases" | "footprint";
const TABS: Tab<TabId>[] = [
  { id: "scan", label: "Scan" },
  { id: "accounts", label: "Accounts" },
  { id: "aliases", label: "Aliases" },
  { id: "footprint", label: "Footprint" },
];
const isTab = (v: string): v is TabId => TABS.some((t) => t.id === v);

// Most urgent first: higher risk, then stronger evidence for the likely source.
const RISK_RANK = { high: 0, medium: 1, low: 2 } as const;
const TIER_RANK = { proven: 0, likely: 1, possible: 2 } as const;
const urgency = (e: Exposure) => [e.risk ? RISK_RANK[e.risk] : 3, e.leads[0] ? TIER_RANK[e.leads[0].tier] : 3];
const byUrgency = (a: Exposure, b: Exposure) => {
  const [ra, ta] = urgency(a);
  const [rb, tb] = urgency(b);
  return ra - rb || ta - tb;
};

export default function ScannerPage() {
  const [result, setResult] = useState<ScanResponse | null>(null);
  const [showingSaved, setShowingSaved] = useState(false); // opened on the account's last saved scan
  const [draftOpen, setDraftOpen] = useState(false);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [draftLoading, setDraftLoading] = useState(false);
  const [draftError, setDraftError] = useState<string | null>(null);
  const [removals, setRemovals] = useState<Record<string, RemovalStatus>>({});
  const [rescanning, setRescanning] = useState(false);
  const [notes, setNotes] = useState<string[]>([]);
  const [scanning, setScanning] = useState(false);
  const [lastRequest, setLastRequest] = useState<ScanRequest | null>(null);
  const [freshScanning, setFreshScanning] = useState(false);
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

  function showScan(scan: ScanResponse, request?: ScanRequest, saved = false) {
    shown.current = true;
    setResult(scan);
    setRemovals({});
    setNotes([]);
    setLastRequest(request ?? null);
    setShowingSaved(saved);
  }

  // Open on this account's last saved scan (local Postgres), so there's something to work with
  // straight away. It's also the demo fallback if the venue Wi-Fi fails, with no click needed.
  // No saved scan yet is fine: the empty state shows. A scan started meanwhile wins.
  const shown = useRef(false);
  useEffect(() => {
    api.latestScan().then(
      (scan) => {
        if (!shown.current) showScan(scan, undefined, true);
      },
      () => {},
    );
  }, []);

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
    <AuthGate>
    <main className="scanner">
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
              <button type="button" className="secondary" onClick={rescan} disabled={rescanning || scanning} aria-busy={rescanning || undefined}>
                <SwapLabel on={rescanning} idle="Re-scan listings" active="Re-checking…" />
              </button>
            )}
          </div>
          {result?.saved_at && (
            <div className="row">
              <span className="muted">
                Loaded your saved scan from {new Date(result.saved_at).toLocaleString()} (local database).
                Nothing was searched.
              </span>
              {lastRequest && (
                <button type="button" className="secondary" onClick={scanAgain} disabled={freshScanning || scanning} aria-busy={freshScanning || undefined}>
                  <SwapLabel on={freshScanning} idle="Scan again" active="Scanning…" />
                </button>
              )}
              {freshScanning && (
                <span className="muted small" role="status">
                  The local LLM can take a few minutes.
                </span>
              )}
            </div>
          )}
          {showingSaved && result && !result.saved_at && (
            <p className="muted">Your last saved scan, from this laptop. Nothing was searched; scan again above to refresh it.</p>
          )}
          {result && count > 0 && !scanning && (
            <p className="row small muted">
              Most urgent first:
              {(["high", "medium", "low"] as const).map((level) => {
                const n = result.exposures.filter((e) => e.risk === level).length;
                return n > 0 && <span key={level} className={`risk ${level}`}>{n} {RISK_LABEL[level].toLowerCase()}</span>;
              })}
            </p>
          )}
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
          {result &&
            [...result.errors, ...notes].map((err, i) => (
              <p key={i} className="notice">
                <strong>Note:</strong> {err}
              </p>
            ))}
          {result && (
            <div className="cards" key={result.scan_id}>
              {[...result.exposures].sort(byUrgency).map((exposure) => (
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

        <div className="tabpanel" role="tabpanel" id="panel-footprint" aria-labelledby="tab-footprint" hidden={tab !== "footprint"}>
          <FootprintPanel />
        </div>
      </div>

      <OutboundLog />

      {draftOpen && (
        <DraftModal draft={draft} loading={draftLoading} error={draftError} onClose={closeDraft} />
      )}
    </main>
    </AuthGate>
  );
}
