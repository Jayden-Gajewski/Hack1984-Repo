import type { Metadata } from "next";
import AuthForm from "../components/AuthForm";

export const metadata: Metadata = { title: "Create your Dossier account" };

export default async function SignupPage({ searchParams }: { searchParams: Promise<{ next?: string | string[] }> }) {
  const { next } = await searchParams;
  return <AuthForm mode="signup" next={typeof next === "string" ? next : undefined} />;
}
