"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { apiFetch, responseErrorMessage } from "@/app/lib/api";

type VerificationState = "checking" | "verified" | "invalid";

export default function VerifyEmailPage() {
  const [state, setState] = useState<VerificationState>("checking");
  const [message, setMessage] = useState("Verifying your email…");

  useEffect(() => {
    let cancelled = false;
    const fragment = new URLSearchParams(window.location.hash.slice(1));
    const token = fragment.get("token");
    window.history.replaceState(null, "", window.location.pathname);

    if (!token) {
      Promise.resolve().then(() => {
        if (!cancelled) {
          setState("invalid");
          setMessage("This verification link is missing its token.");
        }
      });
      return () => {
        cancelled = true;
      };
    }

    apiFetch("/api/auth/verify-email", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
    })
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(await responseErrorMessage(response, "This verification link could not be used."));
        }
        if (!cancelled) {
          setState("verified");
          setMessage("Your email is verified and your account is ready.");
        }
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setState("invalid");
          setMessage(error instanceof Error ? error.message : "This verification link could not be used.");
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="flex min-h-full flex-1 items-center justify-center bg-zinc-50 p-8 dark:bg-black">
      <main className="w-full max-w-md rounded-xl border border-zinc-200 bg-white p-8 text-center shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
        <h1 className="text-2xl font-semibold text-zinc-900 dark:text-zinc-100">
          {state === "verified" ? "Email verified" : state === "invalid" ? "Verification failed" : "Verifying email"}
        </h1>
        <p className={`mt-3 text-sm ${state === "invalid" ? "text-red-700 dark:text-red-300" : "text-zinc-600 dark:text-zinc-400"}`}>
          {message}
        </p>
        {state === "verified" && (
          <Link href="/auth" className="mt-6 inline-flex w-full justify-center rounded-md bg-zinc-900 px-4 py-2 text-sm font-medium text-white dark:bg-zinc-100 dark:text-zinc-900">
            Sign in
          </Link>
        )}
        {state === "invalid" && (
          <Link href="/auth" className="mt-6 inline-flex text-sm font-medium underline text-zinc-700 dark:text-zinc-300">
            Return to login
          </Link>
        )}
      </main>
    </div>
  );
}
