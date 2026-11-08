import type { Exposure, RemovalStatus } from "@/lib/api";
import {
  DATE_SOURCE_LABEL,
  REMOVAL_LABEL,
  RISK_LABEL,
  TIER_HELP,
  TIER_LABEL,
  exposureKind,
  safeHref,
} from "@/lib/display";
import FieldIcon from "./FieldIcon";
import TierClaim from "./TierClaim";

const FOUND_VIA_LABEL = { tavily: "Tavily search", exa: "Exa search" } as const;

// The write-up is a few sentences; one bullet each reads faster than a paragraph.
function sentences(text: string): string[] {
  return text.split(/(?<=[.!?])\s+(?=[A-Z])/).map((t) => t.trim()).filter(Boolean);
}

// Everything on this card comes from scraped pages. React escapes text, and links only render
// for http(s) URLs. Never pass this data to dangerouslySetInnerHTML.
interface Props {
  exposure: Exposure;
  onDraft?: (exposureId: string) => void;
  removal?: RemovalStatus; // from the last re-scan
}

export default function ExposureCard({ exposure, onDraft, removal }: Props) {
  const top = exposure.leads[0];
  const listingHref = safeHref(exposure.url);
  const optOutHref = safeHref(exposure.opt_out_url);
  const evidenceHref = safeHref(exposure.public_by_evidence_url);
  const sourceLabel = DATE_SOURCE_LABEL[exposure.public_by_source];
  // Each kind of information once, even when the page shows several values for it.
  const kinds = [...new Set(exposure.fields.map((f) => f.field))];
  const source = exposureKind(exposure.source_kind); // data broker or public profile

  return (
    <article className="card">
      <div className="card-head">
        <div className="card-title">
          <h3>{exposure.broker}</h3>
          <span className="muted small">{source.label}</span>
          {exposure.risk && (
            <span className={`risk ${exposure.risk}`} title={exposure.risk_reason}>
              {RISK_LABEL[exposure.risk]}
            </span>
          )}
          {removal && <span className={`status ${removal}`}>{REMOVAL_LABEL[removal]}</span>}
        </div>
      </div>

      {top && <TierClaim tier={top.tier} company={top.company} />}

      <ul className="chips" aria-label="Exposed fields">
        {kinds.length === 0 && <li className="muted">Lists your name</li>}
        {kinds.map((field) => (
          <li key={field} className="chip">
            {field}
          </li>
        ))}
      </ul>

      {exposure.summary && (
        <ul className="summary-points">
          {sentences(exposure.summary).map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      )}

      <p className="date-line">
        Public by <strong>{exposure.public_by ?? "unknown"}</strong>
        {exposure.public_by && (
          <>
            . Source:{" "}
            {evidenceHref ? (
              <a href={evidenceHref} target="_blank" rel="noopener noreferrer">
                {sourceLabel}
              </a>
            ) : (
              sourceLabel
            )}
          </>
        )}
      </p>

      {exposure.text_source === "snippet" && (
        <p className="muted small">From search snippet; page blocked extraction.</p>
      )}

      <details className="detail">
        <summary>Details</summary>
        {exposure.risk && (
          <p className={`risk-callout ${exposure.risk}`}>
            <strong>{RISK_LABEL[exposure.risk]}</strong>
            <span>{exposure.risk_reason}</span>
          </p>
        )}

        {exposure.insights.length > 0 && (
          <div className="field-grid">
            {exposure.insights.map((insight) => (
              <section key={insight.field} className="field-box" aria-labelledby={`${exposure.id}-${insight.field}`}>
                <header className="field-box-head">
                  <span className="field-badge">
                    <FieldIcon field={insight.field} />
                  </span>
                  <h4 id={`${exposure.id}-${insight.field}`}>{insight.label}</h4>
                  <span className="field-count">{insight.found.length} found</span>
                </header>
                <ul className="field-values" aria-label="What the page shows">
                  {insight.found.map((value, i) => (
                    <li key={i}>{value}</li>
                  ))}
                </ul>
                <p className="field-why">{insight.why_it_matters}</p>
                <p className="field-lead">Someone could:</p>
                <ul className="field-misuse">
                  {insight.misuse.map((use, i) => (
                    <li key={i}>{use}</li>
                  ))}
                </ul>
                <p className="field-protect">
                  <strong>Protect yourself</strong>
                  <span>{insight.protect}</span>
                </p>
              </section>
            ))}
          </div>
        )}
        {exposure.insights.length === 0 && exposure.fields.length > 0 && (
          <ul className="field-values">
            {exposure.fields.map((f, i) => (
              <li key={`${f.field}-${i}`}>
                <strong>{f.field}</strong>: {f.quote}
              </li>
            ))}
          </ul>
        )}

        {exposure.leads.length > 0 && (
          <section className="leads-box">
            <h4>Likely sources</h4>
            <ul>
              {exposure.leads.map((lead) => (
                <li key={lead.company}>
                  <span className={`pill ${lead.tier}`} title={TIER_HELP[lead.tier]}>
                    {TIER_LABEL[lead.tier]}
                  </span>{" "}
                  <strong>{lead.company}</strong>
                  <ul className="lead-reasons">
                    {lead.reasons.map((reason) => (
                      <li key={reason}>{reason}</li>
                    ))}
                  </ul>
                </li>
              ))}
            </ul>
          </section>
        )}

        <ul className="found-how" aria-label="How this was found">
          {exposure.title && <li>Page title: {exposure.title}</li>}
          <li>Found with {exposure.found_via ? FOUND_VIA_LABEL[exposure.found_via] : "a search"}</li>
          <li>Read from {exposure.text_source === "extract" ? "the page itself" : "the search snippet"}</li>
          <li>Checked on this laptop by the local LLM</li>
        </ul>
      </details>

      <div className="actions">
        {onDraft && (
          <button type="button" className="secondary" onClick={() => onDraft(exposure.id)}>
            {source.draft}
          </button>
        )}
        {listingHref && (
          <a href={listingHref} target="_blank" rel="noopener noreferrer">
            {source.view}
          </a>
        )}
        {optOutHref && (
          <a href={optOutHref} target="_blank" rel="noopener noreferrer">
            {source.page}
          </a>
        )}
      </div>
    </article>
  );
}
