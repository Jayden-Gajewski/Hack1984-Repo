import type { Metadata } from "next";
import AuthForm from "../components/AuthForm";

export const metadata: Metadata = { title: "Log in to Dossier" };

export default async function LoginPage({ searchParams }: { searchParams: Promise<{ next?: string | string[] }> }) {
  const { next } = await searchParams;
  return <AuthForm mode="login" next={typeof next === "string" ? next : undefined} />;
}
