"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  api,
  type Incident,
  type MonitorConfig,
  type MonitorDashboard,
  type RefreshStatus,
  type Severity,
} from "@/lib/api";
import { HIBP_ATTRIBUTION_URL, SEVERITY_LABEL, localTime, timeAgo } from "@/lib/display";
import AuthGate from "../../components/AuthGate";
import IncidentCard from "../../components/IncidentCard";
import MonitorActivity from "../../components/MonitorActivity";
import MonitoredCompanies from "../../components/MonitoredCompanies";
import MonitoredEmails from "../../components/MonitoredEmails";
import OutboundLog from "../../components/OutboundLog";
import RadarScope from "../../components/RadarScope";
import Tabs, { type Tab } from "../../components/Tabs";

const message = (err: unknown) => (err instanceof Error ? err.message : String(err));

type TabId = "threats" | "watch" | "history";
const TABS: Tab<TabId>[] = [
  { id: "threats", label: "Threats" },
  { id: "watch", label: "What we watch" },
  { id: "history", label: "History" },
];
const isTab = (v: string): v is TabId => TABS.some((t) => t.id === v);
const SEVERITIES: Severity[] = ["critical", "high", "medium", "low"];
// Backend step names that aren't worth a line in the scan feed, and friendlier names for the rest.
const QUIET_STEPS = new Set(["Starting", "Finished"]);
const STEP_LABEL: Record<string, string> = { Saving: "Saving results" };

interface FeedLine {
  text: string;
  done: boolean;
}

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

// What can run with this laptop's .env. Off features never produce fake results.
function Setup({ config }: { config: MonitorConfig }) {
  const items = [
    { on: true, text: "Breach list from Have I Been Pwned (no key needed)" },
    { on: config.hibp_email_key, text: config.hibp_email_key ? "Email checks ready (hashed)" : "Email checks need an HIBP Pro key" },
    { on: config.smtp, text: config.smtp ? "Email verification ready" : "Email verification needs SMTP in .env" },
    { on: config.news_search, text: config.news_search ? "News search keys set" : "News search needs a Tavily or Exa key" },
    {
      on: config.local_llm,
      text: config.local_llm ? `Local AI ready (${config.local_llm_model})` : "Local AI not running (start Ollama)",
    },
  ];
  return (
    <section className="section" aria-labelledby="setup-h">
      <h2 id="setup-h">Setup</h2>
      <ul className="setup-list">
        {items.map((item) => (
          <li key={item.text}>
            <span className={`dot ${item.on ? "ok" : "off"}`} aria-hidden="true" />
            {item.text}
          </li>
        ))}
      </ul>
    </section>
  );
}

