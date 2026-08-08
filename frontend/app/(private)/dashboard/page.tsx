'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import { Plus, Users, File, Loader2, Building2, Upload, X, Trash2, ShieldAlert, ChevronDown } from 'lucide-react';
import Navbar from '@/components/Navbar';
import MetricCard from '@/components/MetricCard';
import { useRouter } from 'next/navigation';
import { useBusiness } from '@/app/context/BusinessContext';

const ACCEPTED_TYPES = ".pdf,.txt,.md,.docx,.csv,.xlsx,.xls";

const badgeColor: Record<string, { bg: string; color: string }> = {
  PDF: { bg: '#fee2e2', color: '#ef4444' },
  TXT: { bg: '#fef3c7', color: '#d97706' },
  MD: { bg: '#e0f2fe', color: '#0284c7' },
  DOCX: { bg: '#e0e7ff', color: '#4f46e5' },
  CSV: { bg: '#dcfce7', color: '#16a34a' },
  XLSX: { bg: '#f3e8ff', color: '#9333ea' },
  XLS: { bg: '#f3e8ff', color: '#9333ea' },
};

interface Doc {
  id: string;
  backendId?: string;
  name: string;
  type: string;
  status: "processing" | "ready" | "failed";
}

interface Org {
  id: number;
  name: string;
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

export default function AdminDashboard() {
  const router = useRouter();
  const { businesses, selectBusiness, isLoading, refreshBusinesses } = useBusiness();

  const [organizations, setOrganizations] = useState<Org[]>([]);
  const [currentOrgId, setCurrentOrgId] = useState<number | null>(null);
  const [isLoadingOrgs, setIsLoadingOrgs] = useState(true);

  const [userProfile, setUserProfile] = useState<UserProfile | null>(null);
  const [isOrgModalOpen, setIsOrgModalOpen] = useState(false);
  const [orgName, setOrgName] = useState("");
  const [isCreatingOrg, setIsCreatingOrg] = useState(false);
  const [orgError, setOrgError] = useState<string | null>(null);

  const [isMounted, setIsMounted] = useState(false);

  const [isBizModalOpen, setIsBizModalOpen] = useState(false);
  const [bizName, setBizName] = useState("");
  const [isCreatingBiz, setIsCreatingBiz] = useState(false);
  const [bizError, setBizError] = useState<string | null>(null);

  const [metricsData, setMetricsData] = useState<WorkspaceMetrics | null>(null);
  const [isLoadingMetrics, setIsLoadingMetrics] = useState(false);

  // Fetch granular metrics whenever the user switches organizations
  useEffect(() => {
    if (!currentOrgId) return;

    const fetchWorkspaceMetrics = async () => {
      setIsLoadingMetrics(true);
      try {
        const res = await fetch(`http://localhost:8000/auth/usage-metrics?org_id=${currentOrgId}`, {
          method: "GET",
          credentials: "include",
        });
        if (res.ok) {
          const data = await res.json();
          setMetricsData(data);
        }
      } catch (err) {
        console.error("Failed to fetch location usage bounds:", err);
      } finally {
        setIsLoadingMetrics(false);
      }
    };

    fetchWorkspaceMetrics();
  }, [currentOrgId]);

  useEffect(() => {
    const fetchUserDataAndWorkspaces = async () => {
      try {
        const userRes = await fetch("http://localhost:8000/auth/me", {
          method: "GET",
          credentials: "include",
        });
        if (userRes.ok) {
          const userData = await userRes.json();
          setUserProfile(userData);
        }

        const orgRes = await fetch("http://localhost:8000/organizations", {
          method: "GET",
          credentials: "include",
        });
        if (!orgRes.ok) throw new Error();
        const orgData = await orgRes.json();
        setOrganizations(orgData);
        if (orgData.length > 0) {
          setCurrentOrgId(orgData[0].id);
        }
      } catch (err) {
        console.error("Failed to retrieve organizational framework snapshot", err);
      } finally {
        setIsLoadingOrgs(false);
      }
    };

    fetchUserDataAndWorkspaces();
    setIsMounted(true);
  }, []);

  const activeOrg = organizations.find(o => o.id === currentOrgId);
  const userPlanKey = userProfile?.plan?.toLowerCase() || 'free';

  const maxOrganizationsAllowed = userProfile?.max_organizations ?? 1;
  const isOrgLimitReached = organizations.length >= maxOrganizationsAllowed;

  const maxBusinessesAllowed = userProfile?.max_businesses ?? 1;
  const filteredBusinesses = businesses.filter(
    b => b.org_id?.toString() === currentOrgId?.toString()
  );
  const isBizLimitReached = filteredBusinesses.length >= maxBusinessesAllowed;

  const handleCreateOrganization = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!orgName.trim() || isOrgLimitReached) return;
    setIsCreatingOrg(true);
    setOrgError(null);
    try {
      const res = await fetch("http://localhost:8000/organizations", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: orgName }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Could not instantiate an organization.");
      setOrganizations(prev => [...prev, data]);
      setCurrentOrgId(data.id);
      setIsOrgModalOpen(false);
      setOrgName("");
    } catch (err: any) {
      setOrgError(err.message || "An unhandled server anomaly occurred.");
    } finally {
      setIsCreatingOrg(false);
    }
  };

  const handleCreateBusiness = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!bizName.trim() || !currentOrgId || isBizLimitReached) return;

    setIsCreatingBiz(true);
    setBizError(null);

    try {
      const res = await fetch("http://localhost:8000/businesses", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: bizName,
          org_id: currentOrgId
        }),
      });

      const data = await res.json();

      if (!res.ok) {
        throw new Error(data.detail || "Could not spin up a new business asset.");
      }

      if (refreshBusinesses && currentOrgId) {
        await refreshBusinesses([currentOrgId]);
      } else {
        window.location.reload();
      }

      setIsBizModalOpen(false);
      setBizName("");
    } catch (err: any) {
      setBizError(err.message || "An error occurred while creating the business.");
    } finally {
      setIsCreatingBiz(false);
    }
  };

  const handleManageBusinessRedirect = (biz: any) => {
    selectBusiness(biz);
    if (currentOrgId) {
      router.push(`/businesses?orgId=${currentOrgId}&bizId=${biz.id}`);
    } else {
      router.push(`/businesses?orgId=${biz.org_id}&bizId=${biz.id}`);
    }
  };

  return (
    <div className="screen" style={{ position: 'relative', overflowX: 'hidden' }}>
      <Navbar />
      <div style={{ padding: '24px' }}>

        {/* Title & Action Buttons Header */}
        <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', marginBottom: '20px', justifyContent: 'space-between', gap: '12px' }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', position: 'relative' }}>
              {isLoadingOrgs ? (
                <div style={{ height: '24px', display: 'flex', alignItems: 'center' }}>
                  <Loader2 className="animate-spin" size={14} style={{ color: 'var(--color-text-secondary)' }} />
                </div>
              ) : (
                <div style={s.dropdownContainer}>
                  <select
                    value={currentOrgId ?? ""}
                    onChange={(e) => {
                      const newOrgId = Number(e.target.value);
                      setCurrentOrgId(newOrgId);

                      const alreadyLoaded = businesses.some(b => b.org_id === newOrgId);
                      if (!alreadyLoaded && refreshBusinesses) {
                        refreshBusinesses([newOrgId]);
                      }
                    }}
                    style={s.orgSelect}
                  >
                    {organizations.map(org => (
                      <option key={org.id} value={org.id}>{org.name}</option>
                    ))}
                  </select>
                  <ChevronDown size={14} style={s.dropdownIcon} />
                </div>
              )}
            </div>
            <div style={{ fontSize: '13px', color: 'var(--color-text-secondary)', marginTop: '4px' }}>
              Manage locations, documents, and users
            </div>
          </div>

          <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
            {/* New Org Button */}
            <div style={{ position: 'relative', display: 'inline-block' }} className="group">
              <button
                className="btn btn-secondary"
                onClick={() => setIsOrgModalOpen(true)}
                disabled={isOrgLimitReached}
                style={{
                  fontSize: '13px',
                  opacity: isOrgLimitReached ? 0.5 : 1,
                  cursor: isOrgLimitReached ? 'not-allowed' : 'pointer'
                }}
              >
                <Plus size={14} /> New organization
              </button>

              {isOrgLimitReached && (
                <div className="group-hover:block hidden" style={s.tooltip}>
                  Your current account profile tier ({userPlanKey.toUpperCase()}) is restricted to {maxOrganizationsAllowed} organization workspace.
                  <div style={s.tooltipArrow} />
                </div>
              )}
            </div>

            {/* New Business Button */}
            <div style={{ position: 'relative', display: 'inline-block' }} className="group">
              <button
                className="btn btn-primary"
                style={{
                  fontSize: '13px',
                  opacity: (isMounted ? !currentOrgId : false) || isBizLimitReached ? 0.5 : 1,
                  cursor: (isMounted ? !currentOrgId : false) || isBizLimitReached ? 'not-allowed' : 'pointer'
                }}
                onClick={() => setIsBizModalOpen(true)}
                disabled={(isMounted ? !currentOrgId : false) || isBizLimitReached}
              >
                <Plus size={14} /> New business
              </button>

              {isBizLimitReached && (
                <div className="group-hover:block hidden" style={s.tooltip}>
                  Your current account profile tier ({userPlanKey.toUpperCase()}) is restricted to {maxBusinessesAllowed} connected database {maxBusinessesAllowed === 1 ? 'workspace' : 'workspaces'}.
                  <div style={s.tooltipArrow} />
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Workspace Grid Cards (Fixed 3-Column Layout) */}
        {isLoading ? (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '160px' }}>
            <Loader2 className="animate-spin" size={18} />
          </div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '12px', marginBottom: '20px' }}>
            {filteredBusinesses.map((biz) => {
              const match = metricsData?.businesses?.find((b: any) => b.id === biz.id);
              const bizUsage = match?.usage ?? 0;
              const bizAlloc = match?.allocation ?? 25;
              const bizPercent = Math.min(Math.round((bizUsage / bizAlloc) * 100), 100);

              return (
                <div className="card" key={biz.id}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '10px' }}>
                    <div style={{ fontSize: '14px', fontWeight: 500, display: 'flex', alignItems: 'center', gap: '6px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      <Building2 size={14} style={{ color: 'var(--color-text-secondary)', flexShrink: 0 }} />
                      {biz.name}
                    </div>
                    <span className="badge badge-success">Active</span>
                  </div>

                  {/* Allocation Progress Bar */}
                  <div style={{ margin: '12px 0 6px 0' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', color: 'var(--color-text-secondary)', marginBottom: '4px' }}>
                      <span>Branch Allocation</span>
                      <span>{bizUsage} / {bizAlloc} queries</span>
                    </div>
                    <div style={{ width: '100%', height: '6px', background: 'var(--color-background-secondary, #e4e4e7)', borderRadius: '3px', overflow: 'hidden' }}>
                      <div
                        style={{
                          width: `${bizPercent}%`,
                          height: '100%',
                          background: bizPercent > 85 ? '#ef4444' : 'var(--color-primary, #4f46e5)',
                          transition: 'width 0.3s ease'
                        }}
                      />
                    </div>
                  </div>

                  {/* Action Buttons Layout */}
                  <div style={{ display: 'flex', flexDirection: 'row', gap: '6px', marginTop: '12px' }}>
                    <button
                      className="btn btn-primary"
                      style={{ width: '100%', justifyContent: 'center', fontSize: '13px' }}
                      onClick={() => {
                        selectBusiness(biz);
                        const orgIdToUse = currentOrgId || biz.org_id;
                        router.push(`/search?orgId=${orgIdToUse}&bizId=${biz.id}`);
                      }}
                    >
                      Open Search
                    </button>

                    <button
                      className="btn btn-secondary"
                      style={{
                        width: '100%',
                        justifyContent: 'center',
                        fontSize: '12px',
                        borderStyle: 'dashed'
                      }}
                      onClick={() => handleManageBusinessRedirect(biz)}
                    >
                      Manage Business
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* Global Performance Metrics (Fixed 3-Column Layout) */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '12px' }}>
          {metricsData?.is_owner ? (
            <MetricCard
              label="Account usage this month"
              value={String(metricsData.total_combined_usage)}
              subtext={`${metricsData.total_combined_usage} / ${metricsData.max_queries_allowed} total pool queries · ${userPlanKey.toUpperCase()} plan`}
              progressPercentage={Math.min(Math.round((metricsData.total_combined_usage / metricsData.max_queries_allowed) * 100), 100)}
            />
          ) : (
            <MetricCard
              label="Your searches this month"
              value={String(metricsData?.personal_user_usage ?? 0)}
              subtext="Queries executed by your personal seat profile"
            />
          )}

          <MetricCard
            label="Total active instances"
            value={String(filteredBusinesses.length)}
            subtext={`Connected locations (${filteredBusinesses.length} / ${maxBusinessesAllowed})`}
          />
        </div>
      </div>

      {/* ── BUSINESS INLINE MODAL WINDOW ── */}
      {isBizModalOpen && (
        <div style={s.modalOverlay}>
          <div style={s.modalContent}>
            <div style={s.modalHeader}>
              <div style={{ fontSize: '15px', fontWeight: 600 }}>
                Create New Business
              </div>
              <button onClick={() => { setIsBizModalOpen(false); setBizError(null); }} style={s.closeBtn}>
                <X size={16} />
              </button>
            </div>

            <form onSubmit={handleCreateBusiness} style={{ padding: '16px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <div>
                <label style={{ fontSize: '11px', fontWeight: 600, color: 'var(--color-text-secondary)', display: 'block', marginBottom: '4px' }}>
                  ASSIGN TO ORGANIZATION
                </label>
                <div style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
                  <select
                    value={currentOrgId ?? ""}
                    onChange={(e) => setCurrentOrgId(Number(e.target.value))}
                    disabled={isCreatingBiz}
                    style={{
                      ...s.modalInput,
                      marginTop: 0,
                      appearance: 'none',
                      WebkitAppearance: 'none',
                      paddingRight: '28px',
                      backgroundColor: 'var(--color-background-secondary, #f4f4f5)',
                      cursor: isCreatingBiz ? 'not-allowed' : 'pointer'
                    }}
                  >
                    {organizations.map(org => (
                      <option key={org.id} value={org.id}>{org.name}</option>
                    ))}
                  </select>
                  <ChevronDown size={14} style={{ position: 'absolute', right: '10px', pointerEvents: 'none', color: 'var(--color-text-secondary)' }} />
                </div>
              </div>

              <div>
                <label style={{ fontSize: '11px', fontWeight: 600, color: 'var(--color-text-secondary)', display: 'block', marginBottom: '4px' }}>
                  BUSINESS LOCATION NAME
                </label>
                <input
                  type="text"
                  value={bizName}
                  onChange={(e) => setBizName(e.target.value)}
                  placeholder="e.g. Downtown Branch"
                  required
                  autoFocus
                  disabled={isCreatingBiz}
                  style={s.modalInput}
                />
              </div>

              {bizError && (
                <div style={s.errorAlert}>
                  <ShieldAlert size={14} style={{ flexShrink: 0, marginTop: '1px' }} />
                  <span style={{ fontSize: '11px', lineHeight: '1.4' }}>{bizError}</span>
                </div>
              )}

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px', marginTop: '8px' }}>
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => { setIsBizModalOpen(false); setBizError(null); }}
                  disabled={isCreatingBiz}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="btn btn-primary"
                  disabled={isCreatingBiz || !bizName.trim()}
                >
                  {isCreatingBiz ? <Loader2 className="animate-spin" size={14} /> : "Create Business"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ── ORGANIZATION CREATION POPUP WINDOW ── */}
      {isOrgModalOpen && (
        <div style={s.modalOverlay}>
          <div style={s.modalContent}>
            <div style={s.modalHeader}>
              <div style={{ fontSize: '15px', fontWeight: 600 }}>Create New Organization</div>
              <button onClick={() => { setIsOrgModalOpen(false); setOrgError(null); }} style={s.closeBtn}>
                <X size={16} />
              </button>
            </div>
            <form onSubmit={handleCreateOrganization} style={{ padding: '16px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <div>
                <label style={{ fontSize: '11px', fontWeight: 600, color: 'var(--color-text-secondary)', display: 'block', marginBottom: '4px' }}>
                  ORGANIZATION WORKSPACE NAME
                </label>
                <input
                  type="text"
                  value={orgName}
                  onChange={(e) => setOrgName(e.target.value)}
                  placeholder="e.g. Acme Holdings LLC"
                  required
                  disabled={isCreatingOrg}
                  style={s.modalInput}
                />
              </div>
              {orgError && (
                <div style={s.errorAlert}>
                  <ShieldAlert size={14} style={{ flexShrink: 0, marginTop: '1px' }} />
                  <span style={{ fontSize: '11px', lineHeight: '1.4' }}>{orgError}</span>
                </div>
              )}
              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px', marginTop: '8px' }}>
                <button type="button" className="btn btn-secondary" onClick={() => { setIsOrgModalOpen(false); setOrgError(null); }} disabled={isCreatingOrg}>Cancel</button>
                <button type="submit" className="btn btn-primary" disabled={isCreatingOrg || !orgName.trim()}>
                  {isCreatingOrg ? <Loader2 className="animate-spin" size={14} /> : "Create Workspace"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

const s: Record<string, React.CSSProperties> = {
  dropdownContainer: { position: 'relative', display: 'flex', alignItems: 'center' },
  orgSelect: { fontSize: '18px', fontWeight: 500, background: 'transparent', border: 'none', color: 'var(--color-text-primary, #18181b)', cursor: 'pointer', outline: 'none', paddingRight: '20px', appearance: 'none', WebkitAppearance: 'none' },
  dropdownIcon: { position: 'absolute', right: 0, pointerEvents: 'none', color: 'var(--color-text-secondary, #71717a)' },
  modalOverlay: { position: 'fixed', top: 0, left: 0, width: '100vw', height: '100vh', backgroundColor: 'rgba(0, 0, 0, 0.4)', backdropFilter: 'blur(2px)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 2000, padding: '16px' },
  modalContent: { background: 'var(--color-background-primary, #ffffff)', border: '1px solid var(--color-border-tertiary, #e4e4e7)', borderRadius: '12px', width: '100%', maxWidth: '400px', boxShadow: '0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04)', display: 'flex', flexDirection: 'column' },
  modalHeader: { padding: '16px', borderBottom: '1px solid var(--color-border-tertiary, #e4e4e7)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' },
  modalInput: { width: '100%', padding: '8px 12px', fontSize: '13px', borderRadius: '6px', border: '1px solid var(--color-border-tertiary, #e4e4e7)', background: 'transparent', color: 'var(--color-text-primary, #18181b)', outline: 'none', marginTop: '4px' },
  errorAlert: { display: 'flex', gap: '8px', alignItems: 'flex-start', padding: '10px 12px', borderRadius: '6px', backgroundColor: '#fef2f2', border: '1px solid #fee2e2', color: '#ef4444' },
  closeBtn: { background: 'none', border: 'none', color: 'var(--color-text-secondary, #71717a)', cursor: 'pointer', padding: '4px', display: 'flex', alignItems: 'center' },
  tooltip: {
    position: 'absolute',
    bottom: '135%',
    right: '0',
    backgroundColor: '#1f2937',
    color: '#ffffff',
    fontSize: '11px',
    lineHeight: '1.4',
    padding: '8px 12px',
    borderRadius: '6px',
    width: '220px',
    textAlign: 'center',
    boxShadow: '0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06)',
    zIndex: 3000,
    pointerEvents: 'none',
    display: 'none'
  },
  tooltipArrow: { position: 'absolute', top: '100%', left: '50%', transform: 'translateX(-50%)', borderWidth: '5px', borderStyle: 'solid', borderColor: '#1f2937 transparent transparent transparent' },
};