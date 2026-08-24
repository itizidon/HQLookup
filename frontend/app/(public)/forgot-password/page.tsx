"use client";

import Link from "next/link";
import { useState } from "react";
import { apiFetch, responseErrorMessage } from "@/app/lib/api";
import { Turnstile } from "@/components/Turnstile";

const siteKey = process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY ?? "";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [token, setToken] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [challengeKey, setChallengeKey] = useState(0);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!token) return;
    setError(null);
    setLoading(true);
    try {
      const response = await apiFetch("/api/auth/request-password-reset", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, turnstileToken: token }),
      });
      if (!response.ok) {
        setError(await responseErrorMessage(response, "Unable to request a reset."));
        setToken(null);
        setChallengeKey((current) => current + 1);
        return;
      }
      setMessage("If that account exists, a reset link will be sent.");
    } catch {
      setError("Unable to request a reset. Try again.");
      setToken(null);
      setChallengeKey((current) => current + 1);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-full flex-1 items-center justify-center bg-zinc-50 p-8 dark:bg-black">
      <main className="w-full max-w-md rounded-xl border border-zinc-200 bg-white p-8 dark:border-zinc-800 dark:bg-zinc-950">
        <h1 className="text-2xl font-semibold">Reset password</h1>
        {message ? <p className="mt-4 text-sm">{message}</p> : (
          <form onSubmit={submit} className="mt-6 space-y-4">
            <input type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" className="w-full rounded-md border px-3 py-2 dark:bg-zinc-900" />
            <Turnstile key={challengeKey} siteKey={siteKey} action="password_reset_request" onToken={setToken} />
            {error && <p className="text-sm text-red-700">{error}</p>}
            <button disabled={!token || loading} className="w-full rounded-md bg-zinc-900 px-4 py-2 text-white disabled:opacity-60 dark:bg-zinc-100 dark:text-zinc-900">{loading ? "Sending…" : "Send reset link"}</button>
          </form>
        )}
        <Link href="/auth" className="mt-6 inline-block text-sm underline">Return to login</Link>
      </main>
    </div>
  );
}
