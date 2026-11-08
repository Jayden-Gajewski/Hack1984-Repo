"use client";

import { useId, useState, type FormEvent } from "react";
import type { Company, TrackedCompanyInput } from "@/lib/api";
import SwapLabel from "./SwapLabel";

interface Props {
  title: string;
  initial?: TrackedCompanyInput;
  suggestions: Company[];
  submitLabel: string;
  onSubmit: (value: TrackedCompanyInput) => Promise<void>;
  onCancel?: () => void;
  autoFocus?: boolean;
}

// Add or edit a tracked company. Name suggestions come from the local company list, so
// nothing is searched and nothing typed here leaves the laptop.
export default function CompanyForm({ title, initial, suggestions, submitLabel, onSubmit, onCancel, autoFocus }: Props) {
  const id = useId();
  const [name, setName] = useState(initial?.name ?? "");
  const [website, setWebsite] = useState(initial?.website ?? "");
  const [account, setAccount] = useState(initial?.account_label ?? "");
  const [notes, setNotes] = useState(initial?.notes ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function changeName(value: string) {
    setName(value);
    // Picking a company from the list fills in its website while that field is still empty.
    const known = suggestions.find((c) => c.name.toLowerCase() === value.trim().toLowerCase());
    if (known?.domains[0] && !website) setWebsite(known.domains[0]);
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await onSubmit({ name, website, account_label: account, notes, controls: initial?.controls ?? [] });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="fp-form" onSubmit={submit} aria-labelledby={`${id}-title`}>
      <h3 id={`${id}-title`} className="fp-form-title">
        {title}
      </h3>
      <div className="fp-form-row">
        <label>
          Company or service
          <input
            type="text"
            value={name}
            onChange={(e) => changeName(e.target.value)}
            list={`${id}-known`}
            required
            maxLength={120}
            autoComplete="off"
            autoFocus={autoFocus}
          />
        </label>
        <label>
          <span>
            Website <span className="fp-hint">(optional)</span>
          </span>
          <input
            type="text"
            inputMode="url"
            value={website}
            onChange={(e) => setWebsite(e.target.value)}
            maxLength={300}
            placeholder="example.com"
            autoComplete="off"
          />
        </label>
      </div>
      <label>
        <span>
          Account email, username or number <span className="fp-hint">(optional; only used in your drafts)</span>
        </span>
        <input type="text" value={account} onChange={(e) => setAccount(e.target.value)} maxLength={200} autoComplete="off" />
      </label>
      <label>
        <span>
          Notes <span className="fp-hint">(optional)</span>
        </span>
        <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={3} maxLength={4000} />
      </label>
      <datalist id={`${id}-known`}>
        {suggestions.map((c) => (
          <option key={c.id} value={c.name} />
        ))}
      </datalist>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <div className="row">
        <button type="submit" disabled={saving} aria-busy={saving || undefined}>
          <SwapLabel on={saving} idle={submitLabel} active="Saving…" />
        </button>
        {onCancel && (
          <button type="button" className="secondary" onClick={onCancel} disabled={saving}>
            Cancel
          </button>
        )}
      </div>
    </form>
  );
}
