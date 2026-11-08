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
import CompanyPicker from "./CompanyPicker";

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
  const [checked, setChecked] = useState<string[]>([]);
  const [result, setResult] = useState<AccountsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.companies().then(setCompanies, (err) => setError(err instanceof Error ? err.message : String(err)));
  }, []);

  const add = (id: string) => setPicked((prev) => new Set(prev).add(id));

  // Any company not in the list: the backend finds its website (one logged search) and saves it.
  async function create(name: string) {
    const company = await api.addCompany(name);
    setCompanies((prev) => (prev.some((c) => c.id === company.id) ? prev : [...prev, company]));
    add(company.id);
    return company;
  }
  function remove(id: string) {
    setPicked((prev) => {
      const next = new Set(prev);
      next.delete(id);
      return next;
    });
  }

  async function check() {
    const ids = [...picked];
    setLoading(true);
    setError(null);
    try {
      setResult(await api.accounts(ids));
      setChecked(ids);
      onChecked();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Check failed");
    } finally {
      setLoading(false);
    }
  }

  const name = (id: string) => companies.find((c) => c.id === id)?.name ?? id;

  return (
    <section className="section" aria-labelledby="accounts-h">
      <div className="task-panel">
        <h2 id="accounts-h">Your accounts</h2>
        <p className="muted">Add the companies you have accounts with. We search with the company name only.</p>
        <CompanyPicker companies={companies} selected={[...picked]} onAdd={add} onRemove={remove} onCreate={create} />
        <div className="row mt">
          <button type="button" onClick={check} disabled={picked.size === 0 || loading}>
            {loading ? "Checking…" : "Check breaches & policies"}
          </button>
          <span className="muted small" role="status">
            {loading
              ? `Checking ${picked.size} ${picked.size === 1 ? "company" : "companies"}. About a minute each.`
              : picked.size === 0
                ? "Add at least one company."
                : ""}
          </span>
        </div>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
      </div>

      {result && (
        <div className="cards results">
          {result.errors.map((err, i) => (
            <p key={i} className="notice">
              <strong>Note:</strong> {err}
            </p>
          ))}
          {checked.map((id) => {
            const breaches = result.breaches.filter((b) => b.company_id === id);
            const policy = result.policies.find((p) => p.company_id === id);
            const sold = policy?.clauses.filter((c) => SELL_OR_SHARE.has(c.category)) ?? [];
            const also = policy?.clauses.filter((c) => !SELL_OR_SHARE.has(c.category)) ?? [];
            const policyHref = safeHref(policy?.policy_url);
            return (
              <article key={id} className="card">
                <div className="card-head">
                  <h3>{name(id)}</h3>
                  <button type="button" className="secondary" onClick={() => onDraft(id)} disabled={!canDraft}>
                    Draft privacy request
                  </button>
                </div>
                {!canDraft && <p className="muted small">Run a scan, or load the last one, to draft a request.</p>}

                {sold.length > 0 && (
                  <div className="flag">
                    <strong>This wasn&apos;t a hack, they sold it.</strong>
                    {sold.map((c, i) => (
                      <blockquote key={i}>
                        &ldquo;{c.quote}&rdquo;
                        <span className="muted">
                          {POLICY_CATEGORY_LABEL[c.category]}: {c.explanation}
                        </span>
                      </blockquote>
                    ))}
                  </div>
                )}

                <h4>Breaches</h4>
                {breaches.length === 0 && <p className="muted">No breaches found.</p>}
                <ul className="timeline">
                  {breaches.map((b, i) => {
                    const href = safeHref(b.source_url);
                    return (
                      <li key={i}>
                        <p>
                          <strong>{b.date ?? "Date unknown"}</strong>
                          {b.date && <> ({DATE_KIND_LABEL[b.date_kind]})</>}. Source:{" "}
                          {href ? (
                            <a href={href} target="_blank" rel="noopener noreferrer">
                              {SOURCE_KIND_LABEL[b.source_kind]}
                            </a>
                          ) : (
                            SOURCE_KIND_LABEL[b.source_kind]
                          )}
                        </p>
                        <ul className="chips" aria-label="Exposed data">
                          {b.data_types.map((t) => (
                            <li key={t} className="chip">
                              {t}
                            </li>
                          ))}
                        </ul>
                        <p className="muted">{b.summary}</p>
                      </li>
                    );
                  })}
                </ul>

                <h4>
                  Privacy policy
                  {policyHref && (
                    <>
                      {" "}
                      <a href={policyHref} target="_blank" rel="noopener noreferrer" className="small">
                        Read it
                      </a>
                    </>
                  )}
                </h4>
                {!policy && <p className="muted">Couldn&apos;t read this company&apos;s privacy policy.</p>}
                {policy && policy.clauses.length === 0 && (
                  <p className="muted">No clauses about selling or sharing data were found.</p>
                )}
                {also.length > 0 && (
                  <div>
                    <p className="muted">The policy also allows:</p>
                    {also.map((c, i) => (
                      <blockquote key={i}>
                        &ldquo;{c.quote}&rdquo;
                        <span className="muted">{POLICY_CATEGORY_LABEL[c.category]}</span>
                      </blockquote>
                    ))}
                  </div>
                )}
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}
