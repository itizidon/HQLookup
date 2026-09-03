'use client';

import { useState, useEffect, useMemo, ChangeEvent } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { 
  ArrowLeft, Search, Upload, Trash2, FileText, UserPlus, 
  ChevronsUpDown, Building2, Loader2, ShieldAlert, Sliders, 
  Users, ChevronDown, ChevronRight, Sparkles, FileSpreadsheet, X 
} from 'lucide-react';
import { useBusiness, type Business } from '@/app/context/BusinessContext';
import { apiFetch, errorMessage, responseErrorMessage } from '@/app/lib/api';

interface ServerDocument {
  id: string | number;
  name: string;
  type: string;
  business_id: number;
}

interface MemberRecord {
  id: string | number;
  email: string;
  role: string;
  status?: string;
  is_root?: boolean;
  created_at?: string;
}

interface TeamMember {
  id: string | number;
  email: string;
  role: string;
  is_root: boolean;
}

interface PendingInvitation {
  id: string | number;
  email: string;
  role: string;
  created_at: string;
}

interface UploadedDocument {
  document_id?: string | number;
  filename: string;
  error?: string;
}

type ActiveTab = 'files' | 'settings' | 'team';
const MAX_INGESTION_NOTES_LENGTH = 4000;

const tabs: Array<{ id: ActiveTab; label: string; icon: React.ReactNode }> = [
  { id: 'files', label: 'Knowledge Base', icon: <FileText size={14} /> },
  { id: 'settings', label: 'Usage Limits', icon: <Sliders size={14} /> },
  { id: 'team', label: 'Access Control', icon: <Users size={14} /> },
];

interface BusinessDetails {
  id: number;
  name: string;
  org_id: number;
  query_allocation: number;
}

interface PendingFile {
  file: File;
  id: string;
  isExcel: boolean;
  context: string;
  isExpanded: boolean;
}

