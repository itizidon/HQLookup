import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import type { ReactNode } from "react";

export default async function PrivateLayout({ children }: { children: ReactNode }) {
  const cookieStore = await cookies();
  const cookieName = process.env.NODE_ENV === "production" ? "__Host-token" : "token";
  const token = cookieStore.get(cookieName)?.value;

  if (!token) redirect("/auth");

  return <>{children}</>;
}
