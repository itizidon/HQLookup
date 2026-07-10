'use client';

import { useState, useEffect, useMemo, ChangeEvent } from 'react';
import Link from 'next/link';
import { ArrowLeft, Search, Upload, Trash2, FileText, UserPlus, ChevronsUpDown, Building2, Loader2, ShieldAlert, Sliders, Users } from 'lucide-react';
import { useBusiness } from '@/app/context/BusinessContext';

interface ServerDocument {
  id: string;
  name: string;
  type: string;
  business_id: number;
}

export default function EnterpriseBusinessDetail() {
  const { businesses, selectedBusiness, selectBusiness, clearSelection, isLoading: contextLoading } = useBusiness();

  // Tab Routing State
  const [activeTab, setActiveTab] = useState<'files' | 'settings' | 'team'>('files');

  // Interactive UI / Form States
  const [searchQuery, setSearchQuery] = useState('');
  const [isDropdownOpen, setIsDropdownOpen] = useState(false);
  const [documents, setDocuments] = useState<ServerDocument[]>([]);
  const [docsLoading, setDocsLoading] = useState(false);
  const [uploading, setUploading] = useState(false);

  // Settings Allocation Form States
  const [localAlloc, setLocalAlloc] = useState<number>(25);
  const [isSavingSettings, setIsSavingSettings] = useState(false);
  const [settingsError, setSettingsError] = useState<string | null>(null);

  // ── INLINE SINGLE INVITE FORM STATES ──
  const [inviteEmail, setInviteEmail] = useState('');
  const [isSendingInvite, setIsSendingInvite] = useState(false);
  const [inviteStatus, setInviteStatus] = useState<{ type: 'success' | 'error'; message: string } | null>(null);

  // Memoized client-side filter for the location picker dropdown
  const filteredBusinesses = useMemo(() => {
    if (!searchQuery) return businesses;
    return businesses.filter((biz) =>
      biz.name.toLowerCase().includes(searchQuery.toLowerCase())
    );
  }, [searchQuery, businesses]);

  // Sync internal configuration data whenever selectedBusiness hooks change
  useEffect(() => {
    if (!selectedBusiness) return;

    // Reset settings tracking parameters to match the active context
    setLocalAlloc(selectedBusiness.query_allocation ?? 25);
    setSettingsError(null);
    
    // Clear out stale invitation form states when switching contexts
    setInviteEmail('');
    setInviteStatus(null);

    const fetchDocs = async () => {
      setDocsLoading(true);
      try {
        const res = await fetch("http://localhost:8000/documents", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "include",
          body: JSON.stringify({
            business_ids: [selectedBusiness.id],
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

    fetchDocs();
  }, [selectedBusiness]);

  // Handle document attachment array pipelines
  const handleUpload = async (e: ChangeEvent<HTMLInputElement>) => {
    if (!e.target.files || e.target.files.length === 0 || !selectedBusiness) return;

    setUploading(true);
    const formData = new FormData();
    formData.append("business_id", selectedBusiness.id.toString());

    Array.from(e.target.files).forEach((file) => {
      formData.append("files", file);
    });

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
          business_id: selectedBusiness.id
        }));
        setDocuments((prev) => [...newDocs, ...prev]);
      }
    } catch (err) {
      console.error("Upload failure:", err);
    } finally {
      setUploading(false);
    }
  };

  // Handle absolute data purging requests
  const handleDeleteDoc = async (docId: string) => {
    if (!selectedBusiness) return;
    try {
      const res = await fetch(`http://localhost:8000/documents/${docId}?business_id=${selectedBusiness.id}`,
        {
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

  // Handle mutations to query pool allocations
  const handleSaveSettings = async () => {
    if (!selectedBusiness) return;
    setIsSavingSettings(true);
    setSettingsError(null);
    try {
      const res = await fetch(`http://localhost:8000/businesses/settings`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ 
          business_id: selectedBusiness.id, 
          query_allocation: Number(localAlloc) 
        }),
        credentials: "include",
      });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || "Could not patch settings profile.");
      }

      selectedBusiness.query_allocation = Number(localAlloc);
    } catch (err: any) {
      setSettingsError(err.message || "An unhandled error occurred.");
    } finally {
      setIsSavingSettings(false);
    }
  };

  // ── INLINE SINGLE BUSINESS INVITE ACTION PIPELINE ──
  const handleInlineInvite = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!inviteEmail.trim() || !selectedBusiness) return;

    setIsSendingInvite(true);
    setInviteStatus(null);

    try {
      const res = await fetch(`http://localhost:8000/organizations/${selectedBusiness.org_id}/invite`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          email: inviteEmail.trim(),
          role: "member",
          business_ids: [selectedBusiness.id] // Encapsulates the 1 targeted business scope
        })
      });

      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || "Could not complete workspace invitation.");
      }

      setInviteStatus({ type: 'success', message: `Invitation dispatched successfully to ${inviteEmail}!` });
      setInviteEmail('');
    } catch (err: any) {
      setInviteStatus({ type: 'error', message: err.message || "An unhandled network error occurred." });
    } finally {
      setIsSendingInvite(false);
    }
  };

  if (contextLoading) {
    return (
      <div className="screen" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '520px' }}>
        <Loader2 className="animate-spin" size={24} style={{ color: 'var(--color-text-info)' }} />
      </div>
    );
  }

  return (
    <div className="screen" style={{ position: 'relative' }}>

      {/* ── TOP HEADER / FILTER NAVIGATION ── */}
      <div className="nav" style={{ overflow: 'visible', padding: '12px 24px', display: 'flex', alignItems: 'center', borderBottom: '1px solid var(--color-border-tertiary)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flex: 1 }}>
          <Link href="/dashboard" className="btn btn-secondary" style={{ padding: '6px 12px', fontSize: '13px', flexShrink: 0 }}>
            <ArrowLeft size={14} /> Dashboard
          </Link>

          {/* Location Picker Custom Input Selector */}
          <div style={{ position: 'relative', width: '280px' }}>
            <button
              className="btn"
              style={{ width: '100%', justifyContent: 'space-between', padding: '6px 12px', background: 'var(--color-background-primary)' }}
              onClick={() => setIsDropdownOpen(!isDropdownOpen)}
            >
              <span style={{ display: 'flex', alignItems: 'center', gap: '6px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', fontSize: '13px', fontWeight: 500 }}>
                <Building2 size={14} style={{ color: 'var(--color-text-secondary)' }} />
                {selectedBusiness ? selectedBusiness.name : "Select a business..."}
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
                          background: selectedBusiness?.id === biz.id ? 'var(--color-background-secondary, #f4f4f5)' : 'transparent',
                          fontWeight: selectedBusiness?.id === biz.id ? 600 : 400
                        }}
                        onClick={() => {
                          selectBusiness(biz);
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

        {selectedBusiness && (
          <Link href="/search" className="btn btn-primary" style={{ flexShrink: 0, fontSize: '13px' }}>
            <Search size={14} /> Open search
          </Link>
        )}
      </div>

      {/* ── MAIN WORKSPACE CONTENT WINDOW ── */}
      <div style={{ padding: '24px' }}>
        {!selectedBusiness ? (
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
                <h1 style={{ fontSize: '16px', fontWeight: 600, margin: 0 }}>{selectedBusiness.name}</h1>
                <p style={{ fontSize: '11px', color: 'var(--color-text-secondary)', margin: '4px 0 0 0' }}>Instance Resource Key: #{selectedBusiness.id}</p>
              </div>
              <button className="btn btn-secondary" style={{ fontSize: '12px', padding: '4px 10px', color: '#ef4444' }} onClick={clearSelection}>
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
                    <label className="btn btn-primary" style={{ fontSize: '12px', padding: '6px 12px', cursor: 'pointer' }}>
                      {uploading ? <Loader2 className="animate-spin" size={13} /> : <Upload size={13} />}
                      {uploading ? " Ingesting..." : " Add Documents"}
                      <input type="file" multiple onChange={handleUpload} style={{ display: 'none' }} disabled={uploading} />
                    </label>
                  </div>

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

              {/* SUB-PANEL 2: USAGE ALIGNMENT ALLOCATIONS */}
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

              {/* SUB-PANEL 3: SEAT COLLABORATORS PERMISSIONS */}
              {activeTab === 'team' && (
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
                    <div>
                      <h3 style={{ fontSize: '14px', fontWeight: 500, margin: 0 }}>Authorized Workspace Access</h3>
                      <p style={{ fontSize: '12px', color: 'var(--color-text-secondary)', margin: '2px 0 0 0' }}>Invite users with query execution permissions inside this location context scope.</p>
                    </div>
                  </div>

                  {/* ── UPDATED SINGLE INVITE MVP FORM ── */}
                  <form onSubmit={handleInlineInvite} style={{ display: 'flex', flexDirection: 'column', gap: '8px', maxWidth: '480px', marginBottom: '20px' }}>
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

                  <div style={s.docItemRow}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                      <div style={{ width: '28px', height: '28px', borderRadius: '50%', background: 'var(--color-primary, #4f46e5)', color: '#fff', fontSize: '10px', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 600 }}>
                        SYS
                      </div>
                      <div>
                        <div style={{ fontSize: '13px', fontWeight: 500 }}>Organization Administrator Account</div>
                        <div style={{ fontSize: '11px', color: 'var(--color-text-secondary)' }}>Inherited Master Clearance</div>
                      </div>
                    </div>
                    <span style={{ fontSize: '10px', padding: '2px 6px', background: '#e0e7ff', color: '#4f46e5', borderRadius: '4px', fontWeight: 600 }}>Root Account</span>
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

// ── STYLE DECLARATIONS OBJECT ──
const s: Record<string, React.CSSProperties> = {
  dropdownMenu: { position: 'absolute', top: 'calc(100% + 4px)', left: 0, width: '100%', background: 'var(--color-background-primary, #ffffff)', border: '1px solid var(--color-border-tertiary, #e4e4e7)', borderRadius: '8px', boxShadow: '0 4px 12px rgba(0,0,0,0.08)', zIndex: 100, padding: '4px' },
  dropdownInput: { width: '100%', fontSize: '12px', padding: '6px 10px', marginBottom: '4px', borderRadius: '6px', border: '1px solid var(--color-border-tertiary, #e4e4e7)', outline: 'none' },
  dropdownItem: { width: '100%', textAlign: 'left', padding: '8px 10px', border: 'none', borderRadius: '6px', fontSize: '12px', cursor: 'pointer', display: 'block', color: 'var(--color-text-primary, #18181b)' },
  tabLink: { display: 'flex', alignItems: 'center', gap: '6px', padding: '12px 16px', fontSize: '13px', background: 'transparent', border: 'none', cursor: 'pointer', outline: 'none', transition: 'all 0.15s ease' },
  docItemRow: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 14px', border: '1px solid var(--color-border-tertiary, #e4e4e7)', borderRadius: '8px', backgroundColor: '#ffffff' },
  formInput: { width: '100%', padding: '8px 12px', fontSize: '13px', borderRadius: '6px', border: '1px solid var(--color-border-tertiary, #e4e4e7)', outline: 'none', background: '#ffffff' },
  errorBox: { display: 'flex', gap: '8px', alignItems: 'center', padding: '8px 12px', background: '#fef2f2', border: '1px solid #fee2e2', color: '#ef4444', borderRadius: '6px', marginBottom: '12px' }
};