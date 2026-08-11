"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import { useBusiness } from "@/app/context/BusinessContext";
import {
  apiRequest,
  getErrorMessage,
  isAbortError,
} from "@/lib/api";

type Organization = {
  id: number;
  name: string;
  is_active: boolean;
};

type InitializationState = "loading" | "ready" | "error";

const ROUTES_WITHOUT_A_BUSINESS = new Set(["/dashboard", "/billing"]);

export default function BusinessGate({
  children,
}: {
  children: React.ReactNode;
}) {
  const { businesses, isLoading, refreshBusinesses } = useBusiness();
  const pathname = usePathname();
  const router = useRouter();
  const [initializationState, setInitializationState] =
    useState<InitializationState>("loading");
  const [error, setError] = useState<string | null>(null);
  const [retryCount, setRetryCount] = useState(0);

  useEffect(() => {
    const controller = new AbortController();

    async function initializeWorkspace() {
      try {
        const organizations = await apiRequest<Organization[]>(
          "/organizations",
          { signal: controller.signal },
        );
        await refreshBusinesses(
          organizations
            .filter((organization) => organization.is_active)
            .map((organization) => organization.id),
          { signal: controller.signal },
        );

        if (!controller.signal.aborted) {
          setInitializationState("ready");
        }
      } catch (caughtError) {
        if (isAbortError(caughtError)) return;
        setError(
          getErrorMessage(
            caughtError,
            "We could not load your workspace. Please try again.",
          ),
        );
        setInitializationState("error");
      }
    }

    void initializeWorkspace();
    return () => controller.abort();
  }, [refreshBusinesses, retryCount]);

  useEffect(() => {
    if (initializationState !== "ready" || isLoading) return;
    if (
      businesses.length === 0 &&
      !ROUTES_WITHOUT_A_BUSINESS.has(pathname)
    ) {
      router.replace("/dashboard");
    }
  }, [businesses.length, initializationState, isLoading, pathname, router]);

  if (initializationState === "loading" || isLoading) {
    return (
      <div style={styles.fallbackScreen} role="status" aria-live="polite">
        <Loader2
          className="animate-spin"
          size={24}
          aria-hidden="true"
          style={{ color: "var(--color-text-info)" }}
        />
        <span style={styles.fallbackText}>Loading workspace…</span>
      </div>
    );
  }

  if (initializationState === "error") {
    return (
      <div style={styles.fallbackScreen}>
        <div style={styles.errorBox} role="alert">
          <h1 style={styles.errorTitle}>Workspace unavailable</h1>
          <p style={styles.errorMessage}>{error}</p>
          <button
            type="button"
            className="btn"
            onClick={() => {
              setError(null);
              setInitializationState("loading");
              setRetryCount((count) => count + 1);
            }}
          >
            Try again
          </button>
        </div>
      </div>
    );
  }

  return <>{children}</>;
}

const styles: Record<string, React.CSSProperties> = {
  fallbackScreen: {
    alignItems: "center",
    backgroundColor: "var(--color-background-primary)",
    display: "flex",
    flexDirection: "column",
    gap: "12px",
    height: "100vh",
    justifyContent: "center",
    width: "100%",
  },
  fallbackText: {
    color: "var(--color-text-secondary)",
    fontSize: "13px",
    fontWeight: 500,
  },
  errorBox: {
    alignItems: "center",
    backgroundColor: "var(--color-background-danger)",
    border: "1px solid var(--color-border-danger)",
    borderRadius: "var(--border-radius-md)",
    color: "var(--color-text-danger)",
    display: "flex",
    flexDirection: "column",
    gap: "12px",
    maxWidth: "380px",
    padding: "20px",
    textAlign: "center",
  },
  errorTitle: { fontSize: "15px", fontWeight: 600, margin: 0 },
  errorMessage: { fontSize: "13px", lineHeight: 1.5, margin: 0 },
};
