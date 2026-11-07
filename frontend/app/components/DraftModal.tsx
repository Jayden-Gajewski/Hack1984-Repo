"use client";

import { useEffect, useState } from "react";
import type { Draft } from "@/lib/api";
import { safeHref, safeMailto } from "@/lib/display";

interface Props {
  draft: Draft | null;
  loading: boolean;
  error: string | null;
  onClose: () => void;
}

// Shows one opt-out or privacy request (Stage 6): where to send it, the subject and the body.
export default function DraftModal({ draft, loading, error, onClose }: Props) {
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  async function copy() {
    if (!draft) return;
    try {
      await navigator.clipboard.writeText(`Subject: ${draft.subject}\n\n${draft.body}`);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  const pageHref = safeHref(draft?.send_to_url);
  const mailHref = safeMailto(draft?.send_to_email);

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal panel" role="dialog" aria-modal="true" aria-label="Draft request" onClick={(e) => e.stopPropagation()}>
        <div className="card-head">
          <h2>{draft ? `Request to ${draft.recipient}` : "Drafting…"}</h2>
          <button type="button" className="secondary" onClick={onClose}>
            Close
          </button>
        </div>
        {loading && <p className="muted">Finding where to send it…</p>}
        {error && <p className="error">{error}</p>}
        {draft && (
          <>
            <p className="row">
              <strong>Send to:</strong>
              {mailHref && <a href={mailHref}>{draft.send_to_email}</a>}
              {pageHref && (
                <a href={pageHref} target="_blank" rel="noopener noreferrer">
                  {draft.kind === "broker" ? "Opt-out page" : "Privacy page"}
                </a>
              )}
              {!mailHref && !pageHref && <span className="muted">not found; use the listing or company site</span>}
            </p>
            {draft.errors.map((err, i) => (
              <p key={i} className="muted">
                {err}
              </p>
            ))}
            <p>
              <strong>Subject:</strong> {draft.subject}
            </p>
            <pre className="letter">{draft.body}</pre>
            <button type="button" onClick={copy}>
              {copied ? "Copied" : "Copy request"}
            </button>
          </>
        )}
      </div>
    </div>
  );
}
