"use client";

import AdminPanel from "../../components/AdminPanel";
import AuthGate, { useSignedInUser } from "../../components/AuthGate";
import ChangePassword from "../../components/ChangePassword";
import "../../account.css";

export default function AccountPage() {
  return (
    <AuthGate>
      <main className="scanner">
        <div className="work">
          <Account />
        </div>
      </main>
    </AuthGate>
  );
}

function Account() {
  const user = useSignedInUser();
  return (
    <>
      <header>
        <h1>Account</h1>
        <p className="lede">
          Signed in as {user.email}
          {user.role === "admin" ? ", an admin" : ""}. Your account is stored in Dossier&apos;s database and isn&apos;t
          shared with anyone.
        </p>
      </header>
      <ChangePassword />
      {user.role === "admin" && <AdminPanel me={user} />}
    </>
  );
}
