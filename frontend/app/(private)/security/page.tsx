"use client";

import { useEffect, useState } from "react";
import Navbar from "@/components/Navbar";
import { apiFetch, responseErrorMessage } from "@/app/lib/api";

export default function SecurityPage() {
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [secret, setSecret] = useState<string | null>(null);
  const [provisioningUri, setProvisioningUri] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [recoveryCodes, setRecoveryCodes] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiFetch("/api/auth/mfa/status")
      .then((response) => response.json())
      .then((payload: { enabled?: unknown }) => setEnabled(payload.enabled === true))
      .catch(() => setError("Unable to load security settings."));
  }, []);

  async function beginSetup() {
    setError(null);
    const response = await apiFetch("/api/auth/mfa/setup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
    });
    if (!response.ok) return setError(await responseErrorMessage(response, "Unable to start MFA setup."));
    const payload = await response.json() as { secret: string; provisioning_uri: string };
    setSecret(payload.secret);
    setProvisioningUri(payload.provisioning_uri);
  }

  async function enableMfa() {
    const response = await apiFetch("/api/auth/mfa/enable", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code }),
    });
    if (!response.ok) return setError(await responseErrorMessage(response, "Unable to enable MFA."));
    const payload = await response.json() as { recovery_codes: string[] };
    setRecoveryCodes(payload.recovery_codes);
    setEnabled(true);
    setSecret(null);
    setPassword("");
    setCode("");
  }

  async function disableMfa() {
    const response = await apiFetch("/api/auth/mfa/disable", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password, code }),
    });
    if (!response.ok) return setError(await responseErrorMessage(response, "Unable to disable MFA."));
    setEnabled(false);
    setPassword("");
    setCode("");
  }

  return (
    <><Navbar /><main className="mx-auto w-full max-w-2xl p-8">
      <h1 className="text-2xl font-semibold">Account security</h1>
      <section className="mt-6 rounded-xl border border-zinc-200 p-6 dark:border-zinc-800">
        <h2 className="text-lg font-medium">Authenticator app</h2>
        <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-400">Status: {enabled === null ? "Loading…" : enabled ? "Enabled" : "Disabled"}</p>
        {!enabled && !secret && <div className="mt-4 space-y-3"><input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Current password" className="w-full rounded-md border px-3 py-2 dark:bg-zinc-900" /><button onClick={beginSetup} className="rounded-md bg-zinc-900 px-4 py-2 text-sm text-white dark:bg-zinc-100 dark:text-zinc-900">Set up MFA</button></div>}
        {secret && <div className="mt-4 space-y-3">
          <p className="text-sm">Add this key to your authenticator app:</p>
          <code className="block break-all rounded bg-zinc-100 p-3 text-sm dark:bg-zinc-900">{secret}</code>
          <details className="text-xs"><summary>Provisioning URI</summary><code className="break-all">{provisioningUri}</code></details>
          <input value={code} onChange={(e) => setCode(e.target.value)} placeholder="6-digit code" autoComplete="one-time-code" className="w-full rounded-md border px-3 py-2 dark:bg-zinc-900" />
          <button onClick={enableMfa} className="rounded-md bg-zinc-900 px-4 py-2 text-sm text-white dark:bg-zinc-100 dark:text-zinc-900">Confirm and enable</button>
        </div>}
        {enabled && <div className="mt-4 space-y-3">
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Current password" className="w-full rounded-md border px-3 py-2 dark:bg-zinc-900" />
          <input value={code} onChange={(e) => setCode(e.target.value)} placeholder="Authenticator or recovery code" className="w-full rounded-md border px-3 py-2 dark:bg-zinc-900" />
          <button onClick={disableMfa} className="rounded-md border border-red-500 px-4 py-2 text-sm text-red-600">Disable MFA</button>
        </div>}
        {recoveryCodes.length > 0 && <div className="mt-6 rounded-md bg-amber-50 p-4 text-amber-950">
          <strong>Save these recovery codes now. They will not be shown again.</strong>
          <p className="mt-1 text-sm">For safety, your existing sessions were signed out. Sign in again after saving these codes.</p>
          <ul className="mt-2 grid grid-cols-2 gap-1 font-mono text-sm">{recoveryCodes.map((item) => <li key={item}>{item}</li>)}</ul>
        </div>}
        {error && <p className="mt-4 text-sm text-red-700">{error}</p>}
      </section>
    </main></>
  );
}