export default function EnterpriseBusinessDetail() {
  // Pulling context sources to read the central business directory list
  const { businesses, isLoading: contextLoading, selectBusiness } = useBusiness();
  const router = useRouter();
  const searchParams = useSearchParams();

  // ── THE ABSOLUTE SOURCES OF TRUTH (URL Parameters) ──
  const urlBizId = searchParams.get('bizId');
  const urlOrgId = searchParams.get('orgId');

  const activeBizId = urlBizId ? Number(urlBizId) : null;
  const activeOrgId = urlOrgId ? Number(urlOrgId) : null;

  // ── LOCAL STATE MATRICES ──
  const [activeTab, setActiveTab] = useState<ActiveTab>('files');

  // Interactive UI / Search Filter States
  const [searchQuery, setSearchQuery] = useState('');
  const [isDropdownOpen, setIsDropdownOpen] = useState(false);
  const [documents, setDocuments] = useState<ServerDocument[]>([]);
  const [docsLoading, setDocsLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  
  // Pending File Staging State for XLSX Context Injection
  const [pendingFiles, setPendingFiles] = useState<PendingFile[]>([]);

  // Settings Allocation Form States
  const [allocationDraft, setAllocationDraft] = useState<{ businessId: number; value: number } | null>(null);
  const [isSavingSettings, setIsSavingSettings] = useState(false);
  const [settingsError, setSettingsError] = useState<string | null>(null);

  // Inline Single Invite Form States
  const [inviteEmail, setInviteEmail] = useState('');
  const [isSendingInvite, setIsSendingInvite] = useState(false);
  const [inviteStatus, setInviteStatus] = useState<{ type: 'success' | 'error'; message: string } | null>(null);

  // Access Control Repositories
  const [teamLoading, setTeamLoading] = useState(false);
  const [allMembers, setAllMembers] = useState<MemberRecord[]>([]);

  const businessDetails = useMemo<BusinessDetails | null>(() => {
    if (!activeBizId || !activeOrgId) return null;

    const matched = businesses.find(
      (business) => business.id === activeBizId && business.org_id === activeOrgId,
    );
    if (!matched) return null;

    return {
      id: matched.id,
      name: matched.name,
      org_id: matched.org_id,
      query_allocation: matched.query_allocation ?? 25,
    };
  }, [activeBizId, activeOrgId, businesses]);

  const localAlloc = allocationDraft && allocationDraft.businessId === businessDetails?.id
    ? allocationDraft.value
    : businessDetails?.query_allocation ?? 25;

  // Split unified members payload cleanly into active/pending structures on the fly
  const { teamMembers, pendingInvites } = useMemo(() => {
    const active: TeamMember[] = [];
    const pending: PendingInvitation[] = [];

    allMembers.forEach((m) => {
      if (m.status === 'pending') {
        pending.push({
          id: m.id,
          email: m.email,
          role: m.role,
          created_at: m.created_at || new Date().toISOString()
        });
      } else {
        active.push({
          id: m.id,
          email: m.email,
          role: m.role,
          is_root: Boolean(m.is_root)
        });
      }
    });

    return { teamMembers: active, pendingInvites: pending };
  }, [allMembers]);

  // Memoized client-side filter for the picker dropdown selector
  const filteredBusinesses = useMemo(() => {
    if (!searchQuery) return businesses;
    return businesses.filter((biz) =>
      biz.name.toLowerCase().includes(searchQuery.toLowerCase())
    );
  }, [searchQuery, businesses]);

  // ── REFRESH-PROOF PIPELINE ──
  useEffect(() => {
    if (!businessDetails) return;

    const controller = new AbortController();
    const businessId = businessDetails.id;
    const organizationId = businessDetails.org_id;

    const fetchDocs = async () => {
      setDocsLoading(true);
      setDocuments([]);
      try {
        const res = await apiFetch("/documents", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          signal: controller.signal,
          body: JSON.stringify({
            business_ids: [businessId],
            page: 1,
            page_size: 50
          })
        });
        const data = await res.json() as { documents?: ServerDocument[] };
        if (data.documents) {
          setDocuments(data.documents);
        }
      } catch (err) {
        if (!controller.signal.aborted) {
          console.error("Error retrieving documents:", err);
        }
      } finally {
        if (!controller.signal.aborted) setDocsLoading(false);
      }
    };

    const fetchTeamAndInvites = async () => {
      setTeamLoading(true);
      setAllMembers([]);
      try {
        const res = await apiFetch(
          `/organizations/${organizationId}/businesses/${businessId}/members`,
          { signal: controller.signal },
        );

        if (res.ok) {
          const data = await res.json() as { members?: MemberRecord[] };
          setAllMembers(data.members || []);
        }
      } catch (err) {
        if (!controller.signal.aborted) {
          console.error("Error retrieving unified access control data list:", err);
        }
      } finally {
        if (!controller.signal.aborted) setTeamLoading(false);
      }
    };

    fetchDocs();
    fetchTeamAndInvites();
    return () => controller.abort();
  }, [businessDetails]);

  const handleSelectBusiness = (biz: Business) => {
    selectBusiness(biz);
    setAllocationDraft(null);
    setSettingsError(null);
    setInviteEmail('');
    setInviteStatus(null);
    const params = new URLSearchParams(searchParams.toString());
    params.set('orgId', biz.org_id.toString());
    params.set('bizId', biz.id.toString());
    router.push(`${window.location.pathname}?${params.toString()}`);
  };

  // Stage files into pending list when picked from disk
  const handleFileSelection = (e: ChangeEvent<HTMLInputElement>) => {
    if (!e.target.files || e.target.files.length === 0) return;
    setUploadError(null);

    const newFiles: PendingFile[] = Array.from(e.target.files).map((f) => {
      const lowerName = f.name.toLowerCase();
      const isExcel = lowerName.endsWith('.xlsx') || lowerName.endsWith('.xlsm') || lowerName.endsWith('.xls');
      return {
        file: f,
        id: `${f.name}_${Date.now()}_${Math.random()}`,
        isExcel,
        context: '',
        isExpanded: isExcel // Auto-expand spreadsheets by default to invite optional notes
      };
    });

    setPendingFiles((prev) => [...prev, ...newFiles]);
    e.target.value = ''; // Reset input target
  };

  const removePendingFile = (id: string) => {
    setPendingFiles((prev) => prev.filter((f) => f.id !== id));
  };

  const toggleExpandPendingFile = (id: string) => {
    setPendingFiles((prev) =>
      prev.map((f) => (f.id === id ? { ...f, isExpanded: !f.isExpanded } : f))
    );
  };

  const updatePendingFileContext = (id: string, text: string) => {
    setPendingFiles((prev) =>
      prev.map((f) => (
        f.id === id
          ? { ...f, context: text.slice(0, MAX_INGESTION_NOTES_LENGTH) }
          : f
      ))
    );
  };

  const addPresetChip = (id: string, presetText: string) => {
    setPendingFiles((prev) =>
      prev.map((f) => {
        if (f.id !== id) return f;
        const current = f.context.trim();
        const updated = current ? `${current}; ${presetText}` : presetText;
        return {
          ...f,
          context: updated.slice(0, MAX_INGESTION_NOTES_LENGTH),
        };
      })
    );
  };

  // Execute actual upload API call with file contexts
  const handleStartUpload = async () => {
    if (pendingFiles.length === 0 || !businessDetails) return;

    const businessId = businessDetails.id;

    setUploading(true);
    setUploadError(null);
    const formData = new FormData();
    formData.append("business_id", businessId.toString());

    // Keep notes aligned with the repeated file fields, including duplicate names.
    pendingFiles.forEach((p) => {
      formData.append("files", p.file);
    });
    const contextsPayload = pendingFiles.map((p) => (
      p.isExcel ? p.context.trim() : ''
    ));

    formData.append("file_contexts", JSON.stringify(contextsPayload));

    try {
      const res = await apiFetch("/upload-multiple", {
        method: "POST",
        body: formData,
      });
      if (!res.ok) {
        throw new Error(await responseErrorMessage(res, "Could not upload documents."));
      }
      const data = await res.json() as { uploaded?: UploadedDocument[] };
      if (!data.uploaded) {
        throw new Error("The upload service returned an invalid response.");
      }

      const successfulUploads = data.uploaded.filter(
        (uploaded): uploaded is UploadedDocument & { document_id: string | number } => (
          uploaded.document_id !== undefined && !uploaded.error
        ),
      );
      const failedUploads = data.uploaded.filter((uploaded) => uploaded.error);
      const completedFileIds = new Set(
        data.uploaded.flatMap((uploaded, index) => (
          uploaded.document_id !== undefined && !uploaded.error && pendingFiles[index]
            ? [pendingFiles[index].id]
            : []
        )),
      );

      if (successfulUploads.length > 0) {
        const newDocs: ServerDocument[] = successfulUploads.map((uploaded) => ({
          id: uploaded.document_id.toString(),
          name: uploaded.filename,
          type: uploaded.filename.split('.').pop()?.toUpperCase() || 'UNKNOWN',
          business_id: businessId
        }));
        setDocuments((prev) => [...newDocs, ...prev]);
      }
      if (failedUploads.length > 0) {
        setUploadError(
          failedUploads
            .map((uploaded) => `${uploaded.filename}: ${uploaded.error}`)
            .join(' '),
        );
      }
      setPendingFiles((prev) => prev.filter((file) => !completedFileIds.has(file.id)));
    } catch (err) {
      console.error("Upload failure:", err);
      setUploadError(errorMessage(err, "An unhandled upload error occurred."));
    } finally {
      setUploading(false);
    }
  };

  const handleDeleteDoc = async (docId: string | number) => {
    if (!businessDetails) return;
    try {
      const res = await apiFetch(`/documents/${encodeURIComponent(String(docId))}?business_id=${businessDetails.id}`, {
        method: "DELETE",
      });
      if (res.ok) {
        setDocuments((prev) => prev.filter(d => d.id !== docId));
      }
    } catch (err) {
      console.error("Error purging target document record:", err);
    }
  };

  const handleSaveSettings = async () => {
    if (!businessDetails) return;
    setIsSavingSettings(true);
    setSettingsError(null);
    try {
      const res = await apiFetch("/businesses/settings", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          business_id: businessDetails.id,
          query_allocation: Number(localAlloc)
        }),
      });
      if (!res.ok) {
        throw new Error(await responseErrorMessage(res, "Could not patch settings profile."));
      }
    } catch (err: unknown) {
      setSettingsError(errorMessage(err, "An unhandled error occurred."));
    } finally {
      setIsSavingSettings(false);
    }
  };

  const handleInlineInvite = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!inviteEmail.trim() || !businessDetails) return;

    setIsSendingInvite(true);
    setInviteStatus(null);

    try {
      const res = await apiFetch(`/organizations/${businessDetails.org_id}/invite`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: inviteEmail.trim(),
          role: "member",
          business_ids: [businessDetails.id]
        })
      });

      if (!res.ok) {
        throw new Error(await responseErrorMessage(res, "Could not complete workspace invitation."));
      }

      const invitation = await res.json() as MemberRecord;
      setInviteStatus({ type: 'success', message: `Invitation dispatched successfully to ${inviteEmail}!` });
      setAllMembers(prev => [invitation, ...prev]);
      setInviteEmail('');
    } catch (err: unknown) {
      setInviteStatus({ type: 'error', message: errorMessage(err, "An unhandled network error occurred.") });
    } finally {
      setIsSendingInvite(false);
    }
  };

  const handleRevokeInvite = async (inviteId: string | number) => {
    if (!businessDetails) return;
    try {
      const parsedId = String(inviteId).replace('pending_', '');
      const res = await apiFetch(`/organizations/${businessDetails.org_id}/invitations/${encodeURIComponent(parsedId)}`, {
        method: "DELETE",
      });
      if (res.ok) {
        setAllMembers(prev => prev.filter(member => member.id !== inviteId));
      }
    } catch (err) {
      console.error("Failed to revoke database invitation entity:", err);
    }
  };

  return (
    <div className="screen" style={{ position: 'relative' }}>

      {/* ── TOP HEADER / FILTER NAVIGATION ── */}
      <div className="nav" style={{ overflow: 'visible', padding: '12px 24px', display: 'flex', alignItems: 'center', borderBottom: '1px solid var(--color-border-tertiary)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flex: 1 }}>
          <Link href="/dashboard" className="btn btn-secondary" style={{ padding: '6px 12px', fontSize: '13px', flexShrink: 0 }}>
            <ArrowLeft size={14} /> Dashboard
          </Link>

          {/* Switcher Dropdown Menu */}
          <div style={{ position: 'relative', width: '280px' }}>
            <button
              className="btn"
              style={{ width: '100%', justifyContent: 'space-between', padding: '6px 12px', background: 'var(--color-background-primary)' }}
              onClick={() => setIsDropdownOpen(!isDropdownOpen)}
            >
              <span style={{ display: 'flex', alignItems: 'center', gap: '6px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', fontSize: '13px', fontWeight: 500 }}>
                <Building2 size={14} style={{ color: 'var(--color-text-secondary)' }} />
                {contextLoading ? "Loading details..." : businessDetails ? businessDetails.name : "Select a business..."}
              </span>
              <ChevronsUpDown size={14} style={{ color: 'var(--color-text-tertiary)', flexShrink: 0 }} />
            </button>

            {isDropdownOpen && (
              <div style={s.dropdownMenu}>
                <input
                  type="text" placeholder="Filter business workspaces..." value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  style={s.dropdownInput}
                  autoFocus
                />
                <div style={{ maxHeight: '200px', overflowY: 'auto' }}>
                  {filteredBusinesses.length === 0 ? (
                    <div style={{ padding: '8px', fontSize: '12px', color: 'var(--color-text-tertiary)', textAlign: 'center' }}>
                      No locations linked
                    </div>
                  ) : (
                    filteredBusinesses.map((biz) => (
                      <button
                        key={biz.id}
                        style={{
                          ...s.dropdownItem,
                          background: activeBizId === biz.id ? 'var(--color-background-secondary, #f4f4f5)' : 'transparent',
                          fontWeight: activeBizId === biz.id ? 600 : 400
                        }}
                        onClick={() => {
                          handleSelectBusiness(biz);
                          setIsDropdownOpen(false);
                          setSearchQuery('');
                        }}
                      >
                        {biz.name}
                      </button>
                    ))
                  )}
                </div>
              </div>
            )}
          </div>
        </div>

        {businessDetails && (
          <Link 
            href={`/search?orgId=${businessDetails.org_id}&bizId=${businessDetails.id}`}
            className="btn btn-primary"
            style={{ flexShrink: '0', fontSize: '13px', display: 'flex', alignItems: 'center', gap: '6px', textDecoration: 'none' }}
          >
            <Search size={14} /> Open search
          </Link>
        )}
      </div>

      {/* ── MAIN WORKSPACE CONTENT WINDOW ── */}
      <div style={{ padding: '24px' }}>
        {!businessDetails ? (
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '360px', color: 'var(--color-text-secondary)', gap: '12px' }}>
            <Building2 size={36} style={{ strokeWidth: 1.5, color: 'var(--color-text-secondary)' }} />
            <div style={{ fontSize: '14px', textAlign: 'center' }}>
              {contextLoading
                ? 'Loading authorized business workspaces...'
                : 'Select an authorized business environment from the dropdown menu above.'}
            </div>
          </div>
        ) : (
          <div style={{ background: 'var(--color-background-primary)', border: '1px solid var(--color-border-tertiary)', borderRadius: '12px', overflow: 'hidden', boxShadow: '0 1px 3px rgba(0,0,0,0.05)' }}>

            {/* Context Sub-Header info block */}
            <div style={{ padding: '20px 24px', borderBottom: '1px solid var(--color-border-tertiary)', display: 'flex', justifyContent: 'space-between', alignItems: 'center', backgroundColor: '#fafafa' }}>
              <div>
                <h1 style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '16px', fontWeight: 600, margin: 0 }}>
                  {contextLoading && <Loader2 className="animate-spin" size={14} style={{ color: 'var(--color-text-info)' }} />}
                  {businessDetails ? businessDetails.name : "Loading Workspace details..."}
                </h1>
              </div>
            </div>

            {/* Segmented Workspace Navigation Tabs */}
            <div style={{ display: 'flex', background: '#ffffff', borderBottom: '1px solid var(--color-border-tertiary)', padding: '0 16px' }}>
              {tabs.map((t) => (
                <button
                  key={t.id}
                  onClick={() => setActiveTab(t.id)}
                  style={{
                    ...s.tabLink,
                    color: activeTab === t.id ? 'var(--color-primary, #4f46e5)' : 'var(--color-text-secondary)',
                    borderBottom: activeTab === t.id ? '2px solid var(--color-primary, #4f46e5)' : '2px solid transparent',
                    fontWeight: activeTab === t.id ? 600 : 400
                  }}
                >
                  {t.icon}
                  {t.label}
                </button>
              ))}
            </div>

            {/* Tab Interface Render Blocks */}
            <div style={{ padding: '24px', minHeight: '300px' }}>

              {/* SUB-PANEL 1: VECTOR DOCUMENTS */}
              {activeTab === 'files' && (
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
                    <div>
                      <h3 style={{ fontSize: '14px', fontWeight: 500, margin: 0 }}>Document Library</h3>
                      <p style={{ fontSize: '12px', color: 'var(--color-text-secondary)', margin: '2px 0 0 0' }}>Files ingested into the AI search index for this location.</p>
                    </div>
                    
                    <label className="btn btn-primary" style={{ fontSize: '12px', padding: '6px 12px', cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
                      <Upload size={13} />
                      Select Files
                      <input type="file" multiple onChange={handleFileSelection} style={{ display: 'none' }} disabled={uploading} />
                    </label>
                  </div>

                  {uploadError && (
                    <div style={{ ...s.errorBox, marginBottom: '16px' }}>
                      <ShieldAlert size={14} style={{ flexShrink: 0 }} />
                      <span style={{ fontSize: '12px' }}>{uploadError}</span>
                    </div>
                  )}

                  {/* STAGING QUEUE (PENDING FILES BEFORE INGESTION) */}
                  {pendingFiles.length > 0 && (
                    <div style={{ marginBottom: '24px', padding: '16px', background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: '8px' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                        <span style={{ fontSize: '12px', fontWeight: 600, color: '#334155' }}>
                          READY TO INGEST ({pendingFiles.length} file{pendingFiles.length > 1 ? 's' : ''})
                        </span>
                        <div style={{ display: 'flex', gap: '8px' }}>
                          <button 
                            className="btn btn-secondary" 
                            style={{ fontSize: '12px', padding: '4px 8px' }} 
                            onClick={() => setPendingFiles([])}
                            disabled={uploading}
                          >
                            Clear Staging
                          </button>
                          <button 
                            className="btn btn-primary" 
                            style={{ fontSize: '12px', padding: '4px 12px', gap: '6px' }}
                            onClick={handleStartUpload}
                            disabled={uploading}
                          >
                            {uploading ? <Loader2 className="animate-spin" size={13} /> : <Upload size={13} />}
                            {uploading ? "Ingesting..." : "Confirm & Ingest"}
                          </button>
                        </div>
                      </div>

                      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                        {pendingFiles.map((p) => (
                          <div key={p.id} style={{ border: '1px solid #cbd5e1', borderRadius: '6px', background: '#ffffff', overflow: 'hidden' }}>
                            {/* Primary Row Header */}
                            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 12px' }}>
                              <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flex: 1, minWidth: 0 }}>
                                {p.isExcel ? (
                                  <FileSpreadsheet size={16} style={{ color: '#16a34a', flexShrink: 0 }} />
                                ) : (
                                  <FileText size={16} style={{ color: '#64748b', flexShrink: 0 }} />
                                )}
                                <span style={{ fontSize: '13px', fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                  {p.file.name}
                                </span>
                                <span style={{ fontSize: '11px', color: '#94a3b8' }}>
                                  ({(p.file.size / 1024).toFixed(1)} KB)
                                </span>
                              </div>

                              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                {p.isExcel && (
                                  <button
                                    className="btn btn-secondary"
                                    onClick={() => toggleExpandPendingFile(p.id)}
                                    style={{
                                      fontSize: '11px',
                                      padding: '3px 8px',
                                      gap: '4px',
                                      background: p.context ? '#f0fdf4' : '#f8fafc',
                                      borderColor: p.context ? '#bbf7d0' : '#e2e8f0',
                                      color: p.context ? '#166534' : '#475569'
                                    }}
                                  >
                                    <Sparkles size={12} style={{ color: p.context ? '#16a34a' : '#94a3b8' }} />
                                    {p.context ? "Notes Added" : "Add AI Notes"}
                                    {p.isExpanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                                  </button>
                                )}
                                <button
                                  className="btn btn-secondary"
                                  style={{ padding: '4px', color: '#ef4444' }}
                                  onClick={() => removePendingFile(p.id)}
                                >
                                  <X size={13} />
                                </button>
                              </div>
                            </div>

                            {/* Inline Expandable Drawer for XLSX Context Notes */}
                            {p.isExcel && p.isExpanded && (
                              <div style={{ padding: '12px', background: '#f8fafc', borderTop: '1px solid #e2e8f0' }}>
                                <label style={{ display: 'block', fontSize: '11px', fontWeight: 600, color: '#475569', marginBottom: '4px' }}>
                                  Spreadsheet Ingestion Notes (Optional)
                                </label>
                                <textarea
                                  value={p.context}
                                  onChange={(e) => updatePendingFileContext(p.id, e.target.value)}
                                  placeholder="e.g. Yellow highlighted cells mean pending approval; Columns A-D are Q1 data."
                                  maxLength={MAX_INGESTION_NOTES_LENGTH}
                                  rows={2}
                                  style={{
                                    width: '100%',
                                    fontSize: '12px',
                                    padding: '6px 10px',
                                    borderRadius: '6px',
                                    border: '1px solid #cbd5e1',
                                    outline: 'none',
                                    resize: 'vertical',
                                    fontFamily: 'inherit'
                                  }}
                                />
                                <div style={{ marginTop: '3px', textAlign: 'right', fontSize: '10px', color: '#94a3b8' }}>
                                  {p.context.length} / {MAX_INGESTION_NOTES_LENGTH}
                                </div>

                                {/* Quick Preset Chips */}
                                <div style={{ display: 'flex', gap: '6px', marginTop: '8px', flexWrap: 'wrap', alignItems: 'center' }}>
                                  <span style={{ fontSize: '10px', color: '#64748b', fontWeight: 500 }}>Quick Presets:</span>
                                  <button
                                    type="button"
                                    onClick={() => addPresetChip(p.id, "Yellow cells indicate pending items")}
                                    style={s.presetChip}
                                  >
                                    + Yellow = Pending
                                  </button>
                                  <button
                                    type="button"
                                    onClick={() => addPresetChip(p.id, "Contains multiple side-by-side tables")}
                                    style={s.presetChip}
                                  >
                                    + Multi-Table
                                  </button>
                                  <button
                                    type="button"
                                    onClick={() => addPresetChip(p.id, "Top 3 rows contain KPI summary cards")}
                                    style={s.presetChip}
                                  >
                                    + Top KPI Cards
                                  </button>
                                </div>
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* INDEXED DOCUMENTS LIST */}
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                    {docsLoading ? (
                      <div style={{ padding: '40px', display: 'flex', justifyContent: 'center' }}><Loader2 className="animate-spin" size={20} /></div>
                    ) : documents.length === 0 ? (
                      <div style={{ fontSize: '13px', color: 'var(--color-text-secondary)', padding: '32px 0', textAlign: 'center', border: '1px dashed var(--color-border-tertiary)', borderRadius: '8px' }}>
                        No files matched to this index database framework yet.
                      </div>
                    ) : (
                      documents.map((doc) => (
                        <div key={doc.id} style={s.docItemRow}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flex: 1, minWidth: 0 }}>
                            <FileText size={16} style={{ color: '#ef4444', flexShrink: 0 }} />
                            <span style={{ fontSize: '13px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{doc.name}</span>
                          </div>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                            <span style={{ fontSize: '10px', fontWeight: 600, padding: '2px 6px', borderRadius: '4px', background: '#f4f4f5', color: '#71717a' }}>{doc.type}</span>
                            <button className="btn btn-secondary" style={{ padding: '4px', color: '#ef4444' }} onClick={() => handleDeleteDoc(doc.id)}>
                              <Trash2 size={13} />
                            </button>
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                </div>
              )}

              {/* SUB-PANEL 2: USAGE LIMITS */}
              {activeTab === 'settings' && (
                <div style={{ maxWidth: '480px' }}>
                  <h3 style={{ fontSize: '14px', fontWeight: 500, margin: '0 0 4px 0' }}>Quota Threshold Controls</h3>
                  <p style={{ fontSize: '12px', color: 'var(--color-text-secondary)', margin: '0 0 16px 0' }}>Configure maximum execution query guardrails assigned to this single branch entity.</p>

                  <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', marginBottom: '20px' }}>
                    <label style={{ fontSize: '11px', fontWeight: 600, color: 'var(--color-text-secondary)' }}>MAX ALLOCATED QUERIES / MONTH</label>
                    <input
                      type="number"
                      value={localAlloc}
                      onChange={(e) => setAllocationDraft({
                        businessId: businessDetails.id,
                        value: Number(e.target.value),
                      })}
                      style={s.formInput}
                      min={0}
                    />
                  </div>

                  {settingsError && (
                    <div style={s.errorBox}>
                      <ShieldAlert size={14} style={{ flexShrink: 0 }} />
                      <span style={{ fontSize: '12px' }}>{settingsError}</span>
                    </div>
                  )}

                  <button
                    className="btn btn-primary"
                    onClick={handleSaveSettings}
                    disabled={isSavingSettings}
                    style={{ fontSize: '13px', padding: '6px 14px' }}
                  >
                    {isSavingSettings ? <Loader2 className="animate-spin" size={13} /> : "Update Limits"}
                  </button>
                </div>
              )}

              {/* SUB-PANEL 3: ACCESS CONTROL */}
              {activeTab === 'team' && (
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
                    <div>
                      <h3 style={{ fontSize: '14px', fontWeight: 500, margin: 0 }}>Authorized Workspace Access</h3>
                      <p style={{ fontSize: '12px', color: 'var(--color-text-secondary)', margin: '2px 0 0 0' }}>Invite users with query execution permissions inside this location context scope.</p>
                    </div>
                  </div>

                  {/* Inline Invite Form */}
                  <form onSubmit={handleInlineInvite} style={{ display: 'flex', gap: '8px', marginBottom: '20px' }}>
                    <input 
                      type="email" 
                      placeholder="colleague@company.com" 
                      value={inviteEmail}
                      onChange={(e) => setInviteEmail(e.target.value)}
                      style={{ ...s.formInput, flex: 1, marginTop: 0 }}
                      required
                    />
                    <button type="submit" className="btn btn-primary" disabled={isSendingInvite || !inviteEmail.trim()} style={{ fontSize: '13px', whiteSpace: 'nowrap' }}>
                      {isSendingInvite ? <Loader2 className="animate-spin" size={13} /> : <UserPlus size={13} />}
                      Send Invite
                    </button>
                  </form>

                  {inviteStatus && (
                    <div style={{ ...s.errorBox, backgroundColor: inviteStatus.type === 'success' ? '#f0fdf4' : '#fef2f2', borderColor: inviteStatus.type === 'success' ? '#bbf7d0' : '#fee2e2', color: inviteStatus.type === 'success' ? '#166534' : '#ef4444', marginBottom: '16px' }}>
                      <span style={{ fontSize: '12px' }}>{inviteStatus.message}</span>
                    </div>
                  )}

                  {/* Team Members List */}
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                    {teamLoading ? (
                      <div style={{ padding: '30px', display: 'flex', justifyContent: 'center' }}><Loader2 className="animate-spin" size={18} /></div>
                    ) : teamMembers.length === 0 && pendingInvites.length === 0 ? (
                      <div style={{ fontSize: '13px', color: 'var(--color-text-secondary)', padding: '24px 0', textAlign: 'center', border: '1px dashed var(--color-border-tertiary)', borderRadius: '8px' }}>
                        No members assigned.
                      </div>
                    ) : (
                      <>
                        {teamMembers.map((m) => (
                          <div key={m.id} style={s.docItemRow}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                              <span style={{ fontSize: '13px', fontWeight: 500 }}>{m.email}</span>
                              {m.is_root && <span style={{ fontSize: '10px', background: '#e0e7ff', color: '#4f46e5', padding: '1px 6px', borderRadius: '4px' }}>Owner</span>}
                            </div>
                            <span style={{ fontSize: '11px', color: 'var(--color-text-secondary)', textTransform: 'capitalize' }}>{m.role}</span>
                          </div>
                        ))}
                        {pendingInvites.map((p) => (
                          <div key={p.id} style={{ ...s.docItemRow, opacity: 0.75 }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                              <span style={{ fontSize: '13px' }}>{p.email}</span>
                              <span style={{ fontSize: '10px', background: '#fef3c7', color: '#d97706', padding: '1px 6px', borderRadius: '4px' }}>Pending Invite</span>
                            </div>
                            <button className="btn btn-secondary" style={{ padding: '4px 8px', fontSize: '11px', color: '#ef4444' }} onClick={() => handleRevokeInvite(p.id)}>
                              Revoke
                            </button>
                          </div>
                        ))}
                      </>
                    )}
                  </div>
                </div>
              )}

            </div>
          </div>
        )}
      </div>
    </div>
  );
}

const s: Record<string, React.CSSProperties> = {
  dropdownMenu: { position: 'absolute', top: 'calc(100% + 4px)', left: 0, width: '100%', background: 'var(--color-background-primary)', border: '1px solid var(--color-border-tertiary)', borderRadius: '8px', boxShadow: '0 4px 12px rgba(0,0,0,0.08)', zIndex: 100, padding: '4px' },
  dropdownInput: { width: '100%', padding: '6px 10px', fontSize: '12px', border: 'none', borderBottom: '1px solid var(--color-border-tertiary)', outline: 'none', background: 'transparent', marginBottom: '4px' },
  dropdownItem: { width: '100%', textAlign: 'left', padding: '6px 10px', border: 'none', borderRadius: '4px', fontSize: '12px', cursor: 'pointer', display: 'block' },
  tabLink: { display: 'flex', alignItems: 'center', gap: '6px', padding: '12px 16px', background: 'transparent', border: 'none', cursor: 'pointer', fontSize: '13px' },
  docItemRow: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 12px', background: 'var(--color-background-secondary, #fafafa)', border: '1px solid var(--color-border-tertiary, #e4e4e7)', borderRadius: '6px' },
  formInput: { width: '100%', padding: '8px 12px', fontSize: '13px', borderRadius: '6px', border: '1px solid var(--color-border-tertiary, #e4e4e7)', background: 'transparent', outline: 'none', marginTop: '4px' },
  errorBox: { display: 'flex', gap: '8px', alignItems: 'center', padding: '10px 12px', borderRadius: '6px', backgroundColor: '#fef2f2', border: '1px solid #fee2e2', color: '#ef4444' },
  presetChip: { background: '#f1f5f9', border: '1px solid #cbd5e1', borderRadius: '4px', padding: '2px 6px', fontSize: '10px', color: '#334155', cursor: 'pointer', fontWeight: 500 }
};
