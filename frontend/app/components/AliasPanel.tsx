"use client";

import { useEffect, useState } from "react";
import { api, type Alias, type AliasHit, type Company } from "@/lib/api";
import TierClaim from "./TierClaim";

interface Props {
  onChecked: () => void; // refresh the likely sources on the cards
}

// Stage 7: a unique alias per signup, and a local check of the (mock) inbox.
export default function AliasPanel({ onChecked }: Props) {
  const [aliases, setAliases] = useState<Alias[]>([]);
  const [companies, setCompanies] = useState<Company[]>([]);
  const [company, setCompany] = useState("");
  const [hits, setHits] = useState<AliasHit[] | null>(null);
  const [busy, setBusy] = useState<"create" | "inbox" | null>(null);
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
    setBusy("create");
    try {
      const alias = await api.newAlias(company);
      setAliases((prev) => [...prev, alias]);
    } catch (err) {
      fail(err);
    } finally {
      setBusy(null);
    }
  }

  async function checkInbox() {
    setError(null);
    setBusy("inbox");
    try {
      setHits(await api.checkInbox());
      onChecked();
    } catch (err) {
      fail(err);
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="section" aria-labelledby="aliases-h">
      <div className="task-panel">
        <h2 id="aliases-h">Your aliases</h2>
        <p className="muted">
          Sign up with a different alias for each company. If mail to that alias comes from anyone else,
          we know where your address went.
        </p>
        <div className="row">
          <select value={company} onChange={(e) => setCompany(e.target.value)} aria-label="Company">
            {companies.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
          <button type="button" className="secondary" onClick={create} disabled={!company || busy !== null}>
            {busy === "create" ? "Creating…" : "New alias for this company"}
          </button>
        </div>

        {aliases.length > 0 && (
          <ul className="alias-list">
            {aliases.map((a) => (
              <li key={a.alias}>
                <code>{a.alias}</code>
                <span className="muted small">
                  for {a.company}, created {a.created_at}
                </span>
              </li>
            ))}
          </ul>
        )}

        <div className={aliases.length > 0 ? "row" : "row mt"}>
          <button type="button" onClick={checkInbox} disabled={busy !== null}>
            {busy === "inbox" ? "Checking…" : "Check inbox (mock)"}
          </button>
          <span className="muted small">Runs on this laptop. Nothing is searched.</span>
        </div>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}

        <div role="status">
          {hits && hits.length === 0 && (
            <p className="muted mt">
              No mail from outside the companies you signed up with.
            </p>
          )}
        </div>
      </div>

      {hits && hits.length > 0 && (
        <div className="cards results">
          {hits.map((h, i) => (
            <article key={i} className="card">
              <h3>{h.company}</h3>
              <TierClaim tier="proven" company={h.company} />
              <p className="mt">
                Mail to <code>{h.alias}</code>, which you gave only to {h.company}, came from{" "}
                <strong>{h.from_domain}</strong>
                {h.date && <> on {h.date}</>}: &ldquo;{h.subject}&rdquo;
              </p>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
