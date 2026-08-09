"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function SignInPage() {
  const router = useRouter();
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    if (mode === "signup" && !name.trim()) {
      setError("Name is required");
      return;
    }

    setLoading(true);

    try {
      const url = mode === "login" ? `${API_BASE}/api/auth/login` : `${API_BASE}/api/auth/signup`;
      const body =
        mode === "login"
          ? new URLSearchParams({ username: email.trim(), password })
          : JSON.stringify({ name: name.trim(), email: email.trim(), password });

      const res = await fetch(url, {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": mode === "login" ? "application/x-www-form-urlencoded" : "application/json",
        },
        body,
      });

      const data = await res.json().catch(() => ({}));

      if (!res.ok) {
        // FastAPI returns either detail: string or list of {msg}
        let message = "Something went wrong";
        if (data.detail) {
          if (typeof data.detail === "string") message = data.detail;
          else if (Array.isArray(data.detail)) message = data.detail.map(d => (d.msg ? d.msg : JSON.stringify(d))).join(", ");
        }
        throw new Error(message);
      }

      // Cookie is now set server-side; no JWT handling in frontend.
      router.push("/dashboard");
      router.refresh();
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Something went wrong";
      setError(message);
    } finally {
      setLoading(false);
    }
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
            onClick={() => { setMode("login"); setError(null); }}
            className={`flex-1 rounded-md px-3 py-2 text-sm font-medium transition-colors ${mode === "login"
                ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900"
                : "text-zinc-600 hover:bg-zinc-50 dark:text-zinc-400 dark:hover:bg-zinc-900"
              }`}
          >
            Log in
          </button>
          <button
            type="button"
            onClick={() => { setMode("signup"); setError(null); }}
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
              minLength={mode === "signup" ? 8 : undefined}
              className="w-full rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900 outline-none placeholder:text-zinc-400 focus:border-zinc-500 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
            />
            {mode === "signup" && <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-500">At least 8 characters.</p>}
          </div>

          {error && (
            <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-800 dark:bg-red-950/40 dark:text-red-200">{error}</p>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full rounded-md bg-zinc-900 px-4 py-2 text-sm font-medium text-white hover:bg-zinc-700 disabled:opacity-60 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-300"
          >
            {loading ? "Please wait…" : mode === "login" ? "Log in" : "Create account"}
          </button>
        </form>

        <p className="mt-6 text-center text-sm text-zinc-600 dark:text-zinc-400">
          <Link href="/" className="underline hover:text-zinc-900 dark:hover:text-zinc-200">Back to home</Link>
        </p>
      </main>
    </div>
  );
}