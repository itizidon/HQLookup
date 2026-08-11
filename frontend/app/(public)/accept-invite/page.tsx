import type { Metadata } from "next";
import AcceptInviteClient from "./AcceptInviteClient";

export const metadata: Metadata = {
  title: "Accept invitation",
};

type AcceptInvitePageProps = {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

export default async function AcceptInvitePage({
  searchParams,
}: AcceptInvitePageProps) {
  const tokenParameter = (await searchParams).token;
  const token = Array.isArray(tokenParameter)
    ? tokenParameter[0] ?? ""
    : tokenParameter ?? "";

  return <AcceptInviteClient token={token} />;
}
