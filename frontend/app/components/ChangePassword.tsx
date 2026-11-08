"use client";

import { useState, type FormEvent } from "react";
import { api } from "@/lib/api";

// The signed-in user changes their own password. The backend ends their other sessions; this one
// stays signed in.
export default function ChangePassword() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const formEl = e.currentTarget;
    const form = new FormData(formEl);
    const current = String(form.get("current") ?? "");
    const next = String(form.get("next") ?? "");
    if (next !== String(form.get("confirm") ?? "")) {
      setError("The new passwords don't match.");
      return;
    }
    setBusy(true);
    setError(null);
    setDone(false);
    try {
      await api.changePassword({ current_password: current, new_password: next });
      formEl.reset();
      setDone(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="section" aria-labelledby="password-h">
      <h2 id="password-h">Change password</h2>
      <p className="muted">Your other signed-in browsers are logged out. This one stays signed in.</p>
      {/* method="post": a submit before React loads must never put a password in the URL. */}
      <form className="account-form" method="post" onSubmit={onSubmit}>
        <label>
          Current password
          <input name="current" type="password" autoComplete="current-password" required maxLength={256} />
        </label>
        <label>
          New password
          <input name="next" type="password" autoComplete="new-password" required minLength={8} maxLength={256} />
        </label>
        <label>
          New password again
          <input name="confirm" type="password" autoComplete="new-password" required minLength={8} maxLength={256} />
        </label>
        <button type="submit" disabled={busy}>
          {busy ? "Saving…" : "Change password"}
        </button>
      </form>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {done && (
        <p className="notice" role="status">
          Password changed. Your other sessions were logged out.
        </p>
      )}
    </section>
  );
}
