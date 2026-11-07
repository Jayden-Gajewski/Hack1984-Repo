"use client";

import { useEffect, useState } from "react";
import { api, type AccountsResponse, type Company } from "@/lib/api";
import {
  DATE_KIND_LABEL,
  POLICY_CATEGORY_LABEL,
  SELL_OR_SHARE,
  SOURCE_KIND_LABEL,
  safeHref,
} from "@/lib/display";

interface Props {
  onChecked: () => void; // refresh the likely sources on the cards
  onDraft: (companyId: string) => void;
  canDraft: boolean;
}

// Stages 3 and 4: pick your accounts, then see each company's breaches and policy flags.
// Everything shown here comes from scraped pages, so it's rendered as text only.
export default function AccountsPanel({ onChecked, onDraft, canDraft }: Props) {
  const [companies, setCompanies] = useState<Company[]>([]);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [result, setResult] = useState<AccountsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.companies().then(setCompanies, (err) => setError(err instanceof Error ? err.message : String(err)));
  }, []);

  function toggle(id: string) {
    setPicked((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function check() {
    setLoading(true);
    setError(null);
    try {
      setResult(await api.accounts([...picked]));
      onChecked();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Check failed");
    } finally {
      setLoading(false);
    }
  }

  const name = (id: string) => companies.find((c) => c.id === id)?.name ?? id;

  return (
    <div className="panel">
      <h2>Your accounts</h2>
      <p className="muted">Pick companies you have accounts with. We search with the company name only.</p>
      <div className="checks">
        {companies.map((c) => (
          <label key={c.id} className="consent">
            <input type="checkbox" checked={picked.has(c.id)} onChange={() => toggle(c.id)} />
            <span>{c.name}</span>
          </label>
        ))}
      </div>
      <button type="button" onClick={check} disabled={picked.size === 0 || loading}>
        {loading ? "Checking… (about a minute per company)" : "Check breaches & policies"}
      </button>
      {error && <p className="error">{error}</p>}

      {result && (
        <div>
          {result.errors.map((err, i) => (
            <p key={i} className="muted">
              {err}
            </p>
          ))}
          {[...picked].filter((id) => result.policies.some((p) => p.company_id === id) || result.breaches.some((b) => b.company_id === id)).map((id) => {
            const breaches = result.breaches.filter((b) => b.company_id === id);
            const policy = result.policies.find((p) => p.company_id === id);
            const sold = policy?.clauses.filter((c) => SELL_OR_SHARE.has(c.category)) ?? [];
            const also = policy?.clauses.filter((c) => !SELL_OR_SHARE.has(c.category)) ?? [];
            const policyHref = safeHref(policy?.policy_url);
            return (
              <article key={id} className="card">
                <div className="card-head">
                  <strong>{name(id)}</strong>
                  <button type="button" className="secondary" onClick={() => onDraft(id)} disabled={!canDraft}
                    title={canDraft ? "" : "Run a scan (or load the last one) first"}>
                    Draft privacy request
                  </button>
                </div>

                <h3>Breaches</h3>
                {breaches.length === 0 && <p className="muted">No breaches found.</p>}
                <ul className="timeline">
                  {breaches.map((b, i) => {
                    const href = safeHref(b.source_url);
                    return (
                      <li key={i}>
                        <strong>{b.date ?? "unknown"}</strong> {b.date && DATE_KIND_LABEL[b.date_kind]} ·{" "}
                        {href ? (
                          <a href={href} target="_blank" rel="noopener noreferrer">
                            {SOURCE_KIND_LABEL[b.source_kind]}
                          </a>
                        ) : (
                          SOURCE_KIND_LABEL[b.source_kind]
                        )}
                        <div className="chips">
                          {b.data_types.map((t) => (
                            <span key={t} className="chip">
                              {t}
                            </span>
                          ))}
                        </div>
                        <span className="muted">{b.summary}</span>
                      </li>
                    );
                  })}
                </ul>

                <h3>
                  Privacy policy{" "}
                  {policyHref && (
                    <a href={policyHref} target="_blank" rel="noopener noreferrer" className="muted">
                      (read it)
                    </a>
                  )}
                </h3>
                {sold.length > 0 && (
                  <div className="flag">
                    <strong>This wasn&apos;t a hack, they sold it.</strong>
                    {sold.map((c, i) => (
                      <blockquote key={i}>
                        &ldquo;{c.quote}&rdquo;
                        <span className="muted"> {POLICY_CATEGORY_LABEL[c.category]}: {c.explanation}</span>
                      </blockquote>
                    ))}
                  </div>
                )}
                {also.length > 0 && (
                  <div>
                    <span className="muted">The policy also allows:</span>
                    {also.map((c, i) => (
                      <blockquote key={i}>
                        &ldquo;{c.quote}&rdquo;
                        <span className="muted"> {POLICY_CATEGORY_LABEL[c.category]}</span>
                      </blockquote>
                    ))}
                  </div>
                )}
                {policy && policy.clauses.length === 0 && (
                  <p className="muted">No clauses about selling or sharing data were found.</p>
                )}
              </article>
            );
          })}
        </div>
      )}
    </div>
  );
}
