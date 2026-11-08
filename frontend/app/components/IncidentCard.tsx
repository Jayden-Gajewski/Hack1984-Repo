"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import type { Incident } from "@/lib/api";
import {
  CONFIDENCE_LABEL,
  HIBP_ATTRIBUTION_URL,
  INCIDENT_DATE_LABEL,
  INVOLVEMENT_LABEL,
  INVOLVEMENT_SHORT,
  SEVERITY_LABEL,
  TIER_HELP,
  TIER_LABEL,
  localTime,
  safeHref,
} from "@/lib/display";
import CompanyMark from "./CompanyMark";
import SwapLabel from "./SwapLabel";

interface Props {
  incident: Incident;
  arrived: boolean; // first shown by the scan that just finished
  llm: { ready: boolean; model: string };
  scanLoaded: boolean;
  hasVerifiedEmail: boolean;
  onToggle: (actionId: string, done: boolean) => Promise<void>;
  onAnalyze: () => Promise<void>;
  onLoadScan: () => Promise<void>;
  onVerifyEmail: () => void;
}

const message = (err: unknown) => (err instanceof Error ? err.message : String(err));

function linkLabel(link: string): string {
  if (link === "/app") return "Open the exposure scan";
  try {
    return new URL(link).hostname.replace(/^www\./, "");
  } catch {
    return "Open";
  }
}

