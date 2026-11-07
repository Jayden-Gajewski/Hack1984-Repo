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

const FOUND_VIA_LABEL = { tavily: "Tavily search", exa: "Exa search" } as const;

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
        <span className="card-title">
          <strong>{exposure.broker}</strong>
          <span className="muted">{source.label}</span>
          {exposure.risk && (
            <span className={`risk ${exposure.risk}`} title={exposure.risk_reason}>
              {RISK_LABEL[exposure.risk]}
            </span>
          )}
          {removal && <span className={`status ${removal}`}>{REMOVAL_LABEL[removal]}</span>}
        </span>
        {top && (
          <span className="lead-badge" title={TIER_HELP[top.tier]}>
            Likely source: <strong>{top.company}</strong>
            <span className={`tier ${top.tier}`}>{TIER_LABEL[top.tier]}</span>
          </span>
        )}
      </div>

      <div className="chips">
        {kinds.length === 0 && <span className="muted">Lists your name</span>}
        {kinds.map((field) => (
          <span key={field} className="chip">
            {field}
          </span>
        ))}
      </div>

      {exposure.summary && <p>{exposure.summary}</p>}

      <p className="muted">
        Public by: {exposure.public_by ?? "unknown"}
        {exposure.public_by && (
          <>
            {" ("}
            {evidenceHref ? (
              <a href={evidenceHref} target="_blank" rel="noopener noreferrer">
                {sourceLabel}
              </a>
            ) : (
              sourceLabel
            )}
            {")"}
          </>
        )}
      </p>

      {exposure.text_source === "snippet" && (
        <p className="muted">From search snippet; page blocked extraction.</p>
      )}

      <details className="detail">
        <summary>Details</summary>
        {exposure.risk && (
          <p>
            <strong>{RISK_LABEL[exposure.risk]}.</strong> {exposure.risk_reason}
          </p>
        )}
        {exposure.insights.map((insight) => (
          <section key={insight.field} className="insight">
            <h4>{insight.label}</h4>
            <p className="muted">What the page shows:</p>
            <ul className="quotes">
              {insight.found.map((value, i) => (
                <li key={i}>&ldquo;{value}&rdquo;</li>
              ))}
            </ul>
            <p>
              <strong>Why it matters:</strong> {insight.why_it_matters}
            </p>
            <p>
              <strong>What someone could do with it:</strong>
            </p>
            <ul className="quotes">
              {insight.misuse.map((use, i) => (
                <li key={i}>{use}</li>
              ))}
            </ul>
            <p>
              <strong>Protect yourself:</strong> {insight.protect}
            </p>
          </section>
        ))}
        {exposure.insights.length === 0 && exposure.fields.length > 0 && (
          <ul className="quotes">
            {exposure.fields.map((f, i) => (
              <li key={`${f.field}-${i}`}>
                <strong>{f.field}</strong>: &ldquo;{f.quote}&rdquo;
              </li>
            ))}
          </ul>
        )}
        <p className="muted">
          {exposure.title && <>{exposure.title} · </>}
          Found with {exposure.found_via ? FOUND_VIA_LABEL[exposure.found_via] : "search"}, read from{" "}
          {exposure.text_source === "extract" ? "the page itself" : "the search snippet"}. Checked
          on this laptop by the local LLM.
        </p>
        {exposure.leads.length > 0 && (
          <div>
            <strong>Likely sources</strong>
            <ul className="quotes">
              {exposure.leads.map((lead) => (
                <li key={lead.company}>
                  <span className={`badge ${lead.tier}`} title={TIER_HELP[lead.tier]}>
                    {TIER_LABEL[lead.tier]}
                  </span>{" "}
                  {lead.company}: {lead.reasons.join(" ")}
                </li>
              ))}
            </ul>
          </div>
        )}
      </details>

      <p className="row">
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
      </p>
    </article>
  );
}
