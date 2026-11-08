"use client";

import { useCallback, useEffect, useState } from "react";
import { api, type ResetCode, type Role, type User } from "@/lib/api";

// Admins only: every account on this laptop, its role, a one-time password reset code for someone
// who forgot theirs, and removing an account (with its saved scans and footprint). The backend
// refuses to demote or remove the last admin.
export default function AdminPanel({ me }: { me: User }) {
  const [users, setUsers] = useState<User[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [issued, setIssued] = useState<ResetCode | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setUsers(await api.users());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function act(userId: string, fn: () => Promise<unknown>) {
    setBusyId(userId);
    try {
      await fn();
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyId(null);
    }
  }

  function changeRole(user: User, role: Role) {
    const self = user.id === me.id;
    if (self && role === "user" && !window.confirm("Make yourself a regular user? You'll lose access to this list.")) {
      return;
    }
    act(user.id!, async () => {
      await api.setRole(user.id!, role);
      if (self) window.location.reload(); // the header and this page follow the new role
    });
  }

  function remove(user: User) {
    if (window.confirm(`Remove ${user.email} with their saved scans and footprint? This can't be undone.`)) {
      act(user.id!, () => api.deleteUser(user.id!));
    }
  }

  return (
    <section className="section" aria-labelledby="accounts-h">
      <h2 id="accounts-h">Accounts on this laptop</h2>
      <p className="muted">
        You&apos;re an admin. The first account made here is one; admins can promote others. Accounts never leave
        this laptop.
      </p>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {issued && (
        <div className="notice" role="status">
          <p>
            Reset code for <strong>{issued.email}</strong>: <code className="reset-code">{issued.code}</code>
          </p>
          <p className="small mt">
            Give it to them in person. It works once, until {new Date(issued.expires_at).toLocaleTimeString()}, and
            won&apos;t be shown again. They enter it under &ldquo;Forgot your password?&rdquo; on the login page.
          </p>
          <button type="button" className="secondary mt" onClick={() => setIssued(null)}>
            Done
          </button>
        </div>
      )}
      {users === null && !error && <p className="muted">Loading accounts…</p>}
      <ul className="account-list">
        {users?.map((u) => {
          const self = u.id === me.id;
          const busy = busyId === u.id;
          return (
            <li key={u.id} className="card account-row">
              <div className="account-who">
                <strong>{u.email}</strong>
                {self && <span className="chip">you</span>}
                {u.created_at && (
                  <span className="muted small">joined {new Date(u.created_at).toLocaleDateString()}</span>
                )}
              </div>
              <div className="actions account-actions">
                <label className="account-role">
                  <span className="sr-only">Role for {u.email}</span>
                  <select value={u.role} disabled={busy} onChange={(e) => changeRole(u, e.target.value as Role)}>
                    <option value="user">User</option>
                    <option value="admin">Admin</option>
                  </select>
                </label>
                {!self && (
                  <button
                    type="button"
                    className="secondary"
                    disabled={busy}
                    onClick={() => act(u.id!, async () => setIssued(await api.resetCode(u.id!)))}
                  >
                    Reset code
                  </button>
                )}
                {!self && (
                  <button type="button" className="quiet" disabled={busy} onClick={() => remove(u)}>
                    Remove
                  </button>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
