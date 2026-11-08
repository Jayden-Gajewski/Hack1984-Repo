"use client";

import { useEffect, useRef, useState } from "react";
import { api, type Company, type TrackedCompany, type TrackedCompanyInput } from "@/lib/api";
import { OPEN_STATUSES, formatDay, formatSavedDay, websiteHost } from "@/lib/display";
import CompanyForm from "./FootprintCompanyForm";
import FootprintCompany from "./FootprintCompany";
import { StatusPill } from "./FootprintRequest";
import { Chevron } from "./icons";
import "../footprint.css";
import Skeleton from "./Skeleton";

const message = (err: unknown) => (err instanceof Error ? err.message : String(err));

// Most recently changed first, the order the backend returns.
const byRecent = (a: TrackedCompany, b: TrackedCompany) => Date.parse(b.updated_at) - Date.parse(a.updated_at);

// What a row shows: the latest request's status, how many are still open, and the last date.
function summarize(company: TrackedCompany) {
  const latest = [...company.requests].sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at))[0];
  const lastStep = company.requests
    .flatMap((r) => r.history.map((step) => step.happened_on))
    .sort()
    .at(-1);
  const open = company.requests.filter((r) => OPEN_STATUSES.has(r.status)).length;
  const when = lastStep
    ? `Last step ${formatDay(lastStep)} (you recorded)`
    : latest
      ? `Draft saved ${formatSavedDay(latest.created_at)}`
      : `Added ${formatSavedDay(company.created_at)}`;
  return { latest, open, when };
}

// Feature 3, the Footprint tab: companies that hold the user's data and the requests they make
// to them. Everything is stored in the local database for the signed-in account. Dossier never
// sends a request, contacts a company or changes its settings; the user does, then records it.
export default function FootprintPanel() {
  const [companies, setCompanies] = useState<TrackedCompany[] | null>(null);
  const [suggestions, setSuggestions] = useState<Company[]>([]);
  const [error, setError] = useState<{ text: string; status?: number } | null>(null);
  const [adding, setAdding] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);
  const rows = useRef(new Map<string, HTMLButtonElement>());
  const returnTo = useRef<string | null>(null);

  function load() {
    setError(null);
    api.footprint().then(setCompanies, (err) => setError({ text: message(err), status: (err as { status?: number }).status }));
  }

  useEffect(() => {
    load();
    api.companies().then(setSuggestions, () => {}); // name suggestions only; the form works without them
  }, []);

  // Going back to the list puts focus on the row you came from.
  useEffect(() => {
    if (openId !== null || !returnTo.current) return;
    rows.current.get(returnTo.current)?.focus();
    returnTo.current = null;
  }, [openId]);

  function saved(company: TrackedCompany) {
    setCompanies((prev) => [company, ...(prev ?? []).filter((c) => c.id !== company.id)].sort(byRecent));
  }

  async function add(value: TrackedCompanyInput) {
    const company = await api.trackCompany(value);
    saved(company);
    setAdding(false);
    setOpenId(company.id); // next step: draft a request
  }

  function removed(id: string) {
    setCompanies((prev) => (prev ?? []).filter((c) => c.id !== id));
    setOpenId(null);
  }

  const open = companies?.find((c) => c.id === openId) ?? null;
  const empty = companies !== null && companies.length === 0;

  return (
    <section className="section fp" aria-labelledby="footprint-h">
      <div className="task-panel">
        <div className="fp-head">
          <h2 id="footprint-h">Your digital footprint</h2>
          {!open && !adding && !empty && companies !== null && (
            <button type="button" onClick={() => setAdding(true)}>
              Add company
            </button>
          )}
        </div>
        <p className="muted fp-lede">
          Keep track of the companies that hold your data and the requests you make to them. It&apos;s saved on
          this laptop only. Dossier never sends a request or changes a company&apos;s settings for you.
        </p>
        {empty && !open && (
          <p className="fp-empty">
            No companies yet. Start with an account you&apos;d like to check on or close, like a shop, an app or a
            bank. Then you can draft a request for a copy of your data, or for its deletion.
          </p>
        )}
        {(adding || empty) && !open && (
          <CompanyForm
            title={empty ? "Add your first company" : "Add a company"}
            suggestions={suggestions}
            submitLabel="Add company"
            onSubmit={add}
            onCancel={empty ? undefined : () => setAdding(false)}
            autoFocus={adding}
          />
        )}
        {error && (
          <p className="error" role="alert">
            {error.text}{" "}
            {error.status === 401 ? (
              <a href="/login?next=/app">Log in again</a>
            ) : (
              <button type="button" className="quiet" onClick={load}>
                Try again
              </button>
            )}
          </p>
        )}
        {companies === null && !error && <Skeleton label="Loading your footprint" rows={3} />}
      </div>

      {open ? (
        <FootprintCompany
          key={open.id}
          company={open}
          suggestions={suggestions}
          onSaved={saved}
          onRemoved={removed}
          onBack={() => {
            returnTo.current = open.id;
            setOpenId(null);
          }}
        />
      ) : (
        companies !== null &&
        companies.length > 0 && (
          <div className="fp-ledger">
            <h3 className="fp-count">
              {companies.length} {companies.length === 1 ? "company" : "companies"}
            </h3>
            <ul className="fp-list">
              {companies.map((c) => {
                const { latest, open: openCount, when } = summarize(c);
                return (
                  <li key={c.id}>
                    <button
                      type="button"
                      className="fp-row"
                      ref={(el) => {
                        if (el) rows.current.set(c.id, el);
                        else rows.current.delete(c.id);
                      }}
                      onClick={() => setOpenId(c.id)}
                    >
                      <span className="fp-row-name">
                        {c.name}
                        {c.website && <span className="fp-row-site">{websiteHost(c.website)}</span>}
                      </span>
                      <span className="fp-row-status">
                        {latest ? <StatusPill status={latest.status} /> : <span className="muted small">No requests yet</span>}
                        {openCount > 1 && <span className="muted small">{openCount} open</span>}
                      </span>
                      <span className="fp-row-when">{when}</span>
                      <Chevron />
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>
        )
      )}
    </section>
  );
}
