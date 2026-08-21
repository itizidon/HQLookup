"use client";

import { useEffect, useState, useRef } from "react";
import { useBusiness } from "@/app/context/BusinessContext";
import { usePathname, useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import { apiFetch, errorMessage, responseErrorMessage } from "@/app/lib/api";

interface OrganizationSummary {
  id: number;
}

export default function BusinessGate({ children }: { children: React.ReactNode }) {
  const { refreshBusinesses, selectedBusiness, businesses, isLoading: isContextLoading } = useBusiness();
  const router   = useRouter();
  const pathname = usePathname();
  const [isInitializing, setIsInitializing]   = useState(true);
  const [error, setError]                     = useState<string | null>(null);

  // ── Guard: prevent fetch running more than once ────────────────────────────
  const hasFetched  = useRef(false);
  // ── Guard: prevent routing from firing more than once per state ────────────
  const hasRouted   = useRef(false);

  // ── Effect 1: Bootstrap — runs exactly once ────────────────────────────────
  useEffect(() => {
    if (hasFetched.current) return;
    hasFetched.current = true;

    const initWorkspace = async () => {
      try {
        const orgRes = await apiFetch("/organizations", {
          method: "GET",
        });

        if (!orgRes.ok) {
          throw new Error(await responseErrorMessage(orgRes, "Failed to retrieve your organization setup."));
        }

        const orgData = await orgRes.json() as OrganizationSummary[] | OrganizationSummary;
        const organizations = Array.isArray(orgData) ? orgData : [orgData];
        const orgIds = organizations
          .map((organization) => organization?.id)
          .filter((id): id is number => Number.isInteger(id));

        await refreshBusinesses(orgIds);
      } catch (err: unknown) {
        console.error("[BusinessGate] Bootstrap error:", err);
        setError(errorMessage(err, "Unexpected error."));
      } finally {
        setIsInitializing(false);
      }
    };

    initWorkspace();
  }, [refreshBusinesses]);

  // Route redirects after workspace state is ready.
  useEffect(() => {
    if (isInitializing || isContextLoading) return;

    // Reset route guard whenever meaningful state changes
    hasRouted.current = false;
  }, [businesses.length, selectedBusiness?.id, isInitializing, isContextLoading]);

  useEffect(() => {
    if (isInitializing || isContextLoading) return;
    if (hasRouted.current) return; // Already routed for this state — stop

    if (businesses.length === 0) {
      if (pathname !== "/dashboard") {
        hasRouted.current = true;
        router.push("/dashboard");
      }
      return;
    }

    if (businesses.length > 0 && !selectedBusiness) return; // Wait for auto-select

    if (pathname === "/" && selectedBusiness) {
      hasRouted.current = true;
      router.push("/search");
    }
  }, [isInitializing, isContextLoading, businesses.length, selectedBusiness, pathname, router]);

  if (isInitializing || (isContextLoading && businesses.length === 0)) {
    return (
      <div style={s.fallbackScreen}>
        <Loader2 className="animate-spin" size={24} style={{ color: "var(--color-primary, #4f46e5)" }} />
        <span style={{ fontSize: "13px", color: "var(--color-text-secondary, #71717a)", fontWeight: 500 }}>
          Loading workspace...
        </span>
      </div>
    );
  }

  if (error) {
    return (
      <div style={s.fallbackScreen}>
        <div style={s.errorBox}>
          <h3 style={{ fontSize: "14px", margin: "0 0 4px 0", fontWeight: 600 }}>
            Initialization Error
          </h3>
          <p style={{ fontSize: "12px", margin: 0 }}>{error}</p>
        </div>
      </div>
    );
  }

  return <>{children}</>;
}

const s: Record<string, React.CSSProperties> = {
  fallbackScreen: {
    display: "flex", flexDirection: "column", alignItems: "center",
    justifyContent: "center", height: "100vh", width: "100vw",
    gap: "12px", backgroundColor: "var(--color-background-primary, #ffffff)",
  },
  errorBox: {
    padding: "16px", borderRadius: "6px", border: "1px solid #fecaca",
    backgroundColor: "#fef2f2", color: "#dc2626", maxWidth: "360px", textAlign: "center",
  },
};
