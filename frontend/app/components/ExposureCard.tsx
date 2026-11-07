import type { Exposure } from "@/lib/api";
import { DATE_SOURCE_LABEL, TIER_HELP, TIER_LABEL, safeHref } from "@/lib/display";

const FOUND_VIA_LABEL = { tavily: "Tavily search", exa: "Exa search" } as const;

// Everything on this card comes from scraped pages. React escapes text, and links only render
// for http(s) URLs. Never pass this data to dangerouslySetInnerHTML.
export default function ExposureCard({ exposure }: { exposure: Exposure }) {
  const top = exposure.leads[0];
  const listingHref = safeHref(exposure.url);
  const optOutHref = safeHref(exposure.opt_out_url);
  const evidenceHref = safeHref(exposure.public_by_evidence_url);
  const sourceLabel = DATE_SOURCE_LABEL[exposure.public_by_source];

  return (
    <article className="card">
      <div className="card-head">
        <strong>{exposure.broker}</strong>
        {top && (
          <span className={`badge ${top.tier}`} title={TIER_HELP[top.tier]}>
            {TIER_LABEL[top.tier]} · likely source: {top.company}
          </span>
        )}
      </div>

      <div className="chips">
        {exposure.fields.length === 0 && <span className="muted">Lists your name</span>}
        {exposure.fields.map((f, i) => (
          <span key={`${f.field}-${i}`} className="chip" title={f.quote}>
            {f.field}
          </span>
        ))}
      </div>

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
      </p>
    </article>
  );
}
