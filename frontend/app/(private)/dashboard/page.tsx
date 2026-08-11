"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Building2,
  ChevronDown,
  Loader2,
  Plus,
  ShieldAlert,
  X,
} from "lucide-react";
import Navbar from "@/components/Navbar";
import MetricCard from "@/components/MetricCard";
import {
  type Business,
  useBusiness,
} from "@/app/context/BusinessContext";
import {
  apiRequest,
  getErrorMessage,
  isAbortError,
} from "@/lib/api";

interface Organization {
  id: number;
  name: string;
  owner_id: number;
  is_active: boolean;
}

interface UserProfile {
  id: number;
  email: string;
  name: string;
  plan: string;
  max_businesses: number;
  max_organizations: number;
}

interface BusinessMetric {
  id: number;
  name: string;
  allocation: number;
  usage: number;
}

interface WorkspaceMetrics {
  is_owner: boolean;
  max_queries_allowed: number;
  total_combined_usage: number;
  personal_user_usage: number;
  businesses: BusinessMetric[];
}

type MetricsSnapshot = {
  orgId: number;
  data: WorkspaceMetrics;
};

function getInitials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "U";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return `${parts[0][0]}${parts.at(-1)?.[0] ?? ""}`.toUpperCase();
}

function percent(used: number, allowed: number): number {
  if (allowed <= 0) return used > 0 ? 100 : 0;
  return Math.min(Math.max(Math.round((used / allowed) * 100), 0), 100);
}

