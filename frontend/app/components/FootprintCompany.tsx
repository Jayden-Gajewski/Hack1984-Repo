"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  api,
  type Company,
  type ControlState,
  type LawBasis,
  type PrivacyControl,
  type RequestKind,
  type TrackedCompany,
  type TrackedCompanyInput,
} from "@/lib/api";
import {
  CONTROL_STATE_LABEL,
  LAW_LABEL,
  formatDay,
  formatSavedDay,
  safeHref,
  todayISO,
  websiteHost,
} from "@/lib/display";
import CompanyForm from "./FootprintCompanyForm";
import FootprintRequest from "./FootprintRequest";
import { Chevron } from "./icons";
import SwapLabel from "./SwapLabel";

const message = (err: unknown) => (err instanceof Error ? err.message : String(err));

const asInput = (company: TrackedCompany, patch: Partial<TrackedCompanyInput> = {}): TrackedCompanyInput => ({
  name: company.name,
  website: company.website,
  account_label: company.account_label,
  notes: company.notes,
  controls: company.controls,
  ...patch,
});

interface Props {
  company: TrackedCompany;
  suggestions: Company[];
  onSaved: (company: TrackedCompany) => void;
  onRemoved: (id: string) => void;
  onBack: () => void;
}

// One tracked company: its details, its data requests and the privacy settings the user checked.
export default function FootprintCompany({ company, suggestions, onSaved, onRemoved, onBack }: Props) {
  const heading = useRef<HTMLHeadingElement>(null);
  const [editing, setEditing] = useState(false);
  const [law, setLaw] = useState<LawBasis>("none");
  const [drafting, setDrafting] = useState<RequestKind | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmRemove, setConfirmRemove] = useState(false);
  const [removing, setRemoving] = useState(false);

  // Opening a company moves focus to its name, so keyboard and screen reader users land here.
  useEffect(() => {
    if (!editing) heading.current?.focus();
  }, [company.id, editing]);

  async function draft(kind: RequestKind) {
    setDrafting(kind);
    setError(null);
    try {
      onSaved(await api.draftDataRequest(company.id, { kind, law }));
    } catch (err) {
      setError(message(err));
    } finally {
      setDrafting(null);
    }
  }

  async function remove() {
    setRemoving(true);
    setError(null);
    try {
      await api.removeTrackedCompany(company.id);
      onRemoved(company.id);
    } catch (err) {
      setError(message(err));
      setRemoving(false);
    }
  }

  const href = safeHref(company.website);

  return (
    <div className="fp-detail">
      <button type="button" className="quiet fp-back" onClick={onBack}>
        <Chevron direction="left" /> All companies
      </button>

      {editing ? (
        <CompanyForm
          title={`Edit ${company.name}`}
          initial={company}
          suggestions={suggestions}
          submitLabel="Save changes"
          autoFocus
          onSubmit={async (value) => {
            onSaved(await api.editTrackedCompany(company.id, value));
            setEditing(false);
          }}
          onCancel={() => setEditing(false)}
        />
      ) : (
        <>
          <div className="card-head">
            <h3 ref={heading} tabIndex={-1} className="fp-company-name">
              {company.name}
            </h3>
            <div className="row">
              <button type="button" className="secondary" onClick={() => setEditing(true)}>
                Edit
              </button>
              {confirmRemove ? (
                <span className="fp-confirm">
                  Remove {company.name} and all its requests?
                  <button type="button" className="secondary fp-danger" onClick={remove} disabled={removing} aria-busy={removing || undefined}>
                    <SwapLabel on={removing} idle="Remove company" active="Removing…" />
                  </button>
                  <button type="button" className="quiet" onClick={() => setConfirmRemove(false)} autoFocus>
                    Keep it
                  </button>
                </span>
              ) : (
                <button type="button" className="quiet" onClick={() => setConfirmRemove(true)}>
                  Remove
                </button>
              )}
            </div>
          </div>
          <dl className="fp-facts">
            <div>
              <dt>Website</dt>
              <dd>
                {href ? (
                  <a href={href} target="_blank" rel="noopener noreferrer">
                    {websiteHost(company.website)}
                  </a>
                ) : (
                  <span className="muted">Not recorded</span>
                )}
              </dd>
            </div>
            <div>
              <dt>Account</dt>
              <dd>{company.account_label || <span className="muted">Not recorded</span>}</dd>
            </div>
            <div>
              <dt>Notes</dt>
              <dd>{company.notes || <span className="muted">None</span>}</dd>
            </div>
            <div>
              <dt>Added</dt>
              <dd>
                {formatSavedDay(company.created_at)} <span className="muted">(saved)</span>
              </dd>
            </div>
          </dl>
        </>
      )}

      <section className="fp-block" aria-labelledby={`fp-requests-${company.id}`}>
        <h4 id={`fp-requests-${company.id}`}>Requests</h4>
        <p className="muted small">
          Draft a request here, send it yourself by email or through the company&apos;s privacy form, then
          record each step. Drafts are saved in your account and never sent by Dossier.
        </p>
        <div className="fp-draft">
          <label>
            Name a privacy law in the draft
            <select value={law} onChange={(e) => setLaw(e.target.value as LawBasis)}>
              {(Object.keys(LAW_LABEL) as LawBasis[]).map((k) => (
                <option key={k} value={k}>
                  {LAW_LABEL[k]}
                </option>
              ))}
            </select>
          </label>
          <button type="button" onClick={() => draft("access")} disabled={drafting !== null} aria-busy={drafting === "access" || undefined}>
            <SwapLabel on={drafting === "access"} idle="Draft a request for my data" active="Drafting…" />
          </button>
          <button type="button" className="secondary" onClick={() => draft("deletion")} disabled={drafting !== null} aria-busy={drafting === "deletion" || undefined}>
            <SwapLabel on={drafting === "deletion"} idle="Draft a deletion request" active="Drafting…" />
          </button>
        </div>
        <p className="muted small mt">
          Dossier can&apos;t tell which privacy laws cover you, and its drafts aren&apos;t legal advice.
        </p>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        {company.requests.length === 0 ? (
          <p className="muted fp-none">No requests yet.</p>
        ) : (
          <div className="cards">
            {company.requests.map((r) => (
              <FootprintRequest key={r.id} request={r} onSaved={onSaved} />
            ))}
          </div>
        )}
      </section>

      <PrivacySettings company={company} onSaved={onSaved} />
    </div>
  );
}

