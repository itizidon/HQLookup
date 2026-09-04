"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState, useEffect } from "react";
import { apiFetch, responseErrorMessage } from "@/app/lib/api";
import { Turnstile } from "@/components/Turnstile";
import { BrandIcon } from "@/components/BrandIcon";

const turnstileSiteKey = process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY ?? "";

export default function SignInPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const initialMode = searchParams.get("mode") === "signup" ? "signup" : "login";

  const [mode, setMode] = useState<"login" | "signup">(initialMode);
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

  // Keep the form mode synchronized if search params change via links
  useEffect(() => {
    const modeParam = searchParams.get("mode");
    if (modeParam === "signup" || modeParam === "login") {
      setMode(modeParam);
    }
  }, [searchParams]);

  // Handle switching tabs and updating URL query parameters cleanly
  function handleModeChange(newMode: "login" | "signup") {
    setMode(newMode);
    setError(null);
    setChallengeKey((current) => current + 1);
    const query = newMode === "signup" ? "?mode=signup" : "";
    router.replace(`/auth${query}`, { scroll: false });
  }

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
          router.push("/search");
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
        router.push("/search");
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
      router.push("/search");
      router.refresh();
    } catch (error: unknown) {
      setError(error instanceof Error ? error.message : "MFA verification failed.");
    } finally {
      setLoading(false);
    }
  }

  if (pendingVerificationEmail) {
    return (
      <div className="screen" style={{ position: 'relative', overflowX: 'hidden', minHeight: '100vh', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '24px' }}>
        <main className="card" style={{ maxWidth: '400px', width: '100%', padding: '32px', textAlign: 'center' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px', marginBottom: '24px' }}>
            <div style={{ padding: '8px', borderRadius: '8px', background: 'var(--color-background-secondary, #f4f4f5)' }}>
              <BrandIcon size={20} />
            </div>
          </div>
          <h1 style={{ fontSize: '20px', fontWeight: 600, color: 'var(--color-text-primary, #18181b)', marginBottom: '12px' }}>Check your email</h1>
          <p style={{ fontSize: '13px', color: 'var(--color-text-secondary, #71717a)', lineHeight: '1.5' }}>
            We sent a verification link to <strong>{pendingVerificationEmail}</strong>. Open it to activate your account.
          </p>
          <button
            type="button"
            onClick={() => {
              setPendingVerificationEmail(null);
              handleModeChange("login");
              setPassword("");
            }}
            style={{ marginTop: '24px', fontSize: '13px', fontWeight: 500, background: 'none', border: 'none', textDecoration: 'underline', cursor: 'pointer', color: 'var(--color-text-primary)' }}
          >
            Return to login
          </button>
        </main>
      </div>
    );
  }

  if (mfaChallenge) {
    return (
      <div className="screen" style={{ position: 'relative', overflowX: 'hidden', minHeight: '100vh', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '24px' }}>
        <main className="card" style={{ maxWidth: '400px', width: '100%', padding: '32px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '20px' }}>
            <div style={{ padding: '6px', borderRadius: '6px', background: 'var(--color-background-secondary, #f4f4f5)' }}>
              <BrandIcon />
            </div>
            <span style={{ fontSize: '12px', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--color-text-secondary)' }}>
              HQLookup
            </span>
          </div>
          <h1 style={{ fontSize: '20px', fontWeight: 600, color: 'var(--color-text-primary)', marginBottom: '8px' }}>Two-factor authentication</h1>
          <p style={{ fontSize: '13px', color: 'var(--color-text-secondary)', marginBottom: '20px' }}>Enter your authenticator code or a recovery code.</p>
          <form onSubmit={handleMfaSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <input
              type="text"
              required
              autoComplete="one-time-code"
              value={mfaCode}
              onChange={(event) => setMfaCode(event.target.value)}
              placeholder="123456 or recovery code"
              style={{ width: '100%', borderRadius: '6px', border: '1px solid var(--color-border-tertiary, #e4e4e7)', padding: '8px 12px', fontSize: '13px' }}
            />
            {error && <p style={{ padding: '8px 12px', borderRadius: '6px', background: '#fef2f2', color: '#991b1b', fontSize: '12px' }}>{error}</p>}
            <button disabled={loading} className="btn btn-primary" style={{ width: '100%', justifyContent: 'center' }}>
              {loading ? "Verifying…" : "Verify"}
            </button>
          </form>
        </main>
      </div>
    );
  }

  return (
    <div className="screen" style={{ position: 'relative', overflowX: 'hidden', minHeight: '100vh', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '24px' }}>
      <main className="card" style={{ maxWidth: '400px', width: '100%', padding: '32px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '20px' }}>
          <div style={{ padding: '6px', borderRadius: '6px', background: 'var(--color-background-secondary, #f4f4f5)' }}>
            <BrandIcon />
          </div>
          <span style={{ fontSize: '12px', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--color-text-secondary)' }}>
            HQLookup Workspace
          </span>
        </div>

        <h1 style={{ fontSize: '20px', fontWeight: 600, color: 'var(--color-text-primary)', marginBottom: '6px' }}>
          {mode === "login" ? "Sign in" : "Create account"}
        </h1>
        <p style={{ fontSize: '13px', color: 'var(--color-text-secondary)', marginBottom: '20px' }}>
          {mode === "login" ? "Use your account to log in." : "Get started with your enterprise workspace."}
        </p>

        {/* Tab switcher */}
        <div style={{ display: 'flex', padding: '3px', borderRadius: '8px', background: 'var(--color-background-secondary, #f4f4f5)', marginBottom: '20px' }}>
          <button
            type="button"
            onClick={() => handleModeChange("login")}
            style={{ flex: 1, padding: '6px 12px', borderRadius: '6px', fontSize: '13px', fontWeight: 500, border: 'none', cursor: 'pointer', background: mode === "login" ? 'var(--color-background-primary, #ffffff)' : 'transparent', color: mode === "login" ? 'var(--color-text-primary)' : 'var(--color-text-secondary)', boxShadow: mode === "login" ? '0 1px 2px rgba(0,0,0,0.05)' : 'none' }}
          >
            Log in
          </button>
          <button
            type="button"
            onClick={() => handleModeChange("signup")}
            style={{ flex: 1, padding: '6px 12px', borderRadius: '6px', fontSize: '13px', fontWeight: 500, border: 'none', cursor: 'pointer', background: mode === "signup" ? 'var(--color-background-primary, #ffffff)' : 'transparent', color: mode === "signup" ? 'var(--color-text-primary)' : 'var(--color-text-secondary)', boxShadow: mode === "signup" ? '0 1px 2px rgba(0,0,0,0.05)' : 'none' }}
          >
            Sign up
          </button>
        </div>

        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          {mode === "signup" && (
            <div>
              <label htmlFor="name" style={{ display: 'block', fontSize: '12px', fontWeight: 500, marginBottom: '6px', color: 'var(--color-text-primary)' }}>Name</label>
              <input
                id="name"
                type="text"
                autoComplete="name"
                value={name}
                onChange={e => setName(e.target.value)}
                placeholder="Jane Doe"
                style={{ width: '100%', borderRadius: '6px', border: '1px solid var(--color-border-tertiary, #e4e4e7)', padding: '8px 12px', fontSize: '13px' }}
              />
            </div>
          )}

          <div>
            <label htmlFor="email" style={{ display: 'block', fontSize: '12px', fontWeight: 500, marginBottom: '6px', color: 'var(--color-text-primary)' }}>Email</label>
            <input
              id="email"
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={e => setEmail(e.target.value)}
              placeholder="you@example.com"
              style={{ width: '100%', borderRadius: '6px', border: '1px solid var(--color-border-tertiary, #e4e4e7)', padding: '8px 12px', fontSize: '13px' }}
            />
          </div>

          <div>
            <label htmlFor="password" style={{ display: 'block', fontSize: '12px', fontWeight: 500, marginBottom: '6px', color: 'var(--color-text-primary)' }}>Password</label>
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
              style={{ width: '100%', borderRadius: '6px', border: '1px solid var(--color-border-tertiary, #e4e4e7)', padding: '8px 12px', fontSize: '13px' }}
            />
            {mode === "signup" && <p style={{ fontSize: '11px', color: 'var(--color-text-secondary)', marginTop: '4px' }}>Use at least 15 characters.</p>}
          </div>

          {error && (
            <p style={{ padding: '8px 12px', borderRadius: '6px', background: '#fef2f2', color: '#991b1b', fontSize: '12px' }}>{error}</p>
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
            className="btn btn-primary"
            style={{ width: '100%', justifyContent: 'center', padding: '10px' }}
          >
            {loading ? "Please wait…" : mode === "login" ? "Log in" : "Create account"}
          </button>
        </form>

        {mode === "login" && (
          <p style={{ textAlign: 'center', fontSize: '12px', marginTop: '16px' }}>
            <Link href="/forgot-password" style={{ textDecoration: 'underline', color: 'var(--color-text-secondary)' }}>Forgot your password?</Link>
          </p>
        )}

        <p style={{ textAlign: 'center', fontSize: '12px', marginTop: '20px' }}>
          <Link href="/" style={{ textDecoration: 'underline', color: 'var(--color-text-secondary)' }}>Back to home</Link>
        </p>
      </main>
    </div>
  );
}
