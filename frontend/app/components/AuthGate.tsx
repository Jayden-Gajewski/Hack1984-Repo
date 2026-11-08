"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useContext, useEffect, useState } from "react";
import { api, type User } from "@/lib/api";
import Logo from "./Logo";

const SignedIn = createContext<User | null>(null);

/** The signed-in account (email, id, role), for components inside AuthGate. */
export function useSignedInUser(): User {
  const user = useContext(SignedIn);
  if (!user) throw new Error("useSignedInUser must be used inside AuthGate");
  return user;
}

// The signed-in app renders only after the backend confirms the session cookie.
export default function AuthGate({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [user, setUser] = useState<User | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.me().then(setUser, async (err: unknown) => {
      if ((err as { status?: number }).status === 401) {
        await api.logout().catch(() => {}); // drop a stale cookie so /app doesn't loop
        router.replace("/login?next=/app");
      } else {
        setError(err instanceof Error ? err.message : String(err));
      }
    });
  }, [router]);

  async function logout() {
    await api.logout().catch(() => {});
    router.replace("/login");
  }

  if (!user) {
    return (
      <div className="gate-wait" role="status">
        {error ? (
          <span className="error">{error}</span>
        ) : (
          <>
            <span className="spinner" aria-hidden /> Checking your session…
          </>
        )}
      </div>
    );
  }

  return (
    <>
      <header className="app-bar">
        <Link href="/" className="brand" aria-label="Dossier home">
          <Logo />
        </Link>
        <nav className="app-nav" aria-label="Sections">
          <Link href="/app" aria-current={pathname === "/app" ? "page" : undefined}>
            Exposure scan
          </Link>
          <Link href="/app/monitor" aria-current={pathname.startsWith("/app/monitor") ? "page" : undefined}>
            Threat monitor
          </Link>
          <Link href="/app/account" aria-current={pathname.startsWith("/app/account") ? "page" : undefined}>
            Account
          </Link>
        </nav>
        <div className="app-bar-user">
          <span>{user.email}</span>
          <button type="button" className="secondary" onClick={logout}>
            Log out
          </button>
        </div>
      </header>
      <SignedIn.Provider value={user}>{children}</SignedIn.Provider>
    </>
  );
}
