"use client";

import { useRef, useState } from "react";
import { api, type MonitorConfig, type MonitoredEmail } from "@/lib/api";
import { localTime, timeAgo } from "@/lib/display";

interface Props {
  emails: MonitoredEmail[];
  config: MonitorConfig;
  onChanged: () => Promise<void>;
}

const message = (err: unknown) => (err instanceof Error ? err.message : String(err));

function checkText(e: MonitoredEmail): string {
  if (!e.verified) return "Not checked until it's verified.";
  if (e.check_status === "ok") {
    return `Checked ${timeAgo(e.last_checked)}. ${e.check_message}`;
  }
  if (e.check_status === "never") return "Verified. Refresh to check it with Have I Been Pwned.";
  const earlier = e.last_checked ? ` Last successful check ${timeAgo(e.last_checked)}.` : "";
  return `${e.check_message}${earlier}`;
}

// Addresses you've proven you own. Have I Been Pwned only ever gets the first 6 characters of an
// address's SHA-1 hash; after verification, only the hash and a masked address stay on this laptop.
export default function MonitoredEmails({ emails, config, onChanged }: Props) {
  const [address, setAddress] = useState("");
  const [codes, setCodes] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const codeInputs = useRef<Record<string, HTMLInputElement | null>>({});

  async function run(key: string, work: () => Promise<unknown>, done?: string) {
    setBusy(key);
    setError(null);
    setNote(null);
    try {
      await work();
      await onChanged();
      if (done) setNote(done);
    } catch (err) {
      setError(message(err));
    } finally {
      setBusy(null);
    }
  }

  async function add(e: React.FormEvent) {
    e.preventDefault();
    let added: MonitoredEmail | null = null;
    await run(
      "add",
      async () => {
        added = await api.monitor.addEmail(address);
      },
      config.smtp ? "Code sent. Check that inbox (and spam), then enter it below." : undefined,
    );
    if (added) {
      setAddress("");
      const id = (added as MonitoredEmail).id;
      requestAnimationFrame(() => codeInputs.current[id]?.focus());
    }
  }

  return (
    <section className="section" aria-labelledby="emails-h">
      <div className="task-panel">
        <h2 id="emails-h">Your email addresses</h2>
        <p className="muted">
          Only addresses you prove you own are checked. Have I Been Pwned gets the first 6 characters of the
          address&apos;s SHA-1 hash, never the address. After verification, only its SHA-1 hash (needed for checks,
          but not anonymous: anyone who guesses the address can match it) and a masked address are kept on this laptop.
          An address that&apos;s never verified is deleted after a day.
        </p>
        {!config.smtp && (
          <p className="notice">
            <strong>Verification isn&apos;t set up.</strong> Add an SMTP server to .env (SMTP_HOST, SMTP_PORT,
            SMTP_USERNAME, SMTP_PASSWORD, SMTP_FROM) to email yourself a code. Until then, addresses can be added but
            not verified or checked.
          </p>
        )}
        {!config.hibp_email_key && (
          <p className="notice">
            <strong>Email checks aren&apos;t set up.</strong> They need a Have I Been Pwned Pro key (HIBP_API_KEY in
            .env); the hashed search isn&apos;t on cheaper plans. Without it, verified addresses show as not checked,
            never as safe.
          </p>
        )}
        <form className="email-form" onSubmit={add}>
          <label>
            Email address
            <input
              type="email"
              value={address}
              onChange={(e) => setAddress(e.target.value)}
              required
              autoComplete="email"
              placeholder="you@example.com"
            />
          </label>
          <button type="submit" disabled={busy === "add" || !address.trim()}>
            {busy === "add" ? "Adding…" : config.smtp ? "Add and send code" : "Add"}
          </button>
        </form>
        <div aria-live="polite">
          {note && <p className="muted small mt">{note}</p>}
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
        </div>
      </div>

      {emails.length > 0 && (
        <ul className="watch-list" aria-label="Monitored emails">
          {emails.map((e) => {
            const codeSent = !e.verified && e.code_sent_at;
            return (
              <li key={e.id}>
                <div className="watch-main">
                  <strong>{e.display}</strong>{" "}
                  <span className={`state ${e.verified ? "ok" : codeSent ? "wait" : "off"}`}>
                    {e.verified ? "Verified" : codeSent ? "Code sent" : "Not verified"}
                  </span>
                  <p className="muted small" title={e.last_checked ? localTime(e.last_checked) : undefined}>
                    {checkText(e)}
                  </p>
                  {!e.verified && (
                    <form
                      className="code-form"
                      onSubmit={(ev) => {
                        ev.preventDefault();
                        run(`verify-${e.id}`, () => api.monitor.verifyEmail(e.id, codes[e.id] ?? ""), "Verified. Refresh to check it.");
                      }}
                    >
                      <label>
                        6-digit code
                        <input
                          ref={(el) => {
                            codeInputs.current[e.id] = el;
                          }}
                          type="text"
                          className="code-input"
                          inputMode="numeric"
                          autoComplete="one-time-code"
                          pattern="[0-9]{6}"
                          maxLength={6}
                          value={codes[e.id] ?? ""}
                          onChange={(ev) => setCodes((prev) => ({ ...prev, [e.id]: ev.target.value.replace(/\D/g, "") }))}
                          disabled={!config.smtp}
                        />
                      </label>
                      <button
                        type="submit"
                        className="secondary"
                        disabled={!config.smtp || (codes[e.id] ?? "").length !== 6 || busy === `verify-${e.id}`}
                      >
                        {busy === `verify-${e.id}` ? "Checking…" : "Verify"}
                      </button>
                      <button
                        type="button"
                        className="quiet"
                        disabled={!config.smtp || busy === `code-${e.id}`}
                        onClick={() => run(`code-${e.id}`, () => api.monitor.sendCode(e.id), "New code sent.")}
                      >
                        {codeSent ? "Send a new code" : "Send code"}
                      </button>
                    </form>
                  )}
                </div>
                <div className="watch-actions">
                  <button
                    type="button"
                    className="quiet"
                    onClick={() => run(`remove-${e.id}`, () => api.monitor.removeEmail(e.id))}
                    disabled={busy === `remove-${e.id}`}
                  >
                    Remove
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
