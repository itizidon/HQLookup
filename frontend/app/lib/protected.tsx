import { cookies } from "next/headers";
import { redirect } from "next/navigation";

export default async function ProtectedLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const hasSession = (await cookies()).has("token");

  if (!hasSession) redirect("/auth");

  return <>{children}</>;
}
