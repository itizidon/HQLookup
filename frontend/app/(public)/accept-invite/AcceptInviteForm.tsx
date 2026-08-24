'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { CheckCircle2, FileText, Loader2 } from 'lucide-react';
import { apiFetch, errorMessage, responseErrorMessage } from '@/app/lib/api';

interface InvitationDetails {
  email: string;
  userExists: boolean;
}

type VerificationState =
  | { status: 'checking' }
  | { status: 'invalid'; message: string }
  | { status: 'ready'; invitation: InvitationDetails }
  | { status: 'accepted'; email: string };

function parseInvitation(payload: unknown): InvitationDetails | null {
  if (!payload || typeof payload !== 'object') return null;

  const candidate = payload as {
    valid?: unknown;
    email?: unknown;
    user_exists?: unknown;
  };
  if (candidate.valid !== true || typeof candidate.email !== 'string') return null;

  return {
    email: candidate.email,
    userExists: candidate.user_exists === true,
  };
}

export default function AcceptInviteForm() {
  const [token, setToken] = useState('');
  const [verification, setVerification] = useState<VerificationState>({ status: 'checking' });
  const [name, setName] = useState('');
  const [password, setPassword] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  useEffect(() => {
    // A URL fragment is never sent to the web server or included in HTTP
    // referrers. Retain the token only in component memory, then immediately
    // remove it from the address bar and browser history.
    const fragmentToken = new URLSearchParams(
      window.location.hash.replace(/^#/, ''),
    ).get('token') ?? '';
    window.history.replaceState(null, '', window.location.pathname);

    const controller = new AbortController();

    async function verifyInvitation() {
      if (!fragmentToken) {
        setVerification({
          status: 'invalid',
          message: 'This invitation link is missing its token.',
        });
        return;
      }

      setToken(fragmentToken);

      try {
        const response = await apiFetch('/auth/verify-invite', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ token: fragmentToken }),
          signal: controller.signal,
        });

        if (!response.ok) {
          throw new Error(await responseErrorMessage(response, 'This invitation is invalid or has expired.'));
        }

        const invitation = parseInvitation(await response.json());
        if (!invitation) {
          throw new Error('The invitation response was not valid.');
        }

        setVerification({ status: 'ready', invitation });
      } catch (error: unknown) {
        if (!controller.signal.aborted) {
          setVerification({
            status: 'invalid',
            message: errorMessage(error, 'This invitation could not be verified.'),
          });
        }
      }
    }

    void verifyInvitation();
    return () => controller.abort();
  }, []);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (verification.status !== 'ready') return;

    const { invitation } = verification;
    if (!invitation.userExists && !name.trim()) {
      setSubmitError('Your name is required.');
      return;
    }

    setIsSubmitting(true);
    setSubmitError(null);

    try {
      const response = await apiFetch('/auth/accept-invite', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          token,
          password,
          name: invitation.userExists ? 'User' : name.trim(),
        }),
      });

      if (!response.ok) {
        throw new Error(await responseErrorMessage(response, 'The invitation could not be accepted.'));
      }

      setPassword('');
      setVerification({ status: 'accepted', email: invitation.email });
    } catch (error: unknown) {
      setSubmitError(errorMessage(error, 'The invitation could not be accepted.'));
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-full flex-1 items-center justify-center bg-zinc-50 p-8 dark:bg-black">
      <main className="w-full max-w-md rounded-xl border border-zinc-200 bg-white p-8 shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
        <div className="flex items-center gap-2 text-zinc-900 dark:text-zinc-100">
          <FileText size={20} aria-hidden="true" />
          <span className="text-sm font-semibold">HQLookup</span>
        </div>

        {verification.status === 'checking' && (
          <div className="flex flex-col items-center gap-3 py-12 text-center" role="status">
            <Loader2 className="animate-spin text-zinc-500" size={24} aria-hidden="true" />
            <p className="text-sm text-zinc-600 dark:text-zinc-400">Verifying your invitation…</p>
          </div>
        )}

        {verification.status === 'invalid' && (
          <div className="pt-8">
            <h1 className="text-2xl font-semibold text-zinc-900 dark:text-zinc-100">Invitation unavailable</h1>
            <p className="mt-3 rounded-md bg-red-50 px-3 py-2 text-sm text-red-800 dark:bg-red-950/40 dark:text-red-200" role="alert">
              {verification.message}
            </p>
            <Link href="/auth" className="mt-6 inline-flex text-sm font-medium underline text-zinc-700 dark:text-zinc-300">
              Go to sign in
            </Link>
          </div>
        )}

        {verification.status === 'accepted' && (
          <div className="pt-8 text-center">
            <CheckCircle2 className="mx-auto text-emerald-600" size={36} aria-hidden="true" />
            <h1 className="mt-4 text-2xl font-semibold text-zinc-900 dark:text-zinc-100">Invitation accepted</h1>
            <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-400">
              {verification.email} can now access the workspace.
            </p>
            <Link href="/auth" className="mt-6 inline-flex w-full justify-center rounded-md bg-zinc-900 px-4 py-2 text-sm font-medium text-white dark:bg-zinc-100 dark:text-zinc-900">
              Continue to sign in
            </Link>
          </div>
        )}

        {verification.status === 'ready' && (
          <div className="pt-8">
            <h1 className="text-2xl font-semibold text-zinc-900 dark:text-zinc-100">Join the workspace</h1>
            <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-400">
              Accept the invitation for <strong>{verification.invitation.email}</strong>.
            </p>

            <form onSubmit={handleSubmit} className="mt-6 space-y-4">
              {!verification.invitation.userExists && (
                <div>
                  <label htmlFor="invite-name" className="mb-1 block text-sm font-medium text-zinc-800 dark:text-zinc-200">Name</label>
                  <input
                    id="invite-name"
                    type="text"
                    autoComplete="name"
                    required
                    value={name}
                    onChange={(event) => setName(event.target.value)}
                    className="w-full rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900 outline-none focus:border-zinc-500 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
                  />
                </div>
              )}

              <div>
                <label htmlFor="invite-password" className="mb-1 block text-sm font-medium text-zinc-800 dark:text-zinc-200">
                  {verification.invitation.userExists ? 'Confirm your password' : 'Create a password'}
                </label>
                <input
                  id="invite-password"
                  type="password"
                  autoComplete={verification.invitation.userExists ? 'current-password' : 'new-password'}
                  minLength={15}
                  maxLength={256}
                  required
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  className="w-full rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900 outline-none focus:border-zinc-500 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
                />
                {!verification.invitation.userExists && (
                  <p className="mt-1 text-xs text-zinc-500">Use at least 15 characters and avoid common passwords.</p>
                )}
              </div>

              {submitError && (
                <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-800 dark:bg-red-950/40 dark:text-red-200" role="alert">
                  {submitError}
                </p>
              )}

              <button
                type="submit"
                disabled={isSubmitting}
                className="inline-flex w-full items-center justify-center gap-2 rounded-md bg-zinc-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-60 dark:bg-zinc-100 dark:text-zinc-900"
              >
                {isSubmitting && <Loader2 className="animate-spin" size={15} aria-hidden="true" />}
                {isSubmitting ? 'Accepting…' : 'Accept invitation'}
              </button>
            </form>
          </div>
        )}
      </main>
    </div>
  );
}
