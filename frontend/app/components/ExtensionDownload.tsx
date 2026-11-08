"use client";

import { useEffect, useState, type ReactNode } from "react";
import { api } from "@/lib/api";

// The extension page's download button. During the beta the download is for signed-in accounts:
// the backend serves the zip only with a session (GET /api/extension.zip), and this asks first so
// a signed-out visitor goes to sign-in, then comes back here. The label stays the same either way,
// so nothing jumps when the check returns.
type Session = "checking" | "in" | "out";

export default function ExtensionDownload({ children }: { children?: ReactNode }) {
  const [session, setSession] = useState<Session>("checking");

  useEffect(() => {
    let live = true;
    api.me().then(
      () => live && setSession("in"),
      () => live && setSession("out"),
    );
    return () => {
      live = false;
    };
  }, []);

  const signedIn = session === "in";
  const note = {
    checking: " ",
    in: "For Chrome and Edge. Unzip it, then follow the four steps below.",
    out: "You'll sign in first. Your account stays on this computer.",
  }[session];

  return (
    <div className="ext-get">
      <div className="hero-ctas">
        <a
          className="btn btn-primary btn-lg"
          href={signedIn ? "/api/extension.zip" : "/login?next=/extension"}
          download={signedIn ? "dossier-privacy-check.zip" : undefined}
          aria-busy={session === "checking"}
        >
          <DownloadIcon /> Download the extension
        </a>
        {children}
      </div>
      <p className="ext-get-note" aria-live="polite">
        {note}
      </p>
    </div>
  );
}

// A browser address with a copy button. Pages can't link to chrome:// addresses, so people paste it.
export function CopyText({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), 1600);
    return () => clearTimeout(timer);
  }, [copied]);

  return (
    <span className="ext-copy">
      <code>{text}</code>
      <button
        type="button"
        className="ext-copy-btn"
        aria-label={copied ? `Copied ${text}` : `Copy ${text}`}
        onClick={() => navigator.clipboard?.writeText(text).then(() => setCopied(true), () => {})}
      >
        <span data-on={!copied} aria-hidden>
          Copy
        </span>
        <span data-on={copied} aria-hidden>
          Copied
        </span>
      </button>
    </span>
  );
}

function DownloadIcon() {
  return (
    <svg className="icon" width="16" height="16" viewBox="0 0 16 16" aria-hidden>
      <path d="M8 2.5v8M4.5 7.5 8 11l3.5-3.5M3 13.5h10" />
    </svg>
  );
}
