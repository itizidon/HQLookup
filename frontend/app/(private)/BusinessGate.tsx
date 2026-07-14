"use client";

import { useEffect, useState } from "react";
import { useBusiness } from "@/app/context/BusinessContext";
import { useRouter, usePathname } from "next/navigation"; // 👈 Added usePathname
import { Loader2 } from "lucide-react";

export default function BusinessGate({ children }: { children: React.ReactNode }) {
  const { refreshBusinesses, selectedBusiness, businesses, isLoading: isContextLoading } = useBusiness();
  const router = useRouter();
  const pathname = usePathname(); // 👈 Track current URL path
  
  const [isInitializing, setIsInitializing] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // 1. Fetch organizations and bootstrap business context on mount
  useEffect(() => {
    const initWorkspace = async () => {
      try {
        const orgRes = await fetch("http://localhost:8000/organizations", {
          method: "GET",
          credentials: "include",
        });

        if (!orgRes.ok) {
          throw new Error("Failed to retrieve your organization setup.");
        }

        const orgData = await orgRes.json();
        const activeOrg = Array.isArray(orgData) ? orgData[0] : orgData;
        
        if (activeOrg && activeOrg.id) {
          await refreshBusinesses([activeOrg.id]);
        } else {
          await refreshBusinesses([]);
        }
      } catch (err: any) {
        console.error("Critical workspace bootstrap failure:", err);
        setError(err.message || "An unexpected system synchronization error occurred.");
      } finally {
        setIsInitializing(false);
      }
    };

    initWorkspace();
  }, [refreshBusinesses]);

  // 2. Handle routing intelligently without infinite loops
  useEffect(() => {
    if (isInitializing || isContextLoading) return;

    // CASE A: User has NO businesses setup
    if (businesses.length === 0) {
      // Only redirect to /businesses if they aren't already sitting on it!
      if (pathname !== "/businesses") {
        router.push("/businesses");
      }
      return;
    }

    // CASE B: User HAS businesses, but is landing on a root or entry page
    // (We don't want to redirect them if they are actively trying to manage settings or view details)
    const isAtEntryRoot = pathname === "/";
    if (isAtEntryRoot && selectedBusiness) {
      router.push("/search");
    }
    
  }, [isInitializing, isContextLoading, businesses, selectedBusiness, pathname, router]);

  // 3. Render loading spinner
  if (isInitializing || (isContextLoading && businesses.length === 0)) {
    return (
      <div style={s.fallbackScreen}>
        <Loader2 className="animate-spin" size={24} style={{ color: "var(--color-primary, #4f46e5)" }} />
        <span style={{ fontSize: "13px", color: "var(--color-text-secondary, #71717a)", fontWeight: 500 }}>
          Synchronizing secure tenant environments...
        </span>
      </div>
    );
  }

  if (error) {
    return (
      <div style={s.fallbackScreen}>
        <div style={s.errorBox}>
          <h3 style={{ fontSize: "14px", margin: "0 0 4px 0", fontWeight: 600 }}>System Initialization Error</h3>
          <p style={{ fontSize: "12px", margin: 0 }}>{error}</p>
        </div>
      </div>
    );
  }

  return <>{children}</>;
}

const s: Record<string, React.CSSProperties> = {
  fallbackScreen: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    justifyContent: "center",
    height: "100vh",
    width: "100vw",
    gap: "12px",
    backgroundColor: "var(--color-background-primary, #ffffff)",
  },
  errorBox: {
    padding: "16px",
    borderRadius: "6px",
    border: "1px solid #fecaca",
    backgroundColor: "#fef2f2",
    color: "#dc2626",
    maxWidth: "360px",
    textAlign: "center",
  },
};