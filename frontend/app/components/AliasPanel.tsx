"use client";

import { useEffect, useMemo, useState } from "react";
import {
  api,
  type Alias,
  type AliasHit,
  type AliasInvestigation,
  type AliasMessage,
  type Company,
} from "@/lib/api";
import {
  ALIAS_CATEGORY_LABEL,
  BLOCKED_HELP,
  SENDER_KIND_LABEL,
  TIER_HELP,
  TIER_LABEL,
  aliasMadeSource,
} from "@/lib/display";
import TierClaim from "./TierClaim";
import SwapLabel from "./SwapLabel";

interface Props {
  onChecked: () => void; // refresh the likely sources on the cards
}

const errorText = (err: unknown) => (err instanceof Error ? err.message : String(err));

// Aliases that got mail from someone unexpected come first (that's the evidence), then newest.
function byEvidenceThenNewest(a: Alias, b: Alias): number {
  const unexpected = Number(b.unexpected_count > 0) - Number(a.unexpected_count > 0);
  return unexpected || b.created_at.localeCompare(a.created_at);
}

function plural(n: number, one: string, many = `${one}s`) {
  return `${n} ${n === 1 ? one : many}`;
}

// The email identity manager: one alias per signup, a way to turn one off, and a local look at
// who wrote to it. Mail comes from a mock inbox; nothing here receives real email.
export default function AliasPanel({ onChecked }: Props) {
  const [aliases, setAliases] = useState<Alias[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [companies, setCompanies] = useState<Company[]>([]);
  const [target, setTarget] = useState("");
  const [newest, setNewest] = useState<string | null>(null);
  const [hits, setHits] = useState<AliasHit[] | null>(null);
  const [busy, setBusy] = useState<"create" | "inbox" | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.aliases().then(
      (list) => {
        setAliases(list);
        setLoaded(true);
      },
      (err) => {
        setError(errorText(err));
        setLoaded(true);
      },
    );
    api.companies().then(setCompanies, (err) => setError(errorText(err)));
  }, []);

  const sorted = useMemo(() => [...aliases].sort(byEvidenceThenNewest), [aliases]);
  const mine = aliases.filter((a) => !a.demo).length;

  function replace(updated: Alias) {
    setAliases((prev) => prev.map((a) => (a.alias === updated.alias ? updated : a)));
  }

  async function create(event: React.FormEvent) {
    event.preventDefault();
    const typed = target.trim();
    if (!typed) return;
    setError(null);
    setBusy("create");
    try {
      // A company from the list makes a company alias; anything else is treated as a website.
      const company = companies.find((c) => c.name.toLowerCase() === typed.toLowerCase() || c.id === typed.toLowerCase());
      const alias = company ? await api.newAlias(company.id) : await api.newSiteAlias(typed);
      setAliases((prev) => [alias, ...prev]);
      setNewest(alias.alias);
      setTarget("");
    } catch (err) {
      setError(errorText(err));
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
      setError(errorText(err));
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="section" aria-labelledby="aliases-h">
      <div className="task-panel">
        <h2 id="aliases-h">Your aliases</h2>
        <p className="muted">
          Give each website its own address. If anyone else writes to it, you&apos;ll know where your
          address went.
        </p>

        <form className="alias-create" onSubmit={create}>
          <label htmlFor="alias-target">Website or company</label>
          <div className="row">
            <input
              id="alias-target"
              type="text"
              list="alias-companies"
              value={target}
              onChange={(e) => setTarget(e.target.value)}
              placeholder="shop.example or a company"
              autoComplete="off"
              spellCheck={false}
              aria-describedby="alias-target-help"
            />
            <datalist id="alias-companies">
              {companies.map((c) => (
                <option key={c.id} value={c.name} />
              ))}
            </datalist>
            <button type="submit" disabled={!target.trim() || busy !== null} aria-busy={busy === "create" || undefined}>
              <SwapLabel on={busy === "create"} idle="Make alias" active="Making alias…" />
            </button>
          </div>
          <p id="alias-target-help" className="muted small">
            Only the website&apos;s name is kept, never the rest of a pasted link.
          </p>
        </form>

        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}

        {!loaded && <p className="muted mt">Loading your aliases…</p>}
        {loaded && mine === 0 && (
          <p className="muted mt">
            You haven&apos;t made an alias yet. The two below are demo aliases with a mock inbox.
          </p>
        )}

        {sorted.length > 0 && (
          <ul className="alias-ledger" aria-label="Aliases">
            {sorted.map((a) => (
              <AliasRow key={a.alias} alias={a} isNew={a.alias === newest} onChange={replace} />
            ))}
          </ul>
        )}

        <div className="row mt">
          <button type="button" className="secondary" onClick={checkInbox} disabled={busy !== null} aria-busy={busy === "inbox" || undefined}>
            <SwapLabel on={busy === "inbox"} idle="Check inbox (mock)" active="Checking…" />
          </button>
          <span className="muted small">Runs on this laptop. Nothing is searched.</span>
        </div>

        <div role="status">
          {hits && hits.length === 0 && (
            <p className="muted mt">No mail from outside the companies you signed up with.</p>
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
                {h.date && <> on {h.date} (date on the message)</>}: &ldquo;{h.subject}&rdquo;
              </p>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

interface RowProps {
  alias: Alias;
  isNew: boolean;
  onChange: (alias: Alias) => void;
}

function AliasRow({ alias: a, isNew, onChange }: RowProps) {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<AliasMessage[] | null>(null);
  const [copied, setCopied] = useState(false);
  const [note, setNote] = useState(a.note);
  const [saving, setSaving] = useState<"status" | "note" | null>(null);
  const [investigation, setInvestigation] = useState<AliasInvestigation | null>(null);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const off = a.status === "disabled";
  const detailId = `alias-${a.alias.replace(/[^a-z0-9]/gi, "-")}`;
  const subject = a.site || a.company;

  // Real elapsed seconds while the local model works. No fake progress.
  useEffect(() => {
    if (startedAt === null) return;
    const timer = setInterval(() => setElapsed(Math.floor((Date.now() - startedAt) / 1000)), 1000);
    return () => clearInterval(timer);
  }, [startedAt]);

  async function loadMessages() {
    try {
      setMessages(await api.aliasMessages(a.alias));
    } catch (err) {
      setError(errorText(err));
    }
  }

  function toggle() {
    const next = !open;
    setOpen(next);
    if (next && messages === null) void loadMessages();
  }

  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), 1600);
    return () => clearTimeout(timer);
  }, [copied]);

  async function copy() {
    try {
      await navigator.clipboard.writeText(a.alias);
      setCopied(true);
    } catch {
      setError("Couldn't copy. Select the address and copy it yourself.");
    }
  }

  async function setStatus() {
    setError(null);
    setSaving("status");
    try {
      onChange(await api.updateAlias(a.alias, { status: off ? "active" : "disabled" }));
      if (messages !== null) void loadMessages(); // blocked labels depend on the date it went off
    } catch (err) {
      setError(errorText(err));
    } finally {
      setSaving(null);
    }
  }

  async function saveNote(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setSaving("note");
    try {
      onChange(await api.updateAlias(a.alias, { note }));
    } catch (err) {
      setError(errorText(err));
    } finally {
      setSaving(null);
    }
  }

  async function investigate() {
    setError(null);
    setInvestigation(null);
    setElapsed(0);
    setStartedAt(Date.now());
    try {
      setInvestigation(await api.investigateAlias(a.alias));
    } catch (err) {
      setError(errorText(err));
    } finally {
      setStartedAt(null);
    }
  }

  const investigating = startedAt !== null;

  return (
    <li className={`alias-row${off ? " off" : ""}${isNew ? " new" : ""}`}>
      <div className="alias-head">
        <code className="alias-address">{a.alias}</code>
        <button type="button" className="quiet copy" onClick={copy} aria-label={`Copy ${a.alias}`}>
          <span className="copy-label" key={String(copied)}>
            {copied ? "Copied" : "Copy"}
          </span>
        </button>
        {a.unexpected_count > 0 && (
          <span className="pill proven" title={TIER_HELP.proven}>
            {TIER_LABEL.proven}: unexpected sender
          </span>
        )}
        {off && <span className="alias-off">Off since {a.disabled_at ?? "unknown"}</span>}
      </div>

      <p className="alias-meta">
        For {subject}
        {a.label && <>, {a.label}</>}. Made {a.created_at} ({aliasMadeSource(a.demo)}).{" "}
        {a.message_count === 0
          ? "No mail yet."
          : `${plural(a.message_count, "message")}${a.unexpected_count > 0 ? `, ${a.unexpected_count} unexpected` : ""}.`}
      </p>

      <button
        type="button"
        className="quiet alias-toggle"
        aria-expanded={open}
        aria-controls={detailId}
        onClick={toggle}
      >
        {open ? "Hide details" : "Show details"}
      </button>
      <span className="sr-only" role="status">
        {copied ? `Copied ${a.alias}` : investigation ? "Investigation finished" : ""}
      </span>

      {open && (
        <div className="alias-detail" id={detailId}>
          {messages === null && !error && <p className="muted small">Loading messages…</p>}
          {messages !== null && messages.length === 0 && (
            <p className="muted small">No mail to this alias in the mock inbox.</p>
          )}
          {messages !== null && messages.length > 0 && (
            <ul className="alias-messages" aria-label={`Mail to ${a.alias} (mock inbox)`}>
              {messages.map((m, i) => (
                <li key={i} className={m.expected ? "" : "unexpected"}>
                  <span className="msg-date">{m.date ?? "unknown"}</span>
                  <strong className="msg-from">{m.from_domain}</strong>
                  <span className="msg-subject">&ldquo;{m.subject}&rdquo;</span>
                  <span className="msg-verdict">
                    {m.expected ? `From ${a.company}` : `Not ${a.company}`}
                    {m.blocked && (
                      <span className="msg-blocked" title={BLOCKED_HELP}>
                        Blocked (mock)
                      </span>
                    )}
                  </span>
                </li>
              ))}
            </ul>
          )}
          <p className="muted small">Dates are the dates on the messages. This is a mock inbox.</p>

          <div className="row alias-actions">
            <button type="button" onClick={investigate} disabled={investigating} aria-busy={investigating || undefined}>
              <SwapLabel on={investigating} idle="Investigate" active={`Reading on this laptop… ${elapsed} s`} />
            </button>
            <button type="button" className="secondary" onClick={setStatus} disabled={saving !== null} aria-busy={saving === "status" || undefined}>
              <SwapLabel on={saving === "status"} idle={off ? "Turn on" : "Turn off"} active="Saving…" />
            </button>
          </div>
          {investigating && (
            <p className="muted small" role="status">
              The local model usually takes under a minute. Nothing leaves this laptop.
            </p>
          )}

          <form className="row alias-note" onSubmit={saveNote}>
            <label htmlFor={`${detailId}-note`} className="small">
              Note
            </label>
            <input
              id={`${detailId}-note`}
              type="text"
              value={note}
              maxLength={280}
              onChange={(e) => setNote(e.target.value)}
              placeholder="Why you turned it off, or what you signed up for"
            />
            <button type="submit" className="secondary" disabled={saving !== null || note === a.note} aria-busy={saving === "note" || undefined}>
              <SwapLabel on={saving === "note"} idle="Save note" active="Saving…" />
            </button>
          </form>

          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}

          {investigation && <InvestigationResult result={investigation} />}
        </div>
      )}
    </li>
  );
}

function InvestigationResult({ result }: { result: AliasInvestigation }) {
  return (
    <section className="alias-investigation" aria-label="Investigation">
      {result.tier && <TierClaim tier={result.tier} company={result.company} />}
      <h4>What the app found</h4>
      <ul className="alias-facts">
        {result.facts.map((fact) => (
          <li key={fact}>{fact}</li>
        ))}
      </ul>
      {result.senders.length > 0 && (
        <ul className="alias-senders" aria-label="Unexpected senders">
          {result.senders.map((s) => (
            <li key={s.domain}>
              <strong>{s.domain}</strong>: {s.name ? `${s.name}. ` : ""}
              {SENDER_KIND_LABEL[s.kind]}.
            </li>
          ))}
        </ul>
      )}
      {result.explanation && (
        <>
          <h4>{ALIAS_CATEGORY_LABEL[result.category]}</h4>
          <p>{result.explanation}</p>
          <p className="muted small">Explained by Gemini. Checked against the facts above.</p>
        </>
      )}
      {result.errors.map((e) => (
        <p key={e} className="notice">
          {e}
        </p>
      ))}
    </section>
  );
}
