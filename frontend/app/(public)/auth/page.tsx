"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { apiFetch, responseErrorMessage } from "@/app/lib/api";
import { Turnstile } from "@/components/Turnstile";

const turnstileSiteKey = process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY ?? "";

export default function SignInPage() {
  const router = useRouter();
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [turnstileToken, setTurnstileToken] = useState<string | null>(null);
  const [challengeKey, setChallengeKey] = useState(0);
  const [pendingVerificationEmail, setPendingVerificationEmail] = useState<string | null>(null);
  const [mfaChallenge, setMfaChallenge] = useState<string | null>(null);
  const [mfaCode, setMfaCode] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    if (mode === "signup" && !name.trim()) {
      setError("Name is required");
      return;
    }
    if (!turnstileToken) {
      setError("Complete the human verification challenge.");
      return;
    }

    setLoading(true);

    try {
      const path = mode === "login" ? "/api/auth/login" : "/api/auth/signup";
      const body =
        mode === "login"
          ? new URLSearchParams({
              username: email.trim(),
              password,
              "cf-turnstile-response": turnstileToken,
            })
          : JSON.stringify({
              name: name.trim(),
              email: email.trim(),
              password,
              turnstileToken,
            });

      const res = await apiFetch(path, {
        method: "POST",
        headers: {
          "Content-Type": mode === "login" ? "application/x-www-form-urlencoded" : "application/json",
        },
        body,
      });

      if (!res.ok) {
        throw new Error(await responseErrorMessage(res, "Unable to authenticate."));
      }

      if (mode === "signup") {
        const payload: unknown = await res.json();
        const verificationRequired =
          payload && typeof payload === "object" && "verification_required" in payload
            ? payload.verification_required === true
            : false;
        const verifiedEmail =
          payload && typeof payload === "object" && "email" in payload && typeof payload.email === "string"
            ? payload.email
            : email.trim();
        if (verificationRequired) {
          setPendingVerificationEmail(verifiedEmail);
        } else {
          router.push("/dashboard");
          router.refresh();
        }
      } else {
        const payload: unknown = await res.json();
        if (
          payload && typeof payload === "object" &&
          "mfa_required" in payload && payload.mfa_required === true &&
          "challenge" in payload && typeof payload.challenge === "string"
        ) {
          setMfaChallenge(payload.challenge);
          setTurnstileToken(null);
          return;
        }
        // Cookie is now set server-side; no JWT handling in frontend.
        router.push("/dashboard");
        router.refresh();
      }
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Something went wrong";
      setError(message);
      setTurnstileToken(null);
      setChallengeKey((current) => current + 1);
    } finally {
      setLoading(false);
    }
  }

  async function handleMfaSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!mfaChallenge) return;
    setLoading(true);
    setError(null);
    try {
      const response = await apiFetch("/api/auth/mfa/complete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ challenge: mfaChallenge, code: mfaCode.trim() }),
      });
      if (!response.ok) throw new Error(await responseErrorMessage(response, "MFA verification failed."));
      router.push("/dashboard");
      router.refresh();
    } catch (error: unknown) {
      setError(error instanceof Error ? error.message : "MFA verification failed.");
    } finally {
      setLoading(false);
    }
  }

  if (pendingVerificationEmail) {
    return (
      <div className="flex min-h-full flex-1 items-center justify-center bg-zinc-50 p-8 dark:bg-black">
        <main className="w-full max-w-md rounded-xl border border-zinc-200 bg-white p-8 text-center shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
          <h1 className="text-2xl font-semibold text-zinc-900 dark:text-zinc-100">Check your email</h1>
          <p className="mt-3 text-sm text-zinc-600 dark:text-zinc-400">
            We sent a verification link to <strong>{pendingVerificationEmail}</strong>. Open it to activate your account.
          </p>
          <button
            type="button"
            onClick={() => {
              setPendingVerificationEmail(null);
              setMode("login");
              setPassword("");
              setChallengeKey((current) => current + 1);
            }}
            className="mt-6 text-sm font-medium underline text-zinc-700 dark:text-zinc-300"
          >
            Return to login
          </button>
        </main>
      </div>
    );
  }

  if (mfaChallenge) {
    return (
      <div className="flex min-h-full flex-1 items-center justify-center bg-zinc-50 p-8 dark:bg-black">
        <main className="w-full max-w-md rounded-xl border border-zinc-200 bg-white p-8 shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
          <h1 className="text-2xl font-semibold text-zinc-900 dark:text-zinc-100">Two-factor authentication</h1>
          <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-400">Enter your authenticator code or a recovery code.</p>
          <form onSubmit={handleMfaSubmit} className="mt-6 space-y-4">
            <input
              type="text"
              required
              autoComplete="one-time-code"
              value={mfaCode}
              onChange={(event) => setMfaCode(event.target.value)}
              placeholder="123456 or recovery code"
              className="w-full rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900"
            />
            {error && <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-800 dark:bg-red-950/40 dark:text-red-200">{error}</p>}
            <button disabled={loading} className="w-full rounded-md bg-zinc-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-60 dark:bg-zinc-100 dark:text-zinc-900">
              {loading ? "Verifying…" : "Verify"}
            </button>
          </form>
        </main>
      </div>
    );
  }

  return (
    <div className="flex min-h-full flex-1 items-center justify-center bg-zinc-50 p-8 dark:bg-black">
      <main className="w-full max-w-md rounded-xl border border-zinc-200 bg-white p-8 shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
        <h1 className="text-2xl font-semibold text-zinc-900 dark:text-zinc-100">{mode === "login" ? "Sign in" : "Sign up"}</h1>
        <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-400">
          {mode === "login" ? "Use your account to log in." : "Create a new account."}
        </p>

        <div className="mt-6 flex rounded-lg border border-zinc-200 p-1 dark:border-zinc-700">
          <button
            type="button"
            onClick={() => { setMode("login"); setError(null); setChallengeKey((current) => current + 1); }}
            className={`flex-1 rounded-md px-3 py-2 text-sm font-medium transition-colors ${mode === "login"
                ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900"
                : "text-zinc-600 hover:bg-zinc-50 dark:text-zinc-400 dark:hover:bg-zinc-900"
              }`}
          >
            Log in
          </button>
          <button
            type="button"
            onClick={() => { setMode("signup"); setError(null); setChallengeKey((current) => current + 1); }}
            className={`flex-1 rounded-md px-3 py-2 text-sm font-medium transition-colors ${mode === "signup"
                ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900"
                : "text-zinc-600 hover:bg-zinc-50 dark:text-zinc-400 dark:hover:bg-zinc-900"
              }`}
          >
            Sign up
          </button>
        </div>

        <form onSubmit={handleSubmit} className="mt-6 space-y-4">
          {mode === "signup" && (

            <div>
              <label htmlFor="name" className="mb-1 block text-sm font-medium text-zinc-800 dark:text-zinc-200">Name</label>
              <input
                id="name"
                type="text"
                autoComplete="name"
                value={name}
                onChange={e => setName(e.target.value)}
                placeholder="Jane Doe"
                className="w-full rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900 outline-none placeholder:text-zinc-400 focus:border-zinc-500 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
              />
            </div>
          )}

          <div>
            <label htmlFor="email" className="mb-1 block text-sm font-medium text-zinc-800 dark:text-zinc-200">Email</label>
            <input
              id="email"
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={e => setEmail(e.target.value)}
              placeholder="you@example.com"
              className="w-full rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900 outline-none placeholder:text-zinc-400 focus:border-zinc-500 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
            />
          </div>

          <div>
            <label htmlFor="password" className="mb-1 block text-sm font-medium text-zinc-800 dark:text-zinc-200">Password</label>
            <input
              id="password"
              type="password"
              required
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              value={password}
              onChange={e => setPassword(e.target.value)}
              placeholder="••••••••"
              minLength={mode === "signup" ? 15 : undefined}
              maxLength={mode === "signup" ? 256 : undefined}
              className="w-full rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900 outline-none placeholder:text-zinc-400 focus:border-zinc-500 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
            />
            {mode === "signup" && <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-500">Use at least 15 characters and avoid common passwords.</p>}
          </div>

          {error && (
            <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-800 dark:bg-red-950/40 dark:text-red-200">{error}</p>
          )}

          <Turnstile
            key={`${mode}-${challengeKey}`}
            siteKey={turnstileSiteKey}
            action={mode}
            onToken={setTurnstileToken}
          />

          <button
            type="submit"
            disabled={loading || !turnstileToken}
            className="w-full rounded-md bg-zinc-900 px-4 py-2 text-sm font-medium text-white hover:bg-zinc-700 disabled:opacity-60 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-300"
          >
            {loading ? "Please wait…" : mode === "login" ? "Log in" : "Create account"}
          </button>
        </form>

        {mode === "login" && (
          <p className="mt-4 text-center text-sm text-zinc-600 dark:text-zinc-400">
            <Link href="/forgot-password" className="underline">Forgot your password?</Link>
          </p>
        )}

        <p className="mt-6 text-center text-sm text-zinc-600 dark:text-zinc-400">
          <Link href="/" className="underline hover:text-zinc-900 dark:hover:text-zinc-200">Back to home</Link>
        </p>
      </main>
    </div>
  );
}
