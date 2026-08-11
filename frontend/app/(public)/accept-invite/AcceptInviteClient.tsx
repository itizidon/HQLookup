"use client";

import Link from "next/link";
import { Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import {
  apiRequest,
  getErrorMessage,
  isAbortError,
} from "@/lib/api";

type InvitationDetails = {
  valid: boolean;
  email: string;
  org_id: number;
  user_exists: boolean;
};

type ViewState = "verifying" | "ready" | "submitting" | "accepted" | "invalid";

export default function AcceptInviteClient({ token }: { token: string }) {
  const [viewState, setViewState] = useState<ViewState>(
    token ? "verifying" : "invalid",
  );
  const [invitation, setInvitation] = useState<InvitationDetails | null>(null);
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(
    token ? null : "This invitation link is missing its token.",
  );

  useEffect(() => {
    if (!token) return;
    const controller = new AbortController();

    async function verifyInvitation() {
      try {
        const details = await apiRequest<InvitationDetails>(
          `/auth/verify-invite?token=${encodeURIComponent(token)}`,
          {
            signal: controller.signal,
            redirectOnUnauthorized: false,
          },
        );
        if (!controller.signal.aborted) {
          setInvitation(details);
          setViewState("ready");
        }
      } catch (caughtError) {
        if (isAbortError(caughtError)) return;
        setError(
          getErrorMessage(
            caughtError,
            "This invitation is invalid, expired, or has been revoked.",
          ),
        );
        setViewState("invalid");
      }
    }

    void verifyInvitation();
    return () => controller.abort();
  }, [token]);

  async function acceptInvitation(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!invitation) return;
    if (!invitation.user_exists && (!name.trim() || password.length < 12)) {
      setError("Enter your name and a password of at least 12 characters.");
      return;
    }

    setViewState("submitting");
    setError(null);
    try {
      await apiRequest<{ status: string; message: string }>(
        "/auth/accept-invite",
        {
          method: "POST",
          redirectOnUnauthorized: false,
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            token,
            ...(invitation.user_exists
              ? {}
              : { name: name.trim(), password }),
          }),
        },
      );
      setViewState("accepted");
    } catch (caughtError) {
      setError(getErrorMessage(caughtError, "Could not accept this invitation."));
      setViewState("ready");
    }
  }

  return (
    <div className="flex min-h-full flex-1 items-center justify-center bg-zinc-50 p-8">
      <main className="w-full max-w-md rounded-xl border border-zinc-200 bg-white p-8 shadow-sm">
        <h1 className="text-2xl font-semibold text-zinc-900">Join workspace</h1>

        {viewState === "verifying" && (
          <div className="mt-6 flex items-center gap-3 text-sm text-zinc-600" role="status">
            <Loader2 className="animate-spin" size={18} aria-hidden="true" />
            Verifying your invitation…
          </div>
        )}

        {viewState === "invalid" && (
          <div className="mt-6">
            <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-800" role="alert">
              {error}
            </p>
            <Link href="/auth" className="mt-5 inline-flex text-sm font-medium underline">
              Return to sign in
            </Link>
          </div>
        )}

        {viewState === "accepted" && (
          <div className="mt-6">
            <p className="rounded-md bg-emerald-50 px-3 py-2 text-sm text-emerald-800" role="status">
              Your invitation was accepted. Sign in to open the workspace.
            </p>
            <Link
              href="/auth"
              className="mt-5 inline-flex w-full justify-center rounded-md bg-zinc-900 px-4 py-2 text-sm font-medium text-white hover:bg-zinc-700"
            >
              Continue to sign in
            </Link>
          </div>
        )}

        {(viewState === "ready" || viewState === "submitting") && invitation && (
          <form onSubmit={acceptInvitation} className="mt-6 space-y-4">
            <p className="text-sm leading-6 text-zinc-600">
              This invitation is for <strong className="text-zinc-900">{invitation.email}</strong>.
            </p>

            {!invitation.user_exists && (
              <>
                <div>
                  <label htmlFor="invite-name" className="mb-1 block text-sm font-medium text-zinc-800">
                    Name
                  </label>
                  <input
                    id="invite-name"
                    type="text"
                    autoComplete="name"
                    required
                    maxLength={120}
                    value={name}
                    onChange={(event) => setName(event.target.value)}
                    className="w-full rounded-md border border-zinc-300 px-3 py-2 text-sm outline-none focus:border-zinc-500"
                  />
                </div>
                <div>
                  <label htmlFor="invite-password" className="mb-1 block text-sm font-medium text-zinc-800">
                    Password
                  </label>
                  <input
                    id="invite-password"
                    type="password"
                    autoComplete="new-password"
                    required
                    minLength={12}
                    maxLength={72}
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    className="w-full rounded-md border border-zinc-300 px-3 py-2 text-sm outline-none focus:border-zinc-500"
                  />
                  <p className="mt-1 text-xs text-zinc-500">12–72 characters.</p>
                </div>
              </>
            )}

            {invitation.user_exists && (
              <p className="rounded-md bg-blue-50 px-3 py-2 text-sm text-blue-800">
                An account already exists for this email. Accept the invitation, then sign in with that account.
              </p>
            )}

            {error && (
              <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-800" role="alert">
                {error}
              </p>
            )}

            <button
              type="submit"
              disabled={viewState === "submitting"}
              className="flex w-full items-center justify-center gap-2 rounded-md bg-zinc-900 px-4 py-2 text-sm font-medium text-white hover:bg-zinc-700 disabled:opacity-60"
            >
              {viewState === "submitting" && (
                <Loader2 className="animate-spin" size={14} aria-hidden="true" />
              )}
              {viewState === "submitting" ? "Accepting…" : "Accept invitation"}
            </button>
          </form>
        )}
      </main>
    </div>
  );
}
