"use client";

import { useEffect, useState, type FormEvent } from "react";
import { api, type DataRequest, type RequestStatus, type TrackedCompany } from "@/lib/api";
import {
  REQUEST_KIND_LABEL,
  REQUEST_STATUS_LABEL,
  UNSENT_STATUSES,
  formatDay,
  formatSavedDay,
  localDayISO,
  todayISO,
} from "@/lib/display";

const message = (err: unknown) => (err instanceof Error ? err.message : String(err));

// Unsent requests wear a dashed outline; sent ones are solid (footprint.css).
export function StatusPill({ status }: { status: RequestStatus }) {
  return <span className={`fp-status fp-status-${status}`}>{REQUEST_STATUS_LABEL[status]}</span>;
}

interface Props {
  request: DataRequest;
  onSaved: (company: TrackedCompany) => void;
}

// One data request: where it stands, what happened when, its text, and a form to record the
// next step. Dossier never sends it; the user sends it and records what happened.
export default function FootprintRequest({ request, onSaved }: Props) {
  const unsent = UNSENT_STATUSES.has(request.status);
  const sentStep = request.history.findLast((step) => step.status === "sent");
  const lastDay = request.history.at(-1)?.happened_on;
  const firstNext = request.next_statuses[0] ?? request.status;

  const [status, setStatus] = useState<RequestStatus>(firstNext);
  const [day, setDay] = useState(todayISO);
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [copy, setCopy] = useState<"idle" | "copied" | "failed">("idle");
  const [confirmRemove, setConfirmRemove] = useState(false);
  const [announce, setAnnounce] = useState(""); // read out after a save; the pill and history show it

  // After a step is saved the request offers new next steps; start the form on the first one.
  useEffect(() => setStatus(firstNext), [request.status, firstNext]);

  useEffect(() => {
    if (copy === "idle") return;
    const t = setTimeout(() => setCopy("idle"), 2000);
    return () => clearTimeout(t);
  }, [copy]);

  async function run(action: () => Promise<TrackedCompany>): Promise<boolean> {
    setSaving(true);
    setError(null);
    try {
      onSaved(await action());
      return true;
    } catch (err) {
      setError(message(err));
      return false;
    } finally {
      setSaving(false);
    }
  }

  async function record(e: FormEvent) {
    e.preventDefault();
    const saved = `Saved: ${status === request.status ? "note" : REQUEST_STATUS_LABEL[status]}, ${formatDay(day)}.`;
    if (await run(() => api.recordRequestUpdate(request.id, { status, happened_on: day, note }))) {
      setAnnounce(saved);
      setNote("");
      setDay(todayISO());
    }
  }

  function startEditing() {
    setSubject(request.subject);
    setBody(request.body);
    setEditing(true);
  }

  async function saveText(e: FormEvent) {
    e.preventDefault();
    if (await run(() => api.editDataRequest(request.id, { subject, body }))) setEditing(false);
  }

  async function copyText() {
    try {
      await navigator.clipboard.writeText(`Subject: ${request.subject}\n\n${request.body}`);
      setCopy("copied");
    } catch {
      setCopy("failed");
    }
  }

  const heading = `fp-request-${request.id}`;
  const justNote = status === request.status;

  // The user's steps are in date order. The day the request was added to Dossier slots in among
  // them (before any step on the same day), so a request sent before it was tracked reads right.
  const added = localDayISO(request.created_at);
  const addedAt = request.history.findIndex((step) => step.happened_on >= added);
  const split = addedAt === -1 ? request.history.length : addedAt;
  const stepItem = (step: DataRequest["history"][number], i: number) => {
    const previous = i === 0 ? "draft" : request.history[i - 1].status;
    return (
      <li key={`${step.recorded_at}-${i}`}>
        <div className="fp-step-head">
          <strong>{step.status === previous ? "Note" : REQUEST_STATUS_LABEL[step.status]}</strong>
          <span className="fp-step-date">{formatDay(step.happened_on)} (you recorded)</span>
          {i === request.history.length - 1 && (
            <button
              type="button"
              className="quiet fp-undo"
              aria-label="Undo this step"
              onClick={() => run(() => api.undoRequestUpdate(request.id))}
              disabled={saving}
            >
              Undo
            </button>
          )}
        </div>
        {step.note && <p className="fp-step-note">{step.note}</p>}
      </li>
    );
  };

  return (
    <article className="card fp-request" aria-labelledby={heading}>
      <div className="card-head">
        <h4 id={heading} className="fp-request-title">
          {REQUEST_KIND_LABEL[request.kind]}
        </h4>
        <StatusPill status={request.status} />
      </div>
      <p className={`fp-request-state${unsent ? " unsent" : ""}`}>
        {unsent ? (
          "Not sent. Dossier doesn't send requests: copy the text, send it yourself, then record that you sent it."
        ) : sentStep ? (
          <>
            Sent {formatDay(sentStep.happened_on)} <span className="muted">(you recorded)</span>
          </>
        ) : (
          "Never marked sent."
        )}
      </p>

      <ol className="timeline fp-steps" aria-label="History">
        {request.history.slice(0, split).map((step, i) => stepItem(step, i))}
        <li key="added">
          <div className="fp-step-head">
            <strong>Added to Dossier</strong>
            <span className="fp-step-date">{formatSavedDay(request.created_at)} (saved)</span>
          </div>
        </li>
        {request.history.slice(split).map((step, i) => stepItem(step, split + i))}
      </ol>
      <span className="sr-only" role="status">
        {announce}
      </span>

      <details className="detail" open={unsent}>
        <summary>Request text</summary>
        {editing ? (
          <form className="fp-text-edit" onSubmit={saveText}>
            <label>
              Subject
              <input type="text" value={subject} onChange={(e) => setSubject(e.target.value)} required maxLength={200} />
            </label>
            <label>
              Message
              <textarea value={body} onChange={(e) => setBody(e.target.value)} required rows={12} maxLength={20000} />
            </label>
            <div className="row">
              <button type="submit" disabled={saving}>
                {saving ? "Saving…" : "Save text"}
              </button>
              <button type="button" className="secondary" onClick={() => setEditing(false)} disabled={saving}>
                Cancel
              </button>
            </div>
          </form>
        ) : (
          <>
            <p className="fp-subject">
              <strong>Subject:</strong> {request.subject}
            </p>
            <pre className="letter">{request.body}</pre>
            <div className="row">
              <button type="button" className="secondary" onClick={copyText}>
                {copy === "copied" ? "Copied" : "Copy request"}
              </button>
              {request.editable && (
                <button type="button" className="quiet" onClick={startEditing}>
                  Edit text
                </button>
              )}
              <span className="muted small" role="status">
                {copy === "failed" && "Couldn't reach the clipboard. Select the text above and copy it."}
              </span>
            </div>
            {!request.editable && (
              <p className="muted small mt">
                {sentStep
                  ? "This is the text you marked as sent, so it can't be edited."
                  : "Record this request as a draft again to edit its text."}
              </p>
            )}
          </>
        )}
      </details>

      <form className="fp-update" onSubmit={record}>
        <p className="fp-wide fp-update-title">Record an update</p>
        <label>
          What happened
          <select value={status} onChange={(e) => setStatus(e.target.value as RequestStatus)}>
            {request.next_statuses.map((s) => (
              <option key={s} value={s}>
                {REQUEST_STATUS_LABEL[s]}
              </option>
            ))}
            <option value={request.status}>No change, just a note</option>
          </select>
        </label>
        <label>
          Date
          <input type="date" value={day} min={lastDay} max={todayISO()} onChange={(e) => setDay(e.target.value)} required />
        </label>
        <label className="fp-wide">
          <span>
            Note <span className="fp-hint">{justNote ? "(needed for a note)" : "(optional)"}</span>
          </span>
          <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2} maxLength={2000} required={justNote} />
        </label>
        <div className="fp-wide row">
          <button type="submit" disabled={saving}>
            {saving ? "Saving…" : "Save update"}
          </button>
          {status === "sent" && <span className="muted small">Only mark it sent once you&apos;ve sent it yourself.</span>}
        </div>
      </form>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      <div className="fp-remove">
        {confirmRemove ? (
          <span className="fp-confirm">
            Remove this request and its history?
            <button
              type="button"
              className="secondary fp-danger"
              onClick={() => run(() => api.removeDataRequest(request.id))}
              disabled={saving}
            >
              Remove request
            </button>
            <button type="button" className="quiet" onClick={() => setConfirmRemove(false)} autoFocus>
              Keep it
            </button>
          </span>
        ) : (
          <button type="button" className="quiet" onClick={() => setConfirmRemove(true)}>
            Remove request
          </button>
        )}
      </div>
    </article>
  );
}
