"use client";

import { useState } from "react";
import { api, type User } from "@/lib/api";

interface Props {
  onLoggedIn: (user: User) => void;
}

type Mode = "login" | "signup" | "reset";

const TITLE: Record<Mode, string> = {
  login: "Log in",
  signup: "Create an account",
  reset: "Reset your password",
};

// Log in, create an account, or reset a forgotten password with a code from an admin.
// A username, not an email: the app collects as little as it can. Accounts live in the
// local Postgres on this laptop, like everything else.
export default function AuthForm({ onLoggedIn }: Props) {
  const [mode, setMode] = useState<Mode>("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function switchTo(next: Mode) {
    setMode(next);
    setError(null);
    setPassword("");
    setCode("");
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      if (mode === "reset") {
        onLoggedIn(await api.resetPassword({ username, code, new_password: password }));
      } else {
        const creds = { username, password };
        onLoggedIn(await (mode === "login" ? api.login(creds) : api.signup(creds)));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  }

  const newPassword = mode !== "login";
  const submitLabel = { login: "Log in", signup: "Create account", reset: "Set new password" }[mode];

  return (
    <form onSubmit={submit} className="panel">
      <h2>{TITLE[mode]}</h2>
      {mode === "reset" && (
        <p className="muted">
          Ask an admin for a reset code. It works once and expires after 30 minutes.
        </p>
      )}
      <label>
        Username
        <input
          type="text"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          autoComplete="username"
          required
          minLength={3}
          maxLength={32}
        />
      </label>
      {mode === "reset" && (
        <label>
          Reset code
          <input
            type="text"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            autoComplete="one-time-code"
            placeholder="ABCD-EFGH-JKMN"
            required
            minLength={4}
            maxLength={32}
          />
        </label>
      )}
      <label>
        {mode === "reset" ? "New password" : "Password"}
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete={newPassword ? "new-password" : "current-password"}
          required
          minLength={8}
          maxLength={128}
        />
      </label>
      <button type="submit" disabled={loading}>
        {loading ? "One moment…" : submitLabel}
      </button>
      {error && <p className="error">{error}</p>}
      <p className="row">
        {mode !== "login" && (
          <button type="button" className="secondary" onClick={() => switchTo("login")}>
            Back to log in
          </button>
        )}
        {mode === "login" && (
          <>
            <button type="button" className="secondary" onClick={() => switchTo("signup")}>
              Create an account
            </button>
            <button type="button" className="secondary" onClick={() => switchTo("reset")}>
              Forgot password?
            </button>
          </>
        )}
      </p>
      {mode === "signup" && (
        <p className="muted">
          No email needed. Your account is stored only in the database on this laptop. The first account
          created becomes the admin.
        </p>
      )}
    </form>
  );
}
