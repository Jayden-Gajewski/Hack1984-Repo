import type { Metadata } from "next";
import AuthForm from "../components/AuthForm";

export const metadata: Metadata = {
  title: "Reset your password",
  description: "Set a new Dossier password with the one-time code an admin on this laptop gave you.",
};

export default async function ResetPage({ searchParams }: { searchParams: Promise<{ next?: string | string[] }> }) {
  const { next } = await searchParams;
  return <AuthForm mode="reset" next={typeof next === "string" ? next : undefined} />;
}