export default function MonitorPage() {
  const [board, setBoard] = useState<MonitorDashboard | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [tab, setTab] = useState<TabId>("threats");
  const [showDone, setShowDone] = useState(false);
  const [includeNews, setIncludeNews] = useState(false);
  const [refresh, setRefresh] = useState<RefreshStatus | null>(null); // while a scan runs
  const [result, setResult] = useState<RefreshStatus | null>(null); // the scan that just finished
  const [feed, setFeed] = useState<FeedLine[]>([]);
  const [actionError, setActionError] = useState<string | null>(null);
  const [arrived, setArrived] = useState<Set<string>>(new Set());
  const [elapsed, setElapsed] = useState(0);
  const known = useRef<Set<string>>(new Set());
  const lastFinished = useRef<string | null>(null);
  const running = refresh?.running ?? false;

  const load = useCallback(async () => {
    try {
      const data = await api.monitor.dashboard();
      setBoard(data);
      setLoadError(null);
      return data;
    } catch (err) {
      setLoadError(message(err));
      return null;
    }
  }, []);

  useEffect(() => {
    const fromHash = window.location.hash.slice(1);
    if (isTab(fromHash)) setTab(fromHash);
    load().then((data) => {
      if (!data) return;
      known.current = new Set(data.incidents.map((i) => i.id));
      lastFinished.current = data.refresh.finished_at;
      if (data.refresh.running) setRefresh(data.refresh);
    });
  }, [load]);

  // While a scan runs, poll its status. Otherwise look every 30 s, so a scheduled scan that
  // started or finished in the background shows up. This endpoint makes no outbound or LLM call.
  useEffect(() => {
    const timer = setInterval(
      async () => {
        try {
          const status = await api.monitor.refreshStatus();
          if (status.running) {
            setRefresh(status);
            return;
          }
          if (status.finished_at && status.finished_at !== lastFinished.current) {
            lastFinished.current = status.finished_at;
            setRefresh(null);
            setResult(status);
            setFeed((prev) => prev.map((line) => ({ ...line, done: true })));
            const before = known.current;
            const data = await load();
            if (data) {
              setArrived(new Set(data.incidents.filter((i) => !before.has(i.id)).map((i) => i.id)));
              known.current = new Set(data.incidents.map((i) => i.id));
            }
          } else if (running) {
            setRefresh(null);
          }
        } catch {
          // the next tick tries again
        }
      },
      running ? 1000 : 30000,
    );
    return () => clearInterval(timer);
  }, [running, load]);

  // The scan feed: each new step the backend reports becomes a line; the previous one is done.
  useEffect(() => {
    const raw = refresh?.step;
    if (!refresh?.running || !raw || QUIET_STEPS.has(raw)) return;
    const step = STEP_LABEL[raw] ?? raw;
    setFeed((prev) =>
      prev.at(-1)?.text === step ? prev : [...prev.map((line) => ({ ...line, done: true })), { text: step, done: false }],
    );
  }, [refresh?.running, refresh?.step]);

  useEffect(() => {
    if (!running || !refresh?.started_at) return;
    const started = Date.parse(refresh.started_at);
    const tick = () => setElapsed(Math.max(0, Math.floor((Date.now() - started) / 1000)));
    tick();
    const timer = setInterval(tick, 1000);
    return () => clearInterval(timer);
  }, [running, refresh?.started_at]);

  function changeTab(id: TabId) {
    setTab(id);
    history.replaceState(null, "", id === "threats" ? window.location.pathname : `#${id}`);
  }

  async function startScan(body: { company_id?: string; include_news?: boolean }) {
    setResult(null);
    setActionError(null);
    setFeed([]);
    try {
      setRefresh(await api.monitor.refresh(body));
    } catch (err) {
      setActionError(message(err));
    }
  }

  function replace(updated: Incident) {
    setBoard((prev) =>
      prev ? { ...prev, incidents: prev.incidents.map((i) => (i.id === updated.id ? updated : i)) } : prev,
    );
  }

  async function toggle(incidentId: string, actionId: string, done: boolean) {
    replace(await api.monitor.setAction(incidentId, actionId, done));
    await load(); // the counts in the panel
  }

  async function analyze(incidentId: string) {
    replace(await api.monitor.analyze(incidentId));
  }

  async function loadScan() {
    await api.latestScan(); // the exposure scanner's "load last scan", from local Postgres
    await load();
  }

  async function markAllSeen() {
    setActionError(null);
    try {
      await api.monitor.markSeen();
      await load();
    } catch (err) {
      setActionError(message(err));
    }
  }

  const summary = board?.summary;
  const incidents = board?.incidents ?? [];
  const open = incidents.filter((i) => !i.steps_done);
  const done = incidents.filter((i) => i.steps_done);
  const shown = showDone ? done : open;
  const nothingMonitored = board !== null && board.companies.length === 0 && board.emails.length === 0;
  const newsReady = !!board && board.config.news_search && board.config.local_llm;
  const hasVerifiedEmail = !!board?.emails.some((e) => e.verified);
  const tally = SEVERITIES.map((s) => [s, open.filter((i) => i.severity === s).length] as const).filter(([, n]) => n > 0);
  const watching = summary
    ? [plural(summary.monitored_companies, "company", "companies"), summary.verified_emails > 0 && plural(summary.verified_emails, "verified email")]
        .filter(Boolean)
        .join(" and ")
    : "";

  // One plain sentence that says what's going on.
  let headline = "Loading…";
  let detail = "";
  if (running) {
    headline = "Scanning for threats…";
    detail = `Checking ${watching} against known breaches.`;
  } else if (nothingMonitored) {
    headline = "Nothing to watch yet";
    detail = "Add the companies you use, and we'll check them against known data breaches.";
  } else if (summary && !summary.last_check) {
    headline = `Ready to scan ${watching}`;
    detail = "The first scan takes a few seconds.";
  } else if (summary && open.length > 0) {
    headline = `${plural(open.length, "threat")} ${open.length === 1 ? "needs" : "need"} your attention`;
    detail =
      summary.email_breaches > 0
        ? `Your verified email is in ${summary.email_breaches === 1 ? "one" : summary.email_breaches} of them.`
        : "Each one is a known breach at a company you use. That alone doesn't mean your account was in it.";
  } else if (summary && incidents.length > 0) {
    headline = "No open threats";
    detail = `Every step is marked done on ${plural(incidents.length, "breach", "breaches")}. That's your record, not a guarantee.`;
  } else if (summary) {
    headline = "No known breaches found";
    detail = `None of your companies appear in Have I Been Pwned's breach list. That covers the breaches it has catalogued, not every incident.`;
  }

  return (
    <AuthGate>
      <main className="scanner">
        <div className="work">
          <header>
            <h1>Threat monitor</h1>
            <p className="lede">
              We watch the companies you use for known data breaches and tell you what to do. Matching and explanations
              run on this laptop.
            </p>
          </header>

          <section className={running ? "monitor-panel scanning" : "monitor-panel"} aria-label="Monitor">
            <RadarScope
              scanning={running}
              blips={open.map((i) => ({ id: i.id, severity: i.severity, label: `${i.company}, ${i.severity}` }))}
              label={
                tally.length
                  ? `Radar showing ${tally.map(([s, n]) => `${n} ${s}`).join(", ")} open threats`
                  : "Radar showing no open threats"
              }
            />
            <div className="monitor-status">
              <p className="monitor-headline" aria-live="polite">
                {headline}
              </p>
              {detail && <p className="muted">{detail}</p>}

              {!running && tally.length > 0 && (
                <ul className="tally" aria-label="Open threats by severity">
                  {tally.map(([s, n]) => (
                    <li key={s} className={`sev-${s}`}>
                      <span className="tally-dot" aria-hidden="true" />
                      {n} {SEVERITY_LABEL[s]}
                    </li>
                  ))}
                </ul>
              )}

              {(running || feed.length > 0 || result) && (
                <ol className="scan-feed" aria-label="Scan progress">
                  {feed.map((line) => (
                    <li key={line.text} className={line.done ? "done" : "active"}>
                      {line.text}
                    </li>
                  ))}
                  {!running && result && (
                    <li className="done summary-line">
                      Done
                      {result.started_at && result.finished_at
                        ? ` in ${Math.max(1, Math.round((Date.parse(result.finished_at) - Date.parse(result.started_at)) / 1000))} s`
                        : ""}
                      : {result.new_incidents === 0 ? "no new threats" : plural(result.new_incidents, "new threat")}.
                    </li>
                  )}
                </ol>
              )}

              {nothingMonitored ? (
                <div className="monitor-actions">
                  <button type="button" onClick={() => changeTab("watch")}>
                    Add companies
                  </button>
                </div>
              ) : (
                <div className="monitor-actions">
                  <button type="button" onClick={() => startScan({ include_news: includeNews })} disabled={running || !board}>
                    {running ? `Scanning… ${elapsed} s` : "Scan now"}
                  </button>
                  {newsReady && (
                    <label className="check">
                      <input
                        type="checkbox"
                        checked={includeNews}
                        disabled={running}
                        onChange={(e) => setIncludeNews(e.target.checked)}
                      />
                      <span>Also search the news (about a minute per company)</span>
                    </label>
                  )}
                </div>
              )}
              {summary?.last_check && !running && (
                <p className="muted small" title={localTime(summary.last_check)}>
                  Last scan {timeAgo(summary.last_check)}
                  {board?.schedule.enabled && board.schedule.next_run ? `. Next at ${localTime(board.schedule.next_run)}` : ""}.
                </p>
              )}
            </div>
          </section>

          {result?.errors.map((e) => (
            <p key={e} className="notice">
              <strong>Note:</strong> {e}
            </p>
          ))}
          {actionError && (
            <p className="error" role="alert">
              {actionError}
            </p>
          )}
          {loadError && (
            <p className="error" role="alert">
              {loadError}
            </p>
          )}

          <Tabs tabs={TABS} active={tab} onChange={changeTab} label="Threat monitor sections" />

          <div className="tabpanel" role="tabpanel" id="panel-threats" aria-labelledby="tab-threats" hidden={tab !== "threats"}>
            {board && !nothingMonitored && incidents.length > 0 && (
              <section className="section" aria-labelledby="threats-h">
                <div className="section-head">
                  <h2 id="threats-h">{showDone ? "Steps done" : "Open threats"}</h2>
                  <div className="filter" role="group" aria-label="Show">
                    <button type="button" aria-pressed={!showDone} onClick={() => setShowDone(false)}>
                      Open {open.length}
                    </button>
                    <button type="button" aria-pressed={showDone} onClick={() => setShowDone(true)}>
                      Done {done.length}
                    </button>
                  </div>
                </div>
                {summary && summary.new_alerts > 0 && (
                  <p className="new-banner">
                    <span>{plural(summary.new_alerts, "new threat")} since you last looked.</span>
                    <button type="button" className="quiet inline" onClick={markAllSeen}>
                      Mark all as seen
                    </button>
                  </p>
                )}
                <p className="muted small">Open a threat to see what happened, whether it affects you and what to do.</p>
                {shown.length === 0 && (
                  <p className="muted mt">
                    {showDone ? "No threats have every step marked done yet." : "Nothing open. Every step is marked done."}
                  </p>
                )}
                <div className="threat-list">
                  {shown.map((incident) => (
                    <IncidentCard
                      key={incident.id}
                      incident={incident}
                      arrived={arrived.has(incident.id)}
                      llm={{ ready: board.config.local_llm, model: board.config.local_llm_model }}
                      scanLoaded={board.scan_loaded}
                      hasVerifiedEmail={hasVerifiedEmail}
                      onToggle={(actionId, value) => toggle(incident.id, actionId, value)}
                      onAnalyze={() => analyze(incident.id)}
                      onLoadScan={loadScan}
                      onVerifyEmail={() => changeTab("watch")}
                    />
                  ))}
                </div>
                <p className="muted small attribution">
                  Breach data from{" "}
                  <a href={HIBP_ATTRIBUTION_URL} target="_blank" rel="noopener noreferrer">
                    Have I Been Pwned
                  </a>
                  , licensed CC BY 4.0.
                </p>
              </section>
            )}
            {board && !nothingMonitored && incidents.length === 0 && summary?.last_check && (
              <p className="muted mt">
                No threats right now. To search beyond Have I Been Pwned, tick &ldquo;Also search the news&rdquo; and
                scan again.
              </p>
            )}
          </div>

          <div className="tabpanel" role="tabpanel" id="panel-watch" aria-labelledby="tab-watch" hidden={tab !== "watch"}>
            {board && (
              <>
                <MonitoredCompanies
                  monitored={board.companies}
                  config={board.config}
                  refreshing={running}
                  onChanged={async () => {
                    await load();
                  }}
                  onSearchNews={(companyId) => startScan({ company_id: companyId, include_news: true })}
                />
                <MonitoredEmails
                  emails={board.emails}
                  config={board.config}
                  onChanged={async () => {
                    await load();
                  }}
                />
                <Setup config={board.config} />
              </>
            )}
          </div>

          <div className="tabpanel" role="tabpanel" id="panel-history" aria-labelledby="tab-history" hidden={tab !== "history"}>
            {board && (
              <MonitorActivity
                schedule={board.schedule}
                events={board.events}
                onChanged={async () => {
                  await load();
                }}
              />
            )}
          </div>
        </div>

        <OutboundLog />
      </main>
    </AuthGate>
  );
}
