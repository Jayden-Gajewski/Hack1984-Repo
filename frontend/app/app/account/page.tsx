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
          {user.role === "admin" ? ", an admin" : ""}. Your account is stored in the database on this laptop and
          isn&apos;t sent anywhere.
        </p>
      </header>
      <ChangePassword />
      {user.role === "admin" && <AdminPanel me={user} />}
    </>
  );
}
