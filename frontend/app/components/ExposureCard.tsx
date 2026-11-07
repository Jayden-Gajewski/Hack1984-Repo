import type { Exposure, RemovalStatus } from "@/lib/api";
import { DATE_SOURCE_LABEL, REMOVAL_LABEL, TIER_HELP, TIER_LABEL, safeHref } from "@/lib/display";
import TierClaim from "./TierClaim";

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

  return (
    <article className="card">
      <div className="card-head">
        <h3>{exposure.broker}</h3>
        {removal && <span className={`status ${removal}`}>{REMOVAL_LABEL[removal]}</span>}
      </div>

      {top && <TierClaim tier={top.tier} company={top.company} />}

      <ul className="chips" aria-label="Exposed fields">
        {exposure.fields.length === 0 && <li className="muted">Lists your name</li>}
        {exposure.fields.map((f, i) => (
          <li key={`${f.field}-${i}`} className="chip" title={f.quote}>
            {f.field}
          </li>
        ))}
      </ul>

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
        {exposure.fields.length > 0 && (
          <ul className="quotes">
            {exposure.fields.map((f, i) => (
              <li key={`${f.field}-${i}`}>
                <strong>{f.field}</strong>: &ldquo;{f.quote}&rdquo;
              </li>
            ))}
          </ul>
        )}
        <p className="muted">
          {exposure.title && <>{exposure.title}. </>}
          Found with {exposure.found_via ? FOUND_VIA_LABEL[exposure.found_via] : "search"}, read from{" "}
          {exposure.text_source === "extract" ? "the page itself" : "the search snippet"}. Checked on this
          laptop by the local LLM.
        </p>
        {exposure.leads.length > 0 && (
          <>
            <h4>Likely sources</h4>
            <ul className="quotes">
              {exposure.leads.map((lead) => (
                <li key={lead.company}>
                  <span className={`pill ${lead.tier}`} title={TIER_HELP[lead.tier]}>
                    {TIER_LABEL[lead.tier]}
                  </span>
                  <strong>{lead.company}</strong>: {lead.reasons.join(" ")}
                </li>
              ))}
            </ul>
          </>
        )}
      </details>

      <div className="actions">
        {onDraft && (
          <button type="button" className="secondary" onClick={() => onDraft(exposure.id)}>
            Draft opt-out
          </button>
        )}
        {listingHref && (
          <a href={listingHref} target="_blank" rel="noopener noreferrer">
            View listing
          </a>
        )}
        {optOutHref && (
          <a href={optOutHref} target="_blank" rel="noopener noreferrer">
            Opt-out page
          </a>
        )}
      </div>
    </article>
  );
}
