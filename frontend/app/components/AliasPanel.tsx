"use client";

import { useEffect, useState } from "react";
import { api, type Alias, type AliasHit, type Company } from "@/lib/api";
import { TIER_HELP, TIER_LABEL } from "@/lib/display";

interface Props {
  onChecked: () => void; // refresh the likely sources on the cards
}

// Stage 7: a unique alias per signup, and a local check of the (mock) inbox.
export default function AliasPanel({ onChecked }: Props) {
  const [aliases, setAliases] = useState<Alias[]>([]);
  const [companies, setCompanies] = useState<Company[]>([]);
  const [company, setCompany] = useState("");
  const [hits, setHits] = useState<AliasHit[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fail = (err: unknown) => setError(err instanceof Error ? err.message : String(err));

  useEffect(() => {
    api.aliases().then(setAliases, fail);
    api.companies().then((list) => {
      setCompanies(list);
      setCompany(list[0]?.id ?? "");
    }, fail);
  }, []);

  async function create() {
    setError(null);
    try {
      const alias = await api.newAlias(company);
      setAliases((prev) => [...prev, alias]);
    } catch (err) {
      fail(err);
    }
  }

  async function checkInbox() {
    setError(null);
    try {
      setHits(await api.checkInbox());
      onChecked();
    } catch (err) {
      fail(err);
    }
  }

  return (
    <div className="panel">
      <h2>Aliases</h2>
      <p className="muted">
        Sign up with a different alias for each company. If mail to that alias comes from anyone else,
        we know where your address went.
      </p>
      <p className="row">
        <select value={company} onChange={(e) => setCompany(e.target.value)} aria-label="Company">
          {companies.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
        <button type="button" className="secondary" onClick={create} disabled={!company}>
          New alias for this company
        </button>
      </p>
      <ul className="quotes">
        {aliases.map((a) => (
          <li key={a.alias}>
            <code>{a.alias}</code> <span className="muted">· {a.company} · {a.created_at}</span>
          </li>
        ))}
      </ul>
      <button type="button" onClick={checkInbox}>
        Check inbox (mock)
      </button>
      <p className="muted">Runs on this laptop. Nothing is searched.</p>
      {error && <p className="error">{error}</p>}
      {hits && hits.length === 0 && <p className="muted">No mail from outside the companies you signed up with.</p>}
      {hits?.map((h, i) => (
        <article key={i} className="card">
          <div className="card-head">
            <strong>{h.company}</strong>
            <span className="badge proven" title={TIER_HELP.proven}>
              {TIER_LABEL.proven} · likely source: {h.company}
            </span>
          </div>
          <p>
            Mail to <code>{h.alias}</code>, which you gave only to {h.company}, came from{" "}
            <strong>{h.from_domain}</strong>
            {h.date && <> on {h.date}</>}: &ldquo;{h.subject}&rdquo;
          </p>
        </article>
      ))}
    </div>
  );
}
