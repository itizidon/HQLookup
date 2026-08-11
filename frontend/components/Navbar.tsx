"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { FileText, Loader2, LogOut } from "lucide-react";
import { useRouter } from "next/navigation";
import { useBusiness } from "@/app/context/BusinessContext";
import { ApiError, apiRequest, getErrorMessage } from "@/lib/api";

export default function Navbar({ avatarInitials = "U" }: { avatarInitials?: string }) {
  const [isOpen, setIsOpen] = useState(false);
  const [isSigningOut, setIsSigningOut] = useState(false);
  const [signOutError, setSignOutError] = useState<string | null>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const router = useRouter();
  const { resetBusinesses } = useBusiness();

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (
        dropdownRef.current &&
        !dropdownRef.current.contains(event.target as Node)
      ) {
        setIsOpen(false);
      }
    }

    function handleEscape(event: KeyboardEvent) {
      if (event.key === "Escape") setIsOpen(false);
    }

    document.addEventListener("mousedown", handleClickOutside);
    document.addEventListener("keydown", handleEscape);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      document.removeEventListener("keydown", handleEscape);
    };
  }, []);

  async function handleSignOut() {
    setIsSigningOut(true);
    setSignOutError(null);

    try {
      await apiRequest<{ message: string }>("/auth/logout", {
        method: "POST",
        redirectOnUnauthorized: false,
      });
    } catch (error) {
      if (!(error instanceof ApiError && error.status === 401)) {
        setSignOutError(getErrorMessage(error, "Sign out failed."));
        setIsSigningOut(false);
        return;
      }
    }

    resetBusinesses();
    router.replace("/");
    router.refresh();
  }

  return (
    <nav className="nav" style={{ position: "relative" }} aria-label="Primary">
      <Link href="/dashboard" className="nav-logo" style={{ textDecoration: "none" }}>
        <FileText size={18} aria-hidden="true" style={{ color: "var(--color-text-info)" }} />
        HQLookup
      </Link>

      <div className="nav-right" style={{ gap: "16px" }}>
        <Link href="/billing" className="nav-link">
          Billing
        </Link>

        <div style={{ position: "relative" }} ref={dropdownRef}>
          <button
            type="button"
            className="avatar"
            aria-label="Open account menu"
            aria-expanded={isOpen}
            aria-haspopup="menu"
            onClick={() => {
              setIsOpen((open) => !open);
              setSignOutError(null);
            }}
            style={{ border: 0, cursor: "pointer", userSelect: "none" }}
          >
            {avatarInitials}
          </button>

          {isOpen && (
            <div role="menu" style={styles.menu}>
              <button
                type="button"
                role="menuitem"
                onClick={() => void handleSignOut()}
                disabled={isSigningOut}
                style={styles.signOutButton}
              >
                {isSigningOut ? (
                  <Loader2 className="animate-spin" size={14} aria-hidden="true" />
                ) : (
                  <LogOut size={14} aria-hidden="true" />
                )}
                {isSigningOut ? "Signing out…" : "Sign out"}
              </button>
              {signOutError && (
                <p role="alert" style={styles.error}>
                  {signOutError}
                </p>
              )}
            </div>
          )}
        </div>
      </div>
    </nav>
  );
}

const styles: Record<string, React.CSSProperties> = {
  menu: {
    background: "var(--color-background-primary)",
    border: "1px solid var(--color-border-tertiary)",
    borderRadius: "var(--border-radius-md)",
    boxShadow: "0 4px 12px rgba(0,0,0,0.08)",
    display: "flex",
    flexDirection: "column",
    gap: "2px",
    padding: "4px",
    position: "absolute",
    right: 0,
    top: "calc(100% + 8px)",
    width: "180px",
    zIndex: 1000,
  },
  signOutButton: {
    alignItems: "center",
    background: "transparent",
    border: "none",
    borderRadius: "4px",
    color: "var(--color-text-danger)",
    cursor: "pointer",
    display: "flex",
    fontSize: "13px",
    gap: "8px",
    padding: "8px 10px",
    textAlign: "left",
    width: "100%",
  },
  error: {
    color: "var(--color-text-danger)",
    fontSize: "11px",
    lineHeight: 1.4,
    margin: 0,
    padding: "4px 10px 6px",
  },
};