const BLANK = { name: "", state: "unknown" as ControlState, checked_on: "", note: "" };

// Settings the user checked on the company's own site. Dossier only records what they saw.
function PrivacySettings({ company, onSaved }: { company: TrackedCompany; onSaved: (c: TrackedCompany) => void }) {
  const [form, setForm] = useState(BLANK);
  const [editingIndex, setEditingIndex] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save(controls: PrivacyControl[]): Promise<boolean> {
    setSaving(true);
    setError(null);
    try {
      onSaved(await api.editTrackedCompany(company.id, asInput(company, { controls })));
      return true;
    } catch (err) {
      setError(message(err));
      return false;
    } finally {
      setSaving(false);
    }
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    const control: PrivacyControl = { ...form, checked_on: form.checked_on || null };
    const next =
      editingIndex === null
        ? [...company.controls, control]
        : company.controls.map((c, i) => (i === editingIndex ? control : c));
    if (await save(next)) cancel();
  }

  function edit(index: number) {
    const c = company.controls[index];
    setForm({ name: c.name, state: c.state, checked_on: c.checked_on ?? "", note: c.note });
    setEditingIndex(index);
  }

  function cancel() {
    setForm(BLANK);
    setEditingIndex(null);
  }

  async function remove(index: number) {
    if (await save(company.controls.filter((_, i) => i !== index)) && editingIndex === index) cancel();
  }

  return (
    <section className="fp-block" aria-labelledby={`fp-controls-${company.id}`}>
      <h4 id={`fp-controls-${company.id}`}>Privacy settings you checked</h4>
      <p className="muted small">
        Record settings you checked on {company.name}&apos;s own site, like ad personalization or &ldquo;Sell or
        share my personal information&rdquo;. Dossier can&apos;t see or change them; this is your record.
      </p>
      {company.controls.length > 0 && (
        <ul className="fp-controls">
          {company.controls.map((c, i) => (
            <li key={`${c.name}-${i}`}>
              <div className="fp-control-head">
                <strong>{c.name}</strong>
                <span className="chip">{CONTROL_STATE_LABEL[c.state]}</span>
                <span className="muted small">
                  {c.checked_on ? `Checked ${formatDay(c.checked_on)} (you recorded)` : "Date checked: unknown"}
                </span>
              </div>
              {c.note && <p className="fp-step-note">{c.note}</p>}
              <div className="row">
                <button type="button" className="quiet" onClick={() => edit(i)} disabled={saving}>
                  Edit
                </button>
                <button type="button" className="quiet" onClick={() => remove(i)} disabled={saving}>
                  Remove
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
      <form className="fp-control-form" onSubmit={submit}>
        <label className="fp-wide">
          Setting
          <input
            type="text"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            required
            maxLength={120}
            placeholder="Sell or share my personal information"
          />
        </label>
        <label>
          State
          <select value={form.state} onChange={(e) => setForm({ ...form, state: e.target.value as ControlState })}>
            {(Object.keys(CONTROL_STATE_LABEL) as ControlState[]).map((s) => (
              <option key={s} value={s}>
                {CONTROL_STATE_LABEL[s]}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>
            Date checked <span className="fp-hint">(optional)</span>
          </span>
          <input
            type="date"
            value={form.checked_on}
            max={todayISO()}
            onChange={(e) => setForm({ ...form, checked_on: e.target.value })}
          />
        </label>
        <label className="fp-wide">
          <span>
            Note <span className="fp-hint">(optional)</span>
          </span>
          <input type="text" value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} maxLength={500} />
        </label>
        <div className="fp-wide row">
          <button type="submit" className="secondary" disabled={saving} aria-busy={saving || undefined}>
            <SwapLabel on={saving} idle={editingIndex === null ? "Record setting" : "Save setting"} active="Saving…" />
          </button>
          {editingIndex !== null && (
            <button type="button" className="quiet" onClick={cancel} disabled={saving}>
              Cancel
            </button>
          )}
        </div>
      </form>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}
