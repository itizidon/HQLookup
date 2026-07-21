'use client';

import { useState, useEffect, useMemo, ChangeEvent } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { 
  ArrowLeft, Search, Upload, Trash2, FileText, UserPlus, 
  ChevronsUpDown, Building2, Loader2, ShieldAlert, Sliders, 
  Users, ChevronDown, ChevronRight, Sparkles, FileSpreadsheet, X 
} from 'lucide-react';
import { useBusiness } from '@/app/context/BusinessContext';

interface ServerDocument {
  id: string;
  name: string;
  type: string;
  business_id: number;
}

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
  const { businesses, isLoading: contextLoading } = useBusiness();
  const router = useRouter();
  const searchParams = useSearchParams();

  // ── THE ABSOLUTE SOURCES OF TRUTH (URL Parameters) ──
  const urlBizId = searchParams.get('bizId');
  const urlOrgId = searchParams.get('orgId');

  const activeBizId = urlBizId ? Number(urlBizId) : null;
  const activeOrgId = urlOrgId ? Number(urlOrgId) : null;

  // ── LOCAL STATE MATRICES ──
  const [businessDetails, setBusinessDetails] = useState<BusinessDetails | null>(null);
  const [activeTab, setActiveTab] = useState<'files' | 'settings' | 'team'>('files');

  // Interactive UI / Search Filter States
  const [searchQuery, setSearchQuery] = useState('');
  const [isDropdownOpen, setIsDropdownOpen] = useState(false);
  const [documents, setDocuments] = useState<ServerDocument[]>([]);
  const [docsLoading, setDocsLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  
  // Pending File Staging State for XLSX Context Injection
  const [pendingFiles, setPendingFiles] = useState<PendingFile[]>([]);

  // Settings Allocation Form States
  const [localAlloc, setLocalAlloc] = useState<number>(25);
  const [isSavingSettings, setIsSavingSettings] = useState(false);
  const [settingsError, setSettingsError] = useState<string | null>(null);

  // Inline Single Invite Form States
  const [inviteEmail, setInviteEmail] = useState('');
  const [isSendingInvite, setIsSendingInvite] = useState(false);
  const [inviteStatus, setInviteStatus] = useState<{ type: 'success' | 'error'; message: string } | null>(null);

  // Access Control Repositories
  const [teamLoading, setTeamLoading] = useState(false);
  const [allMembers, setAllMembers] = useState<any[]>([]);

  // Split unified members payload cleanly into active/pending structures on the fly
  const { teamMembers, pendingInvites } = useMemo(() => {
    const active: any[] = [];
    const pending: any[] = [];

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
          is_root: m.is_root
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
    if (!activeBizId || !activeOrgId) {
      setBusinessDetails(null);
      setDocuments([]);
      setAllMembers([]);
      return;
    }

    setSettingsError(null);
    setInviteEmail('');
    setInviteStatus(null);

    if (businesses && businesses.length > 0) {
      const matched = businesses.find(b => b.id === activeBizId);
      if (matched) {
        setBusinessDetails({
          id: matched.id,
          name: matched.name,
          org_id: matched.org_id,
          query_allocation: matched.query_allocation ?? 25
        });
        setLocalAlloc(matched.query_allocation ?? 25);
      }
    }

    const fetchDocs = async () => {
      setDocsLoading(true);
      try {
        const res = await fetch("http://localhost:8000/documents", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "include",
          body: JSON.stringify({
            business_ids: [activeBizId],
            page: 1,
            page_size: 50
          })
        });
        const data = await res.json();
        if (data.documents) {
          setDocuments(data.documents);
        }
      } catch (err) {
        console.error("Error retrieving documents:", err);
      } finally {
        setDocsLoading(false);
      }
    };

    const fetchTeamAndInvites = async () => {
      setTeamLoading(true);
      try {
        const res = await fetch(
          `http://localhost:8000/organizations/${activeOrgId}/businesses/${activeBizId}/members`,
          { credentials: "include" }
        );

        if (res.ok) {
          const data = await res.json();
          setAllMembers(data.members || []);
        }
      } catch (err) {
        console.error("Error retrieving unified access control data list:", err);
      } finally {
        setTeamLoading(false);
      }
    };

    fetchDocs();
    fetchTeamAndInvites();
  }, [activeBizId, activeOrgId, businesses]);

  const handleSelectBusiness = (biz: typeof businesses[0]) => {
    const params = new URLSearchParams(searchParams.toString());
    params.set('orgId', biz.org_id.toString());
    params.set('bizId', biz.id.toString());
    router.push(`${window.location.pathname}?${params.toString()}`);
  };

  // Stage files into pending list when picked from disk
  const handleFileSelection = (e: ChangeEvent<HTMLInputElement>) => {
    if (!e.target.files || e.target.files.length === 0) return;

    const newFiles: PendingFile[] = Array.from(e.target.files).map((f) => {
      const isExcel = f.name.endsWith('.xlsx') || f.name.endsWith('.xls');
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
      prev.map((f) => (f.id === id ? { ...f, context: text } : f))
    );
  };

  const addPresetChip = (id: string, presetText: string) => {
    setPendingFiles((prev) =>
      prev.map((f) => {
        if (f.id !== id) return f;
        const current = f.context.trim();
        const updated = current ? `${current}; ${presetText}` : presetText;
        return { ...f, context: updated };
      })
    );
  };

  // Execute actual upload API call with file contexts
  const handleStartUpload = async () => {
    if (pendingFiles.length === 0 || !activeBizId) return;

    setUploading(true);
    const formData = new FormData();
    formData.append("business_id", activeBizId.toString());

    // Map file metadata contexts as a JSON string array to pass alongside FormData
    const contextsPayload: Record<string, string> = {};

    pendingFiles.forEach((p) => {
      formData.append("files", p.file);
      if (p.isExcel && p.context.trim()) {
        contextsPayload[p.file.name] = p.context.trim();
      }
    });

    formData.append("file_contexts", JSON.stringify(contextsPayload));

    try {
      const res = await fetch("http://localhost:8000/upload-multiple", {
        method: "POST",
        body: formData,
        credentials: "include",
      });
      const data = await res.json();
      if (data.uploaded) {
        const newDocs: ServerDocument[] = data.uploaded.map((u: any) => ({
          id: u.document_id.toString(),
          name: u.filename,
          type: u.filename.split('.').pop()?.toUpperCase() || 'UNKNOWN',
          business_id: activeBizId
        }));
        setDocuments((prev) => [...newDocs, ...prev]);
        setPendingFiles([]); // Clear staging queue
      }
    } catch (err) {
      console.error("Upload failure:", err);
    } finally {
      setUploading(false);
    }
  };

  const handleDeleteDoc = async (docId: string) => {
    if (!activeBizId) return;
    try {
      const res = await fetch(`http://localhost:8000/documents/${docId}?business_id=${activeBizId}`, {
        credentials: "include",
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
    if (!activeBizId) return;
    setIsSavingSettings(true);
    setSettingsError(null);
    try {
      const res = await fetch(`http://localhost:8000/businesses/settings`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          business_id: activeBizId,
          query_allocation: Number(localAlloc)
        }),
        credentials: "include",
      });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || "Could not patch settings profile.");
      }
      
      setBusinessDetails(prev => prev ? { ...prev, query_allocation: Number(localAlloc) } : null);
    } catch (err: any) {
      setSettingsError(err.message || "An unhandled error occurred.");
    } finally {
      setIsSavingSettings(false);
    }
  };

  const handleInlineInvite = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!inviteEmail.trim() || !activeBizId || !activeOrgId) return;

    setIsSendingInvite(true);
    setInviteStatus(null);

    try {
      const res = await fetch(`http://localhost:8000/organizations/${activeOrgId}/invite`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          email: inviteEmail.trim(),
          role: "member",
          business_ids: [activeBizId]
        })
      });

      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || "Could not complete workspace invitation.");
      }

      setInviteStatus({ type: 'success', message: `Invitation dispatched successfully to ${inviteEmail}!` });

      const simulatedInvite = {
        id: `pending_${Math.random().toString()}`,
        email: inviteEmail.trim(),
        role: "member",
        status: "pending",
        created_at: new Date().toISOString()
      };
      setAllMembers(prev => [simulatedInvite, ...prev]);
      setInviteEmail('');
    } catch (err: any) {
      setInviteStatus({ type: 'error', message: err.message || "An unhandled network error occurred." });
    } finally {
      setIsSendingInvite(false);
    }
  };

  const handleRevokeInvite = async (inviteId: string) => {
    if (!activeOrgId) return;
    try {
      const parsedId = inviteId.replace('pending_', '');
      const res = await fetch(`http://localhost:8000/organizations/${activeOrgId}/invitations/${parsedId}`, {
        method: "DELETE",
        credentials: "include"
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

        {activeBizId && (
          <Link href="/search" className="btn btn-primary" style={{ flexShrink: 0, fontSize: '13px' }}>
            <Search size={14} /> Open search
          </Link>
        )}
      </div>

      {/* ── MAIN WORKSPACE CONTENT WINDOW ── */}
      <div style={{ padding: '24px' }}>
        {!activeBizId ? (
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '360px', color: 'var(--color-text-secondary)', gap: '12px' }}>
            <Building2 size={36} style={{ strokeWidth: 1.5, color: 'var(--color-text-secondary)' }} />
            <div style={{ fontSize: '14px', textAlign: 'center' }}>
              Select an isolated business environment from the dropdown menu above to adjust vectors or bounds.
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
                <p style={{ fontSize: '11px', color: 'var(--color-text-secondary)', margin: '4px 0 0 0' }}>Instance Resource Key: #{activeBizId}</p>
              </div>
              <button 
                className="btn btn-secondary" 
                style={{ fontSize: '12px', padding: '4px 10px', color: '#ef4444' }} 
                onClick={() => {
                  router.push(window.location.pathname);
                }}
              >
                Unmount Context
              </button>
            </div>

            {/* Segmented Workspace Navigation Tabs */}
            <div style={{ display: 'flex', background: '#ffffff', borderBottom: '1px solid var(--color-border-tertiary)', padding: '0 16px' }}>
              {[
                { id: 'files', label: 'Knowledge Base', icon: <FileText size={14} /> },
                { id: 'settings', label: 'Usage Limits', icon: <Sliders size={14} /> },
                { id: 'team', label: 'Access Control', icon: <Users size={14} /> }
              ].map((t) => (
                <button
                  key={t.id}
                  onClick={() => setActiveTab(t.id as any)}
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
                      <h3 style={{ fontSize: '14px', fontWeight: 500, margin: 0 }}>Indexed Knowledge Corpora</h3>
                      <p style={{ fontSize: '12px', color: 'var(--color-text-secondary)', margin: '2px 0 0 0' }}>Files ingested into the vector search embedding space.</p>
                    </div>
                    
                    <label className="btn btn-primary" style={{ fontSize: '12px', padding: '6px 12px', cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
                      <Upload size={13} />
                      Select Files
                      <input type="file" multiple onChange={handleFileSelection} style={{ display: 'none' }} disabled={uploading} />
                    </label>
                  </div>

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
                                  Spreadsheet Processing Context (Optional)
                                </label>
                                <textarea
                                  value={p.context}
                                  onChange={(e) => updatePendingFileContext(p.id, e.target.value)}
                                  placeholder="e.g. Yellow highlighted cells mean pending approval; Columns A-D are Q1 data."
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
                      onChange={(e) => setLocalAlloc(Number(e.target.value))}
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

                  {/* Single Invite Form */}
                  <form onSubmit={handleInlineInvite} style={{ display: 'flex', flexDirection: 'column', gap: '8px', maxWidth: '480px', marginBottom: '24px' }}>
                    <div style={{ display: 'flex', gap: '8px' }}>
                      <input
                        type="email"
                        placeholder="teammate@company.com"
                        value={inviteEmail}
                        onChange={(e) => setInviteEmail(e.target.value)}
                        required
                        disabled={isSendingInvite}
                        style={{ ...s.formInput, flex: 1 }}
                      />
                      <button
                        type="submit"
                        className="btn btn-primary"
                        disabled={isSendingInvite || !inviteEmail.trim()}
                        style={{ fontSize: '12px', whiteSpace: 'nowrap', gap: '6px', display: 'flex', alignItems: 'center' }}
                      >
                        {isSendingInvite ? <Loader2 className="animate-spin" size={14} /> : <UserPlus size={14} />}
                        {isSendingInvite ? "Adding..." : "Add User"}
                      </button>
                    </div>

                    {inviteStatus && (
                      <div style={{
                        fontSize: '12px',
                        padding: '6px 10px',
                        borderRadius: '4px',
                        marginTop: '4px',
                        backgroundColor: inviteStatus.type === 'success' ? '#f0fdf4' : '#fef2f2',
                        border: inviteStatus.type === 'success' ? '1px solid #bbf7d0' : '1px solid #fee2e2',
                        color: inviteStatus.type === 'success' ? '#16a34a' : '#ef4444',
                        display: 'flex',
                        alignItems: 'center'
                      }}>
                        {inviteStatus.message}
                      </div>
                    )}
                  </form>

                  {teamLoading ? (
                    <div style={{ padding: '24px', display: 'flex', justifyContent: 'center' }}>
                      <Loader2 className="animate-spin" size={20} />
                    </div>
                  ) : (
                    <>
                      {/* Section 1: Active Team Members */}
                      <div style={{ marginBottom: '24px' }}>
                        <h4 style={{ fontSize: '11px', fontWeight: 600, color: 'var(--color-text-secondary)', marginBottom: '8px', letterSpacing: '0.05em' }}>
                          ACTIVE MEMBERS ({teamMembers.length})
                        </h4>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                          {teamMembers.map((member) => (
                            <div key={member.id} style={s.docItemRow}>
                              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                                <div style={{ width: '28px', height: '28px', borderRadius: '50%', background: member.is_root ? 'var(--color-primary, #4f46e5)' : '#e4e4e7', color: member.is_root ? '#fff' : '#18181b', fontSize: '10px', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 600 }}>
                                  {member.email.slice(0, 2).toUpperCase()}
                                </div>
                                <div>
                                  <div style={{ fontSize: '13px', fontWeight: 500 }}>{member.email}</div>
                                  <div style={{ fontSize: '11px', color: 'var(--color-text-secondary)' }}>Role context classification: {member.role}</div>
                                </div>
                              </div>
                              <span style={{ fontSize: '10px', padding: '2px 6px', background: member.is_root ? '#e0e7ff' : '#f4f4f5', color: member.is_root ? '#4f46e5' : '#71717a', borderRadius: '4px', fontWeight: 600 }}>
                                {member.is_root ? "Root Account" : "Active"}
                              </span>
                            </div>
                          ))}
                        </div>
                      </div>

                      {/* Section 2: Pending Invitations */}
                      <div>
                        <h4 style={{ fontSize: '11px', fontWeight: 600, color: 'var(--color-text-secondary)', marginBottom: '8px', letterSpacing: '0.05em' }}>
                          PENDING INVITATIONS ({pendingInvites.length})
                        </h4>
                        {pendingInvites.length === 0 ? (
                          <div style={{ fontSize: '12px', color: 'var(--color-text-tertiary)', padding: '16px 0', textAlign: 'center', border: '1px dashed var(--color-border-tertiary)', borderRadius: '8px' }}>
                            No pending invitations active for this scope.
                          </div>
                        ) : (
                          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                            {pendingInvites.map((invite) => (
                              <div key={invite.id} style={s.docItemRow}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                                  <div style={{ width: '28px', height: '28px', borderRadius: '50%', background: '#fafafa', color: '#a1a1aa', fontSize: '10px', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 600, border: '1px dashed #e4e4e7' }}>
                                    ?
                                  </div>
                                  <div>
                                    <div style={{ fontSize: '13px', fontWeight: 500 }}>{invite.email}</div>
                                    <div style={{ fontSize: '11px', color: 'var(--color-text-secondary)' }}>
                                      Sent {new Date(invite.created_at).toLocaleDateString()}
                                    </div>
                                  </div>
                                </div>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                                  <span style={{ fontSize: '10px', padding: '2px 6px', background: '#fef3c7', color: '#d97706', borderRadius: '4px', fontWeight: 600 }}>
                                    Pending Seat
                                  </span>
                                  <button
                                    className="btn btn-secondary"
                                    style={{ padding: '4px 8px', fontSize: '11px', color: '#ef4444', border: '1px solid #fee2e2' }}
                                    onClick={() => handleRevokeInvite(invite.id)}
                                  >
                                    Revoke
                                  </button>
                                </div>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    </>
                  )}
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
  dropdownMenu: { position: 'absolute', top: 'calc(100% + 4px)', left: 0, width: '100%', background: 'var(--color-background-primary, #ffffff)', border: '1px solid var(--color-border-tertiary, #e4e4e7)', borderRadius: '8px', boxShadow: '0 4px 12px rgba(0,0,0,0.08)', zIndex: 100, padding: '4px' },
  dropdownInput: { width: '100%', fontSize: '12px', padding: '6px 10px', marginBottom: '4px', borderRadius: '6px', border: '1px solid var(--color-border-tertiary, #e4e4e7)', outline: 'none' },
  dropdownItem: { width: '100%', textAlign: 'left', padding: '8px 10px', border: 'none', borderRadius: '6px', fontSize: '12px', cursor: 'pointer', display: 'block', color: 'var(--color-text-primary, #18181b)' },
  tabLink: { display: 'flex', alignItems: 'center', gap: '6px', padding: '12px 16px', fontSize: '13px', background: 'transparent', border: 'none', cursor: 'pointer', outline: 'none', transition: 'all 0.15s ease' },
  docItemRow: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 14px', border: '1px solid var(--color-border-tertiary, #e4e4e7)', borderRadius: '8px', backgroundColor: '#ffffff' },
  formInput: { width: '100%', padding: '8px 12px', fontSize: '13px', borderRadius: '6px', border: '1px solid var(--color-border-tertiary, #e4e4e7)', outline: 'none', background: '#ffffff' },
  errorBox: { display: 'flex', gap: '8px', alignItems: 'center', padding: '8px 12px', background: '#fef2f2', border: '1px solid #fee2e2', color: '#ef4444', borderRadius: '6px', marginBottom: '12px' },
  presetChip: { fontSize: '10px', padding: '2px 8px', borderRadius: '12px', border: '1px solid #cbd5e1', background: '#ffffff', color: '#334155', cursor: 'pointer', outline: 'none' }
};