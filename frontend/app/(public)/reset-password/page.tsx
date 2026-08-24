"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { apiFetch, responseErrorMessage } from "@/app/lib/api";
import { Turnstile } from "@/components/Turnstile";

const siteKey = process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY ?? "";

export default function ResetPasswordPage() {
  const [resetToken, setResetToken] = useState("");
  const [password, setPassword] = useState("");
  const [turnstileToken, setTurnstileToken] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [challengeKey, setChallengeKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    const params = new URLSearchParams(window.location.hash.slice(1));
    const token = params.get("token") ?? "";
    window.history.replaceState(null, "", window.location.pathname);
    Promise.resolve().then(() => {
      if (!cancelled) setResetToken(token);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!turnstileToken || !resetToken) return;
    setError(null);
    setLoading(true);
    try {
      const response = await apiFetch("/api/auth/reset-password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token: resetToken, password, turnstileToken }),
      });
      if (!response.ok) {
        setError(await responseErrorMessage(response, "Unable to reset the password."));
        setTurnstileToken(null);
        setChallengeKey((current) => current + 1);
        return;
      }
      setPassword("");
      setMessage("Password changed. You can now sign in.");
    } catch {
      setError("Unable to reset the password. Try again.");
      setTurnstileToken(null);
      setChallengeKey((current) => current + 1);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-full flex-1 items-center justify-center bg-zinc-50 p-8 dark:bg-black">
      <main className="w-full max-w-md rounded-xl border border-zinc-200 bg-white p-8 dark:border-zinc-800 dark:bg-zinc-950">
        <h1 className="text-2xl font-semibold">Choose a new password</h1>
        {message ? <><p className="mt-4 text-sm">{message}</p><Link href="/auth" className="mt-6 inline-block underline">Sign in</Link></> : (
          <form onSubmit={submit} className="mt-6 space-y-4">
            <input type="password" required minLength={15} maxLength={256} autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="At least 15 characters" className="w-full rounded-md border px-3 py-2 dark:bg-zinc-900" />
            <Turnstile key={challengeKey} siteKey={siteKey} action="password_reset" onToken={setTurnstileToken} />
            {error && <p className="text-sm text-red-700">{error}</p>}
            <button disabled={!turnstileToken || !resetToken || loading} className="w-full rounded-md bg-zinc-900 px-4 py-2 text-white disabled:opacity-60 dark:bg-zinc-100 dark:text-zinc-900">{loading ? "Changing…" : "Change password"}</button>
          </form>
        )}
      </main>
    </div>
  );
}