export default function AdminDashboard() {
  const router = useRouter();
  const {
    businesses,
    selectBusiness,
    isLoading: isLoadingBusinesses,
    refreshBusinesses,
  } = useBusiness();

  const [organizations, setOrganizations] = useState<Organization[]>([]);
  const [currentOrgId, setCurrentOrgId] = useState<number | null>(null);
  const [userProfile, setUserProfile] = useState<UserProfile | null>(null);
  const [isLoadingPage, setIsLoadingPage] = useState(true);
  const [pageError, setPageError] = useState<string | null>(null);
  const [metricsSnapshot, setMetricsSnapshot] =
    useState<MetricsSnapshot | null>(null);

  const [isOrgModalOpen, setIsOrgModalOpen] = useState(false);
  const [orgName, setOrgName] = useState("");
  const [isCreatingOrg, setIsCreatingOrg] = useState(false);
  const [orgError, setOrgError] = useState<string | null>(null);

  const [isBizModalOpen, setIsBizModalOpen] = useState(false);
  const [bizName, setBizName] = useState("");
  const [isCreatingBiz, setIsCreatingBiz] = useState(false);
  const [bizError, setBizError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();

    async function loadPage() {
      try {
        const [profile, organizationList] = await Promise.all([
          apiRequest<UserProfile>("/auth/me", { signal: controller.signal }),
          apiRequest<Organization[]>("/organizations", {
            signal: controller.signal,
          }),
        ]);

        if (controller.signal.aborted) return;
        setUserProfile(profile);
        setOrganizations(organizationList);
        setCurrentOrgId(organizationList[0]?.id ?? null);
      } catch (caughtError) {
        if (isAbortError(caughtError)) return;
        setPageError(
          getErrorMessage(caughtError, "Could not load your dashboard."),
        );
      } finally {
        if (!controller.signal.aborted) setIsLoadingPage(false);
      }
    }

    void loadPage();
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!currentOrgId) return;
    const orgId = currentOrgId;
    const controller = new AbortController();

    async function loadMetrics() {
      try {
        const data = await apiRequest<WorkspaceMetrics>(
          `/auth/usage-metrics?org_id=${orgId}`,
          { signal: controller.signal },
        );
        if (!controller.signal.aborted) {
          setMetricsSnapshot({ orgId, data });
        }
      } catch (caughtError) {
        if (!isAbortError(caughtError)) {
          setPageError(
            getErrorMessage(caughtError, "Could not load workspace usage."),
          );
        }
      }
    }

    void loadMetrics();
    return () => controller.abort();
  }, [currentOrgId]);

  const currentOrganization = organizations.find(
    (organization) => organization.id === currentOrgId,
  );
  const filteredBusinesses = useMemo(
    () => businesses.filter((business) => business.org_id === currentOrgId),
    [businesses, currentOrgId],
  );
  const metricsData =
    metricsSnapshot?.orgId === currentOrgId ? metricsSnapshot.data : null;
  const plan = userProfile?.plan?.toLowerCase() || "free";
  const maxOrganizationsAllowed = userProfile?.max_organizations ?? 1;
  const maxBusinessesAllowed = userProfile?.max_businesses ?? 1;
  const isOrgLimitReached =
    organizations.length >= maxOrganizationsAllowed;
  const isBizLimitReached =
    filteredBusinesses.length >= maxBusinessesAllowed;

  async function handleCreateOrganization(event: React.FormEvent) {
    event.preventDefault();
    const name = orgName.trim();
    if (!name || isOrgLimitReached) return;

    setIsCreatingOrg(true);
    setOrgError(null);
    try {
      const organization = await apiRequest<Organization>("/organizations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
      setOrganizations((current) => [...current, organization]);
      setCurrentOrgId(organization.id);
      setOrgName("");
      setIsOrgModalOpen(false);
    } catch (caughtError) {
      setOrgError(
        getErrorMessage(caughtError, "Could not create the organization."),
      );
    } finally {
      setIsCreatingOrg(false);
    }
  }

  async function handleCreateBusiness(event: React.FormEvent) {
    event.preventDefault();
    const name = bizName.trim();
    if (!name || !currentOrgId || isBizLimitReached) return;

    setIsCreatingBiz(true);
    setBizError(null);
    try {
      const created = await apiRequest<{ id: number; name: string }>(
        "/businesses",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name, org_id: currentOrgId }),
        },
      );
      const refreshed = await refreshBusinesses(
        organizations.map((organization) => organization.id),
      );
      const createdBusiness =
        refreshed.find((business) => business.id === created.id) ?? {
          ...created,
          org_id: currentOrgId,
        };
      selectBusiness(createdBusiness);
      setBizName("");
      setIsBizModalOpen(false);
    } catch (caughtError) {
      setBizError(
        getErrorMessage(caughtError, "Could not create the business."),
      );
    } finally {
      setIsCreatingBiz(false);
    }
  }

  function openSearch(business: Business) {
    selectBusiness(business);
    router.push(`/search?orgId=${business.org_id}&bizId=${business.id}`);
  }

  function manageBusiness(business: Business) {
    selectBusiness(business);
    router.push(`/businesses?orgId=${business.org_id}&bizId=${business.id}`);
  }

  return (
    <div className="screen" style={{ overflowX: "hidden", position: "relative" }}>
      <Navbar avatarInitials={getInitials(userProfile?.name ?? "")} />
      <main style={{ padding: "24px" }}>
        {pageError && (
          <div role="alert" style={styles.pageError}>
            {pageError}
          </div>
        )}

        <div style={styles.header}>
          <div>
            {isLoadingPage ? (
              <Loader2 className="animate-spin" size={18} aria-label="Loading organizations" />
            ) : organizations.length > 0 ? (
              <div style={styles.dropdownContainer}>
                <label htmlFor="organization" className="sr-only">
                  Organization
                </label>
                <select
                  id="organization"
                  value={currentOrgId ?? ""}
                  onChange={(event) => setCurrentOrgId(Number(event.target.value))}
                  style={styles.orgSelect}
                >
                  {organizations.map((organization) => (
                    <option key={organization.id} value={organization.id}>
                      {organization.name}
                    </option>
                  ))}
                </select>
                <ChevronDown size={14} aria-hidden="true" style={styles.dropdownIcon} />
              </div>
            ) : (
              <h1 style={{ fontSize: "18px", fontWeight: 500, margin: 0 }}>
                Create your first organization
              </h1>
            )}
            <p style={styles.subtitle}>Manage locations, documents, and users</p>
          </div>

          <div style={styles.actions}>
            <div className="group" style={{ display: "inline-block", position: "relative" }}>
              <button
                type="button"
                className="btn"
                onClick={() => setIsOrgModalOpen(true)}
                disabled={isOrgLimitReached || isLoadingPage}
                title={isOrgLimitReached ? "Your plan organization limit has been reached." : undefined}
              >
                <Plus size={14} aria-hidden="true" /> New organization
              </button>
            </div>
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => setIsBizModalOpen(true)}
              disabled={!currentOrgId || isBizLimitReached || isLoadingPage}
              title={
                isBizLimitReached
                  ? "Your plan business limit has been reached."
                  : !currentOrgId
                    ? "Create an organization first."
                    : undefined
              }
            >
              <Plus size={14} aria-hidden="true" /> New business
            </button>
          </div>
        </div>

        {isLoadingBusinesses ? (
          <div style={styles.loadingArea} role="status">
            <Loader2 className="animate-spin" size={18} aria-hidden="true" />
            Loading businesses…
          </div>
        ) : filteredBusinesses.length === 0 ? (
          <div style={styles.emptyState}>
            <Building2 size={28} aria-hidden="true" />
            <p style={{ margin: 0 }}>
              {currentOrganization
                ? `${currentOrganization.name} does not have any businesses yet.`
                : "Create an organization, then add its first business."}
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3" style={{ marginBottom: "20px" }}>
            {filteredBusinesses.map((business) => {
              const businessMetrics = metricsData?.businesses.find(
                (metric) => metric.id === business.id,
              );
              const used = businessMetrics?.usage ?? 0;
              const allocated = businessMetrics?.allocation ?? 25;
              const usagePercent = percent(used, allocated);

              return (
                <article className="card" key={business.id}>
                  <div style={styles.cardHeader}>
                    <div style={styles.businessName}>
                      <Building2 size={14} aria-hidden="true" style={{ flexShrink: 0 }} />
                      {business.name}
                    </div>
                    <span className="badge badge-success">Active</span>
                  </div>
                  <div style={{ margin: "12px 0 6px" }}>
                    <div style={styles.allocationLabel}>
                      <span>Branch allocation</span>
                      <span>{used} / {allocated} queries</span>
                    </div>
                    <div className="progress-bar">
                      <div
                        className="progress-fill"
                        style={{
                          background: usagePercent > 85 ? "var(--color-text-danger)" : undefined,
                          width: `${usagePercent}%`,
                        }}
                      />
                    </div>
                  </div>
                  <div className="mt-3 flex gap-2">
                    <button type="button" className="btn btn-primary flex-1 justify-center" onClick={() => openSearch(business)}>
                      Open search
                    </button>
                    <button type="button" className="btn flex-1 justify-center" onClick={() => manageBusiness(business)}>
                      Manage
                    </button>
                  </div>
                </article>
              );
            })}
          </div>
        )}

        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          {metricsData?.is_owner ? (
            <MetricCard
              label="Account usage this month"
              value={metricsData.total_combined_usage}
              subtext={`${metricsData.total_combined_usage} / ${metricsData.max_queries_allowed} total queries · ${plan.toUpperCase()} plan`}
              progressPercentage={percent(metricsData.total_combined_usage, metricsData.max_queries_allowed)}
            />
          ) : (
            <MetricCard
              label="Your searches this month"
              value={metricsData?.personal_user_usage ?? 0}
              subtext="Queries executed by your account"
            />
          )}
          <MetricCard
            label="Active businesses"
            value={filteredBusinesses.length}
            subtext={`${filteredBusinesses.length} / ${maxBusinessesAllowed} allowed`}
          />
        </div>
      </main>

      {isBizModalOpen && (
        <div style={styles.modalOverlay} role="presentation">
          <div role="dialog" aria-modal="true" aria-labelledby="business-modal-title" style={styles.modalContent}>
            <div style={styles.modalHeader}>
              <h2 id="business-modal-title" style={styles.modalTitle}>Create new business</h2>
              <button type="button" aria-label="Close" onClick={() => { setIsBizModalOpen(false); setBizError(null); }} style={styles.closeButton}>
                <X size={16} aria-hidden="true" />
              </button>
            </div>
            <form onSubmit={handleCreateBusiness} style={styles.modalForm}>
              <label htmlFor="business-organization" style={styles.label}>Organization</label>
              <select
                id="business-organization"
                value={currentOrgId ?? ""}
                onChange={(event) => setCurrentOrgId(Number(event.target.value))}
                disabled={isCreatingBiz}
                style={styles.modalInput}
              >
                {organizations.map((organization) => (
                  <option key={organization.id} value={organization.id}>{organization.name}</option>
                ))}
              </select>
              <label htmlFor="business-name" style={styles.label}>Business name</label>
              <input
                id="business-name"
                type="text"
                value={bizName}
                onChange={(event) => setBizName(event.target.value)}
                maxLength={120}
                required
                autoFocus
                disabled={isCreatingBiz}
                style={styles.modalInput}
              />
              {bizError && <ErrorAlert message={bizError} />}
              <div style={styles.modalActions}>
                <button type="button" className="btn" onClick={() => { setIsBizModalOpen(false); setBizError(null); }} disabled={isCreatingBiz}>Cancel</button>
                <button type="submit" className="btn btn-primary" disabled={isCreatingBiz || !bizName.trim()}>
                  {isCreatingBiz && <Loader2 className="animate-spin" size={14} aria-hidden="true" />}
                  {isCreatingBiz ? "Creating…" : "Create business"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {isOrgModalOpen && (
        <div style={styles.modalOverlay} role="presentation">
          <div role="dialog" aria-modal="true" aria-labelledby="organization-modal-title" style={styles.modalContent}>
            <div style={styles.modalHeader}>
              <h2 id="organization-modal-title" style={styles.modalTitle}>Create new organization</h2>
              <button type="button" aria-label="Close" onClick={() => { setIsOrgModalOpen(false); setOrgError(null); }} style={styles.closeButton}>
                <X size={16} aria-hidden="true" />
              </button>
            </div>
            <form onSubmit={handleCreateOrganization} style={styles.modalForm}>
              <label htmlFor="organization-name" style={styles.label}>Organization name</label>
              <input
                id="organization-name"
                type="text"
                value={orgName}
                onChange={(event) => setOrgName(event.target.value)}
                maxLength={120}
                required
                autoFocus
                disabled={isCreatingOrg}
                style={styles.modalInput}
              />
              {orgError && <ErrorAlert message={orgError} />}
              <div style={styles.modalActions}>
                <button type="button" className="btn" onClick={() => { setIsOrgModalOpen(false); setOrgError(null); }} disabled={isCreatingOrg}>Cancel</button>
                <button type="submit" className="btn btn-primary" disabled={isCreatingOrg || !orgName.trim()}>
                  {isCreatingOrg && <Loader2 className="animate-spin" size={14} aria-hidden="true" />}
                  {isCreatingOrg ? "Creating…" : "Create organization"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

function ErrorAlert({ message }: { message: string }) {
  return (
    <div role="alert" style={styles.errorAlert}>
      <ShieldAlert size={14} aria-hidden="true" style={{ flexShrink: 0 }} />
      <span>{message}</span>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  pageError: { background: "var(--color-background-danger)", border: "1px solid var(--color-border-danger)", borderRadius: "6px", color: "var(--color-text-danger)", fontSize: "13px", marginBottom: "16px", padding: "10px 12px" },
  header: { alignItems: "center", display: "flex", flexWrap: "wrap", gap: "12px", justifyContent: "space-between", marginBottom: "20px" },
  dropdownContainer: { alignItems: "center", display: "flex", position: "relative" },
  orgSelect: { appearance: "none", background: "transparent", border: "none", color: "var(--color-text-primary)", cursor: "pointer", fontSize: "18px", fontWeight: 500, outline: "none", paddingRight: "22px" },
  dropdownIcon: { color: "var(--color-text-secondary)", pointerEvents: "none", position: "absolute", right: 0 },
  subtitle: { color: "var(--color-text-secondary)", fontSize: "13px", margin: "4px 0 0" },
  actions: { display: "flex", flexWrap: "wrap", gap: "8px" },
  loadingArea: { alignItems: "center", display: "flex", gap: "8px", height: "160px", justifyContent: "center" },
  emptyState: { alignItems: "center", border: "1px dashed var(--color-border-tertiary)", borderRadius: "var(--border-radius-lg)", color: "var(--color-text-secondary)", display: "flex", flexDirection: "column", gap: "10px", marginBottom: "20px", padding: "36px", textAlign: "center" },
  cardHeader: { alignItems: "center", display: "flex", justifyContent: "space-between", marginBottom: "10px" },
  businessName: { alignItems: "center", display: "flex", fontSize: "14px", fontWeight: 500, gap: "6px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" },
  allocationLabel: { color: "var(--color-text-secondary)", display: "flex", fontSize: "11px", justifyContent: "space-between", marginBottom: "4px" },
  modalOverlay: { alignItems: "center", backdropFilter: "blur(2px)", backgroundColor: "rgba(0,0,0,0.4)", display: "flex", height: "100vh", justifyContent: "center", left: 0, padding: "16px", position: "fixed", top: 0, width: "100vw", zIndex: 2000 },
  modalContent: { background: "var(--color-background-primary)", border: "1px solid var(--color-border-tertiary)", borderRadius: "12px", boxShadow: "0 20px 25px -5px rgba(0,0,0,0.1)", display: "flex", flexDirection: "column", maxWidth: "400px", width: "100%" },
  modalHeader: { alignItems: "center", borderBottom: "1px solid var(--color-border-tertiary)", display: "flex", justifyContent: "space-between", padding: "16px" },
  modalTitle: { fontSize: "15px", fontWeight: 600, margin: 0 },
  closeButton: { alignItems: "center", background: "none", border: "none", color: "var(--color-text-secondary)", cursor: "pointer", display: "flex", padding: "4px" },
  modalForm: { display: "flex", flexDirection: "column", gap: "10px", padding: "16px" },
  label: { color: "var(--color-text-secondary)", fontSize: "11px", fontWeight: 600, textTransform: "uppercase" },
  modalInput: { background: "transparent", border: "1px solid var(--color-border-tertiary)", borderRadius: "6px", color: "var(--color-text-primary)", fontSize: "13px", outline: "none", padding: "8px 12px", width: "100%" },
  modalActions: { display: "flex", gap: "8px", justifyContent: "flex-end", marginTop: "8px" },
  errorAlert: { alignItems: "flex-start", backgroundColor: "var(--color-background-danger)", border: "1px solid var(--color-border-danger)", borderRadius: "6px", color: "var(--color-text-danger)", display: "flex", fontSize: "12px", gap: "8px", padding: "10px 12px" },
};
