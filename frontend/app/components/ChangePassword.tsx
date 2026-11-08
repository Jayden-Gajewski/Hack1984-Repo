"use client";

import { useState } from "react";
import { api } from "@/lib/api";

// A logged-in user changes their own password. The backend logs out their other sessions;
// this one stays logged in.
export default function ChangePassword() {
  const [open, setOpen] = useState(false);
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  function close() {
    setOpen(false);
    setCurrent("");
    setNext("");
    setConfirm("");
    setError(null);
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (next !== confirm) {
      setError("The new passwords don't match.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      await api.changePassword(current, next);
      close();
      setDone(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't change your password");
    } finally {
      setLoading(false);
    }
  }

  if (!open) {
    return (
      <>
        <button
          type="button"
          className="secondary"
          onClick={() => {
            setOpen(true);
            setDone(false);
          }}
        >
          Change password
        </button>
        {done && <span className="muted">Password changed. Your other logins were logged out.</span>}
      </>
    );
  }

  return (
    <form onSubmit={submit} className="panel">
      <h2>Change password</h2>
      <label>
        Current password
        <input
          type="password"
          value={current}
          onChange={(e) => setCurrent(e.target.value)}
          autoComplete="current-password"
          required
        />
      </label>
      <label>
        New password
        <input
          type="password"
          value={next}
          onChange={(e) => setNext(e.target.value)}
          autoComplete="new-password"
          required
          minLength={8}
          maxLength={128}
        />
      </label>
      <label>
        New password again
        <input
          type="password"
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          autoComplete="new-password"
          required
          minLength={8}
          maxLength={128}
        />
      </label>
      {error && <p className="error">{error}</p>}
      <p className="row">
        <button type="submit" disabled={loading}>
          {loading ? "Saving…" : "Change password"}
        </button>
        <button type="button" className="secondary" onClick={close}>
          Cancel
        </button>
      </p>
    </form>
  );
}