// One threat: a row you can read at a glance (who, what was exposed, how bad, whether it's you,
// how far along your steps are) that opens into boxes for each question. Everything comes from
// HIBP, public reports or Gemini, so it renders as text, and links go through safeHref().
export default function IncidentCard(props: Props) {
  const { incident, arrived, llm, scanLoaded, hasVerifiedEmail, onToggle, onAnalyze, onLoadScan, onVerifyEmail } = props;
  // Optimistic: a step flips on click and only reverts if saving it fails.
  const [override, setOverride] = useState<Record<string, boolean>>({});
  const [error, setError] = useState<string | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [analyzeError, setAnalyzeError] = useState<string | null>(null);
  const [loadingScan, setLoadingScan] = useState(false);
  const id = `threat-${incident.id}`;
  const isDone = (a: { id: string; done: boolean }) => override[a.id] ?? a.done;
  const done = incident.actions.filter(isDone).length;
  const total = incident.actions.length;
  const severity = SEVERITY_LABEL[incident.severity];
  const analysis = incident.analysis;
  const hibpSource = incident.sources.find((s) => s.kind === "hibp");
  const couldBePublic = incident.data_types.some((t) => t !== "name");
  // Mirrors analysis.fetch_notice(): a breach HIBP doesn't describe gets its official notice read.
  const readsNotice =
    !(hibpSource && incident.description) && incident.sources.some((s) => s.official && s.kind !== "hibp");
  const year = (incident.dates.find((d) => d.kind === "occurred") ?? incident.dates.find((d) => d.kind === "disclosed"))
    ?.date.slice(0, 4);

  useEffect(() => {
    if (!analyzing) return;
    const started = Date.now();
    setElapsed(0);
    const timer = setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => clearInterval(timer);
  }, [analyzing]);

  async function toggle(actionId: string, value: boolean) {
    setOverride((prev) => ({ ...prev, [actionId]: value }));
    setError(null);
    try {
      await onToggle(actionId, value);
    } catch (err) {
      setError(message(err));
    } finally {
      setOverride(({ [actionId]: _, ...rest }) => rest); // the saved state comes back in the props
    }
  }

  async function analyze() {
    setAnalyzing(true);
    setAnalyzeError(null);
    try {
      await onAnalyze();
    } catch (err) {
      setAnalyzeError(message(err));
    } finally {
      setAnalyzing(false);
    }
  }

  async function loadScan() {
    setLoadingScan(true);
    try {
      await onLoadScan();
    } catch (err) {
      setError(message(err));
    } finally {
      setLoadingScan(false);
    }
  }

  return (
    <details className={`threat${arrived ? " arrived" : ""}${incident.steps_done ? " is-done" : ""}`}>
      <summary className="threat-row">
        <CompanyMark name={incident.company} />
        <span className="threat-main">
          <span className="threat-name">
            <strong>{incident.company}</strong>
            {incident.title !== incident.company ? (
              <span className="muted small"> {incident.title}</span>
            ) : (
              year && <span className="muted small"> {year}</span>
            )}
            {incident.new && <span className="new-badge">New</span>}
          </span>
          <span className="threat-what">{incident.threat}</span>
        </span>
        <span className="threat-meta">
          <span className="verdict">
            <span className={`verdict-sev sev-${incident.severity}`}>{severity}</span>
            <span className={`verdict-you you-${incident.involvement}`}>{INVOLVEMENT_SHORT[incident.involvement]}</span>
          </span>
          <span className={incident.steps_done ? "steps-count all" : "steps-count"}>
            {done} of {total} steps
          </span>
        </span>
        <svg className="threat-chevron" width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
          <path d="m4 6 4 4 4-4" />
        </svg>
      </summary>

      <div className="threat-body">
        <div className="box-grid">
          <section className="box" aria-labelledby={`${id}-what`}>
            <h4 id={`${id}-what`}>What happened</h4>
            <ul className="fact-list">
              {incident.dates.map((d) => {
                const href = safeHref(d.source_url);
                return (
                  <li key={`${d.kind}-${d.date}-${d.source}`}>
                    {INCIDENT_DATE_LABEL[d.kind]} <time dateTime={d.date}>{d.date}</time>{" "}
                    <span className="muted">
                      (
                      {href ? (
                        <a href={href} target="_blank" rel="noopener noreferrer">
                          {d.source}
                        </a>
                      ) : (
                        d.source
                      )}
                      )
                    </span>
                  </li>
                );
              })}
              {incident.dates.length === 0 && <li>Date unknown</li>}
              {incident.pwn_count !== null && (
                <li>
                  {incident.pwn_count.toLocaleString()} accounts in it{" "}
                  <span className="muted">(Have I Been Pwned)</span>
                </li>
              )}
              <li>
                {CONFIDENCE_LABEL[incident.confidence]}: <span className="muted">{incident.confidence_reason}</span>
              </li>
            </ul>
            {incident.flags.length > 0 && (
              <ul className="flag-list" aria-label="Caveats">
                {incident.flags.map((f) => (
                  <li key={f}>{f}</li>
                ))}
              </ul>
            )}
          </section>

          <section className={`box affected you-${incident.involvement}`} aria-labelledby={`${id}-you`}>
            <h4 id={`${id}-you`}>Are you affected?</h4>
            <p className="affected-status">{INVOLVEMENT_LABEL[incident.involvement]}</p>
            <p className="muted small">{incident.involvement_reason.replace(/^Not confirmed\.\s*/, "")}</p>
            {incident.involvement === "unconfirmed" && !hasVerifiedEmail && (
              <button type="button" className="secondary mt" onClick={onVerifyEmail}>
                Verify an email to check
              </button>
            )}
          </section>
        </div>

        <section className="box" aria-labelledby={`${id}-steps`}>
          <div className="box-head">
            <h4 id={`${id}-steps`}>What to do</h4>
            <span className="muted small" aria-live="polite">
              {done} of {total} done
            </span>
          </div>
          <ul className="step-list">
            {incident.actions.map((a) => {
              const href = a.link === "/app" ? "/app" : safeHref(a.link);
              return (
                <li key={a.id} className={isDone(a) ? "step done" : "step"}>
                  <label className="check">
                    <input type="checkbox" checked={isDone(a)} onChange={(e) => toggle(a.id, e.target.checked)} />
                    <span>
                      <span className="step-text">{a.text}</span>
                      <span className="muted small step-why">{a.why}</span>
                    </span>
                  </label>
                  {href &&
                    (href === "/app" ? (
                      <Link href="/app" className="step-link">
                        {linkLabel(href)}
                      </Link>
                    ) : (
                      <a href={href} target="_blank" rel="noopener noreferrer" className="step-link">
                        {linkLabel(href)}
                      </a>
                    ))}
                </li>
              );
            })}
          </ul>
          <p className="muted small steps-note">
            {incident.steps_done
              ? "Every step is marked done. That's your record of what you did; it doesn't confirm the account is secure."
              : "Checking a step records what you did. It doesn't mean the account is secure."}
          </p>
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
        </section>

        <section className="box" aria-labelledby={`${id}-exposed`}>
          <h4 id={`${id}-exposed`}>What was exposed</h4>
          <ul className="chips" aria-label="Exposed data">
            {incident.data_classes.length === 0 && <li className="muted">Not reported yet</li>}
            {incident.data_classes.map((c) => (
              <li key={c} className="chip">
                {c}
              </li>
            ))}
          </ul>
          {incident.risks.length > 0 && (
            <>
              <p className="field-lead">This could lead to:</p>
              <ul className="risk-points">
                {incident.risks.map((r) => (
                  <li key={r}>{r}</li>
                ))}
              </ul>
            </>
          )}
        </section>

        <section className="box" aria-labelledby={`${id}-ai`}>
          <h4 id={`${id}-ai`}>In plain English</h4>
          {analysis ? (
            <div className="analysis">
              <p>{analysis.summary}</p>
              <ul className="analysis-points">
                {analysis.impact && (
                  <li>
                    <strong>How it could affect you:</strong> {analysis.impact}
                  </li>
                )}
                <li>
                  <strong>What the sources advise:</strong>{" "}
                  {analysis.guidance || "They don't include official advice."}
                </li>
                {analysis.uncertainty && (
                  <li>
                    <strong>What isn&apos;t known:</strong> {analysis.uncertainty}
                  </li>
                )}
                <li>
                  <strong>Why {severity.toLowerCase()}:</strong> {analysis.severity_explanation}
                </li>
              </ul>
              <p className="muted small">
                Written by {analysis.model}, {localTime(analysis.analyzed_at)}, from the evidence above.
                {analysis.removed_sentences > 0 &&
                  ` ${analysis.removed_sentences} sentence${analysis.removed_sentences === 1 ? " was" : "s were"} removed because the evidence didn't support ${analysis.removed_sentences === 1 ? "it" : "them"}.`}
              </p>
              {analysis.stale && (
                <p className="notice">The facts changed since this was written. Explain again to update it.</p>
              )}
            </div>
          ) : (
            <p className="muted small">A short explanation written by Gemini from the evidence above.</p>
          )}
          <div className="row mt">
            <button type="button" className="secondary" onClick={analyze} disabled={analyzing || !llm.ready} aria-busy={analyzing || undefined}>
              <SwapLabel on={analyzing} idle={analysis ? "Explain again" : "Explain this breach"} active="Explaining…" />
            </button>
            {!analyzing && (
              <span className="muted small">
                {!llm.ready
                  ? "Add GEMINI_API_KEY to .env to use Gemini."
                  : readsNotice
                    ? `Sends the evidence above to Gemini (${llm.model}). It may first read the official notice through Tavily (one public URL). Both show in the outbound log.`
                    : `Sends the evidence above to Gemini (${llm.model}). It shows in the outbound log.`}
              </span>
            )}
          </div>
          {analyzing && (
            <div className="progress" role="status">
              <p className="progress-text">
                <span className="elapsed" aria-hidden="true">
                  {elapsed} s
                </span>
                <span>Asking Gemini. This usually takes a few seconds.</span>
              </p>
              <div className="stripe" aria-hidden="true" />
            </div>
          )}
          {analyzeError && (
            <p className="error" role="alert">
              {analyzeError}
            </p>
          )}
        </section>

        {incident.related_listings.length > 0 && (
          <section className="box" aria-labelledby={`${id}-related`}>
            <h4 id={`${id}-related`}>In your exposure scan</h4>
            <ul className="related-list">
              {incident.related_listings.map((r) => {
                const href = safeHref(r.url);
                return (
                  <li key={r.exposure_id}>
                    <p>
                      <strong>{r.site}</strong> shows your {r.shared_fields.join(", ")}.{" "}
                      {r.lead_tier && (
                        <>
                          <span className={`pill ${r.lead_tier}`} title={TIER_HELP[r.lead_tier]}>
                            {TIER_LABEL[r.lead_tier]}
                          </span>{" "}
                          source for this listing.
                        </>
                      )}
                    </p>
                    <p className="muted small">{r.reason}</p>
                    {href && (
                      <a href={href} target="_blank" rel="noopener noreferrer" className="small">
                        View listing
                      </a>
                    )}
                  </li>
                );
              })}
            </ul>
          </section>
        )}
        {incident.related_listings.length === 0 && couldBePublic && !scanLoaded && (
          <p className="small">
            Is this data public? <Link href="/app">Run an exposure scan</Link>, or{" "}
            <button type="button" className="quiet inline" onClick={loadScan} disabled={loadingScan}>
              {loadingScan ? "loading…" : "load your last scan"}
            </button>{" "}
            to compare.
          </p>
        )}

        <div className="threat-more">
          <details className="detail">
            <summary>Why {severity.toLowerCase()}?</summary>
            <ul className="quotes">
              {incident.severity_reasons.map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
            <p className="muted small">
              Severity comes from fixed rules about the kinds of data exposed. It describes the breach, not whether you
              were in it.
            </p>
          </details>
          <details className="detail">
            <summary>Sources ({incident.sources.length})</summary>
            <ul className="source-list">
              {incident.sources.map((s) => {
                const href = safeHref(s.url);
                return (
                  <li key={s.url}>
                    {href ? (
                      <a href={href} target="_blank" rel="noopener noreferrer">
                        {s.label}
                      </a>
                    ) : (
                      s.label
                    )}
                    {s.official && <span className="muted small"> (official)</span>}
                  </li>
                );
              })}
            </ul>
          </details>
          {incident.description && (
            <details className="detail">
              <summary>{hibpSource ? "Have I Been Pwned's description" : "Report summary"}</summary>
              <p className="description">{incident.description}</p>
              {hibpSource && (
                <p className="muted small">
                  From{" "}
                  <a href={HIBP_ATTRIBUTION_URL} target="_blank" rel="noopener noreferrer">
                    Have I Been Pwned
                  </a>
                  , licensed CC BY 4.0.
                </p>
              )}
            </details>
          )}
        </div>
      </div>
    </details>
  );
}
