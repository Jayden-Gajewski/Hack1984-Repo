"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { api } from "@/lib/api";
import Logo from "./Logo";
import { Lock } from "./icons";

type Mode = "login" | "signup";

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
          <form className="auth-form" onSubmit={onSubmit}>
            <label className="auth-field">
              Email
              <input name="email" type="email" autoComplete="email" required autoFocus />
            </label>
            <label className="auth-field">
              Password
              <input
                name="password"
                type="password"
                autoComplete={mode === "signup" ? "new-password" : "current-password"}
                required
                minLength={8}
                aria-describedby={mode === "signup" ? "password-hint" : undefined}
              />
              {mode === "signup" && (
                <span id="password-hint" className="auth-hint">
                  At least 8 characters.
                </span>
              )}
            </label>
            {error && (
              <p className="auth-error" role="alert">
                {error}
              </p>
            )}
            <button type="submit" className="btn btn-primary btn-block" disabled={busy}>
              {busy ? copy.busy : copy.submit}
            </button>
          </form>
          <p className="auth-local">
            <Lock /> Your account is saved in the database on this laptop. It isn&apos;t sent anywhere.
          </p>
        </div>
        <p className="auth-switch">
          {copy.switchText} <Link href={switchHref}>{copy.switchLink}</Link>
        </p>
      </main>
    </div>
  );
}
