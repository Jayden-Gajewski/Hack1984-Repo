"use client";

import { useCallback, useEffect, useState } from "react";
import { api, type ResetCode, type Role, type User } from "@/lib/api";

interface Props {
  me: User;
}

// Admins only: everyone with an account, their role, a password reset code for someone who
// forgot theirs, and a way to remove them. Deleting a user also deletes their saved scans.
// The backend refuses to remove or demote the last admin.
export default function AdminPanel({ me }: Props) {
  const [users, setUsers] = useState<User[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [issued, setIssued] = useState<ResetCode | null>(null);

  const load = useCallback(async () => {
    try {
      setUsers(await api.users());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't load users");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function act(fn: () => Promise<unknown>) {
    try {
      await fn();
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "That didn't work");
    }
  }

  return (
    <div className="panel">
      <h2>Users (admin)</h2>
      {error && <p className="error">{error}</p>}
      {issued && (
        <div className="card">
          <p>
            Reset code for <strong>{issued.username}</strong>: <code>{issued.code}</code>
          </p>
          <p className="muted">
            Give it to them in person. It works once, until {new Date(issued.expires_at).toLocaleTimeString()}.
            It won&apos;t be shown again. They enter it under &ldquo;Forgot password?&rdquo; on the login screen.
          </p>
          <button type="button" className="secondary" onClick={() => setIssued(null)}>
            Done
          </button>
        </div>
      )}
      {users.map((u) => (
        <div key={u.id} className="row log-row">
          <strong>{u.username}</strong>
          {u.id === me.id && <span className="muted">(you)</span>}
          <span className="muted">joined {new Date(u.created_at).toLocaleDateString()}</span>
          <select
            value={u.role}
            aria-label={`Role for ${u.username}`}
            onChange={(e) => act(() => api.setRole(u.id, e.target.value as Role))}
          >
            <option value="user">user</option>
            <option value="admin">admin</option>
          </select>
          {u.id !== me.id && (
            <button
              type="button"
              className="secondary"
              onClick={() =>
                act(async () => {
                  setIssued(await api.resetCode(u.id));
                })
              }
            >
              Reset code
            </button>
          )}
          {u.id !== me.id && (
            <button
              type="button"
              className="secondary"
              onClick={() => {
                if (window.confirm(`Delete ${u.username} and their saved scans? This can't be undone.`)) {
                  act(() => api.deleteUser(u.id));
                }
              }}
            >
              Delete
            </button>
          )}
        </div>
      ))}
    </div>
  );
}
