"use client";

import { useEffect, useRef, useState } from "react";
import type { Draft } from "@/lib/api";
import { exposureKind, safeHref, safeMailto } from "@/lib/display";

interface Props {
  draft: Draft | null;
  loading: boolean;
  error: string | null;
  onClose: () => void;
}

// Shows one opt-out or privacy request (Stage 6): where to send it, the subject and the body.
export default function DraftModal({ draft, loading, error, onClose }: Props) {
  const [copy, setCopy] = useState<"idle" | "copied" | "failed">("idle");
  const dialog = useRef<HTMLDivElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);

  // Move focus in, keep Tab inside the dialog, and give focus back to the opener on close.
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    closeButton.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key !== "Tab" || !dialog.current) return;
      const focusable = dialog.current.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])',
      );
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last?.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      opener?.focus();
    };
  }, [onClose]);

  useEffect(() => {
    if (copy === "idle") return;
    const t = setTimeout(() => setCopy("idle"), 2000);
    return () => clearTimeout(t);
  }, [copy]);

  async function copyRequest() {
    if (!draft) return;
    try {
      await navigator.clipboard.writeText(`Subject: ${draft.subject}\n\n${draft.body}`);
      setCopy("copied");
    } catch {
      setCopy("failed");
    }
  }

  const pageHref = safeHref(draft?.send_to_url);
  const mailHref = safeMailto(draft?.send_to_email);
  const title = draft ? `Request to ${draft.recipient}` : "Drafting request";

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div
        ref={dialog}
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="draft-h"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="card-head">
          <h2 id="draft-h">{title}</h2>
          <button ref={closeButton} type="button" className="quiet" onClick={onClose}>
            Close
          </button>
        </div>
        <div role="status">{loading && <p className="muted mt">Finding where to send it…</p>}</div>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        {draft && (
          <>
            <p className="row mt">
              <strong>Send to:</strong>
              {mailHref && <a href={mailHref}>{draft.send_to_email}</a>}
              {pageHref && (
                <a href={pageHref} target="_blank" rel="noopener noreferrer">
                  {draft.kind === "company" ? "Privacy page" : exposureKind(draft.kind).page}
                </a>
              )}
              {!mailHref && !pageHref && <span className="muted">Not found. Use the listing or the company site.</span>}
            </p>
            {draft.errors.map((err, i) => (
              <p key={i} className="notice">
                <strong>Note:</strong> {err}
              </p>
            ))}
            <p className="mt">
              <strong>Subject:</strong> {draft.subject}
            </p>
            <pre className="letter">{draft.body}</pre>
            <div className="row">
              <button type="button" onClick={copyRequest}>
                {copy === "copied" ? "Copied" : "Copy request"}
              </button>
              <span className="muted small" role="status">
                {copy === "failed" && "Couldn't reach the clipboard. Select the text above and copy it."}
              </span>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
