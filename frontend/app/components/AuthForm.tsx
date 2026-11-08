"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { api } from "@/lib/api";
import Logo from "./Logo";
import { Lock } from "./icons";
import SwapLabel from "./SwapLabel";

type Mode = "login" | "signup" | "reset";

const COPY = {
  login: {
    title: "Log in to Dossier",
    sub: "Pick up where your last scan left off.",
    submit: "Log in",
    busy: "Logging in…",
    switchText: "New to Dossier?",
    switchLink: "Create an account",
    switchHref: "/signup",
  },
  signup: {
    title: "Create your account",
    sub: "Find where your personal data is exposed, and get it taken down.",
    submit: "Create account",
    busy: "Creating account…",
    switchText: "Already have an account?",
    switchLink: "Log in",
    switchHref: "/login",
  },
  reset: {
    title: "Reset your password",
    sub: "Enter the one-time code an admin gave you, then choose a new password.",
    submit: "Set new password",
    busy: "Saving…",
    switchText: "Remembered it?",
    switchLink: "Log in",
    switchHref: "/login",
  },
};

// Only same-site paths, so a crafted ?next= link can't send someone to another site.
function safeNext(next?: string) {
  return next && next.startsWith("/") && !next.startsWith("//") && !next.startsWith("/\\") ? next : "/app";
}

export default function AuthForm({ mode, next }: { mode: Mode; next?: string }) {
  const router = useRouter();
  const copy = COPY[mode];
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const switchHref = next ? `${copy.switchHref}?next=${encodeURIComponent(next)}` : copy.switchHref;

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    const email = String(form.get("email") ?? "");
    const password = String(form.get("password") ?? "");
    setBusy(true);
    setError(null);
    try {
      if (mode === "signup") await api.signup({ email, password });
      else if (mode === "reset")
        await api.resetPassword({ email, code: String(form.get("code") ?? ""), new_password: password });
      else await api.login({ email, password });
      router.replace(safeNext(next)); // stays busy until the next page takes over
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  }

  return (
    <div className="site auth">
      <header className="wrap auth-top">
        <Link href="/" className="brand" aria-label="Dossier home">
          <Logo />
        </Link>
      </header>
      <main className="auth-main">
        <div className="auth-card">
          <h1 className="auth-title">{copy.title}</h1>
          <p className="auth-sub">{copy.sub}</p>
          {/* method="post": a submit before React loads must never put the password in the URL. */}
          <form className="auth-form" method="post" onSubmit={onSubmit}>
            <label className="auth-field">
              Email
              <input name="email" type="email" autoComplete="email" required autoFocus />
            </label>
            {mode === "reset" && (
              <label className="auth-field">
                Reset code
                <input
                  name="code"
                  type="text"
                  autoComplete="one-time-code"
                  autoCapitalize="characters"
                  spellCheck={false}
                  required
                  minLength={4}
                  maxLength={32}
                  placeholder="K7QM-2XRP-9HTD"
                />
              </label>
            )}
            <label className="auth-field">
              {mode === "reset" ? "New password" : "Password"}
              <input
                name="password"
                type="password"
                autoComplete={mode === "login" ? "current-password" : "new-password"}
                required
                minLength={8}
                aria-describedby={mode === "login" ? undefined : "password-hint"}
              />
              {mode !== "login" && (
                <span id="password-hint" className="auth-hint">
                  At least 8 characters.
                </span>
              )}
              {mode === "login" && (
                <Link href={next ? `/reset?next=${encodeURIComponent(next)}` : "/reset"} className="auth-hint">
                  Forgot your password?
                </Link>
              )}
            </label>
            {error && (
              <p className="auth-error" role="alert">
                {error}
              </p>
            )}
            <button type="submit" className="btn btn-primary btn-block" disabled={busy} aria-busy={busy || undefined}>
              <SwapLabel on={busy} idle={copy.submit} active={copy.busy} />
            </button>
          </form>
          <p className="auth-local">
            <Lock /> Your account is saved in Dossier&apos;s database. It isn&apos;t shared with anyone.
          </p>
        </div>
        <p className="auth-switch">
          {copy.switchText} <Link href={switchHref}>{copy.switchLink}</Link>
        </p>
      </main>
    </div>
  );
}
