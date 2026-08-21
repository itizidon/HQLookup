'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import { FileText } from 'lucide-react';
import { Search, ChevronDown, Clock, Loader2, Building2, MessageSquare, ArrowRight, Plus } from 'lucide-react';
import { useBusiness } from '@/app/context/BusinessContext';
import { DebounceContainer } from '@/components/Debounce';
import { useRouter, useSearchParams } from 'next/navigation';
import { apiFetch } from '@/app/lib/api';

interface RagAnswerSource {
  chunk: number;
  filename: string;
  correlation?: number | null;
}

interface RagAnswer {
  answer: string;
  confidence?: number | null;
  sources?: RagAnswerSource[];
}

interface RagResponse {
  answer: {
    answers: RagAnswer[];
  };
  sources: string[];
  chunks_used: number;
  hasMore: boolean;
  nextOffset: number | null;
  usage?: {
    searches_limit: number;
  };
}

interface RecentQuery {
  id: number;
  question: string;
  answer: string;
}

const formatCorrelation = (score: number | null | undefined) => {
  if (typeof score !== 'number' || !Number.isFinite(score)) {
    return 'Unavailable';
  }

  const percentage = score * 100;

  return `${Math.round(Math.min(100, Math.max(-100, percentage)))}%`;
};

export default function SearchHome() {
  const { selectedBusiness: contextBusiness, businesses, selectBusiness } = useBusiness();
  const router = useRouter();
  const searchParams = useSearchParams();
  const requestedBusinessValue = searchParams.get('bizId');
  const requestedOrganizationValue = searchParams.get('orgId');
  const requestedBusinessId = requestedBusinessValue ? Number(requestedBusinessValue) : null;
  const requestedOrganizationId = requestedOrganizationValue ? Number(requestedOrganizationValue) : null;
  const requestedBusiness = businesses.find((business) => (
    business.id === requestedBusinessId
    && (requestedOrganizationId === null || business.org_id === requestedOrganizationId)
  ));
  const selectedBusiness = requestedBusiness ?? contextBusiness;
  const [isDropdownOpen, setIsDropdownOpen] = useState(false);

  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [result, setResult] = useState<RagResponse | null>(null);

  const [recentQueries, setRecentQueries] = useState<RecentQuery[]>([]);
  const [loadingQueries, setLoadingQueries] = useState(false);
  useEffect(() => {
    if (!selectedBusiness) {
      return;
    }

    const fetchRecentQueries = async () => {
      setLoadingQueries(true);
      try {
        const res = await apiFetch(`/queries/recent?business_id=${selectedBusiness.id}&page=1&page_size=5`, {
          method: "GET",
        });
        if (!res.ok) throw new Error("Failed to fetch recent queries");
        const data = await res.json();
        setRecentQueries(data.queries || []);
      } catch (err) {
        console.error("Recent Queries Error:", err);
      } finally {
        setLoadingQueries(false);
      }
    };

    fetchRecentQueries();
  }, [selectedBusiness]);

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim() || !selectedBusiness) return;

    setLoading(true);
    setResult(null);

    try {
      const response = await apiFetch("/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: query,
          business_id: selectedBusiness.id,
          get_k: 5,
          offset: 0
        })
      });

      if (!response.ok) throw new Error("Search execution failed");
      const data: RagResponse = await response.json();
      setResult(data);

      const updatedRes = await apiFetch(`/queries/recent?business_id=${selectedBusiness.id}&page=1&page_size=5`, {
        method: "GET",
      });
      if (updatedRes.ok) {
        const updatedData = await updatedRes.json();
        setRecentQueries(updatedData.queries || []);
      }
    } catch (err) {
      console.error("RAG Error:", err);
    } finally {
      setLoading(false);
    }
  };

  const handleLoadMore = async () => {
    if (!result || !result.hasMore || result.nextOffset === null || !selectedBusiness || loadingMore) return;

    setLoadingMore(true);

    try {
      const response = await apiFetch("/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: query,
          business_id: selectedBusiness.id,
          get_k: 5,
          offset: result.nextOffset
        })
      });

      if (!response.ok) throw new Error("Pagination iteration step failed");
      const data: RagResponse = await response.json();

      setResult((prev) => {
        if (!prev) return data;
      
        return {
          ...data,
          answer: {
            answers: [
              ...(prev.answer?.answers ?? []),
              ...(data.answer?.answers ?? []),
            ],
          },
          sources: Array.from(
            new Set([
              ...(prev.sources ?? []),
              ...(data.sources ?? []),
            ])
          ),
          chunks_used:
            (prev.chunks_used ?? 0) +
            (data.chunks_used ?? 0),
        };
      });
    } catch (err) {
      console.error("Load More Pipeline Error:", err);
    } finally {
      setLoadingMore(false);
    }
  };

  return (
    <div className="screen" style={{ position: 'relative' }}>
      <div className="nav" style={{ overflow: 'visible' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', position: 'relative' }}>
          {/* Logo / Brand Name linking back to Dashboard */}
          <Link href="/dashboard" className="nav-logo" style={{ textDecoration: 'none' }}>
            <FileText size={18} style={{ color: 'var(--color-text-info)' }} /> HQLookup
          </Link>

          <div style={{ width: '1px', height: '14px', background: 'var(--color-border-secondary)' }} />

          <button
            className="btn"
            style={{ fontSize: '13px', padding: '5px 10px', display: 'flex', alignItems: 'center', gap: '6px' }}
            onClick={() => setIsDropdownOpen(!isDropdownOpen)}
          >
            <Building2 size={13} style={{ color: 'var(--color-text-secondary)' }} />
            {selectedBusiness ? selectedBusiness.name : "Select Business"} <ChevronDown size={12} />
          </button>

          {isDropdownOpen && (
            <div style={{
              position: 'absolute', top: 'calc(100% + 4px)', left: '90px', width: '220px',
              background: 'var(--color-background-primary)', border: '0.5px solid var(--color-border-secondary)',
              borderRadius: 'var(--border-radius-md)', boxShadow: '0 4px 12px rgba(0,0,0,0.08)', zIndex: 100, padding: '4px'
            }}>
              {businesses.map((biz) => (
                <button
                  key={biz.id}
                  style={{
                    width: '100%', textAlign: 'left', padding: '6px 10px', border: 'none', borderRadius: '4px',
                    fontSize: '12px', background: selectedBusiness?.id === biz.id ? 'var(--color-background-secondary)' : 'transparent',
                    cursor: 'pointer'
                  }}
                  onClick={() => {
                    setRecentQueries([]);
                    selectBusiness(biz);
                    router.replace(`/search?orgId=${biz.org_id}&bizId=${biz.id}`);
                    setIsDropdownOpen(false);
                    setResult(null);
                  }}
                >
                  {biz.name}
                </button>
              ))}
            </div>
          )}
        </div>

      </div>

      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '40px 24px', gap: '24px' }}>
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: '22px', fontWeight: 500, marginBottom: '6px' }}>What do you want to know?</div>
          <div style={{ fontSize: '13px', color: 'var(--color-text-secondary)' }}>
            Search across documents in <span style={{ fontWeight: 600, color: 'var(--color-text-info)' }}>{selectedBusiness?.name || "your business"}</span>
          </div>
        </div>

        <form onSubmit={handleSearch} style={{ display: 'flex', alignItems: 'center', gap: '10px', width: '100%', maxWidth: '520px', padding: '6px 10px 6px 14px', border: '0.5px solid var(--color-border-secondary)', borderRadius: '40px', background: 'var(--color-background-primary)' }}>
          <Search size={16} style={{ color: 'var(--color-text-tertiary)' }} />
          <input
            type="text"
            placeholder="Ask anything about your documents…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            disabled={!selectedBusiness || loading}
            style={{ border: 'none', outline: 'none', flex: 1, fontSize: '14px', background: 'transparent', padding: 0 }}
          />
          <button
            type="submit"
            className="btn btn-primary"
            disabled={loading || !query.trim() || !selectedBusiness}
            style={{ borderRadius: '20px', padding: '6px 16px', fontSize: '13px' }}
          >
            {loading ? <Loader2 className="animate-spin" size={14} /> : "Search"}
          </button>
        </form>

        {result && (
          <div style={{ width: '100%', maxWidth: '520px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
            <div className="card" style={{ width: '100%', padding: '16px', borderRadius: 'var(--border-radius-lg)', background: 'var(--color-background-secondary)' }}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', marginBottom: '10px' }}>
                <div style={{ display: 'flex', alignItems: 'flex-start', gap: '8px' }}>
                  <MessageSquare size={16} style={{ color: 'var(--color-text-info)', marginTop: '2px' }} />
                  <div style={{ fontSize: '13px', fontWeight: 600, color: 'var(--color-text-primary)' }}>
                    Generated Answer ({result.answer?.answers?.length} points):
                  </div>
                </div>

                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', paddingLeft: '24px' }}>
                  {result.answer?.answers?.map((item, idx) => (
                    <div
                      key={`${idx}-${item.answer}`}
                      style={{
                        padding: '10px',
                        border: '0.5px solid var(--color-border-tertiary)',
                        borderRadius: 'var(--border-radius-md)',
                        background: 'var(--color-background-primary)'
                      }}
                    >
                      <div style={{ fontSize: '13px', color: 'var(--color-text-primary)', lineHeight: '1.5' }}>
                        {idx + 1}. {item.answer}
                      </div>

                      <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: '4px', marginTop: '8px' }}>
                        {(item.sources ?? []).length > 0 ? (
                          (item.sources ?? []).map((source) => (
                            <div
                              key={`${source.filename}-${source.chunk}`}
                              style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: '4px', minWidth: 0 }}
                            >
                              <span
                                className="badge badge-success"
                                style={{ fontSize: '10px', padding: '2px 6px', gap: '3px', maxWidth: '100%', overflowWrap: 'anywhere' }}
                              >
                                <FileText size={10} style={{ flexShrink: 0 }} />
                                Source: {source.filename} · chunk {source.chunk}
                              </span>
                              <span className="badge badge-info" style={{ fontSize: '10px', padding: '2px 6px' }}>
                                Correlation: {formatCorrelation(source.correlation)}
                              </span>
                            </div>
                          ))
                        ) : (
                          <>
                            <span className="badge" style={{ fontSize: '10px', padding: '2px 6px', color: 'var(--color-text-tertiary)' }}>
                              Source unavailable
                            </span>
                            <span className="badge badge-info" style={{ fontSize: '10px', padding: '2px 6px' }}>
                              Correlation: Unavailable
                            </span>
                          </>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>

            </div>

            {result.hasMore && (
              <DebounceContainer action={handleLoadMore} delay={600}>
                {({ handleAction, isLoading }) => {
                  const isProcessing = loadingMore || isLoading;

                  return (
                    <button
                      type="button"
                      onClick={handleAction}
                      disabled={isProcessing}
                      className="btn"
                      style={{
                        width: '100%',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        gap: '6px',
                        padding: '10px',
                        fontSize: '12px',
                        fontWeight: 500,
                        borderRadius: 'var(--border-radius-md)',
                        border: '0.5px dashed var(--color-border-secondary)',
                        background: 'var(--color-background-primary)',
                        cursor: isProcessing ? 'not-allowed' : 'pointer',
                        transition: 'all 0.2s ease',
                        opacity: isProcessing ? 0.7 : 1
                      }}
                    >
                      {isProcessing ? (
                        <>
                          <Loader2 className="animate-spin" size={13} />
                          Assembling Context Chunks ({result.nextOffset})...
                        </>
                      ) : (
                        <>
                          <Plus size={13} />
                          Load More Points (Offset: {result.nextOffset})
                        </>
                      )}
                    </button>
                  );
                }}
              </DebounceContainer>
            )}
          </div>
        )}

        {!result && (
          <div style={{ width: '100%', maxWidth: '520px' }}>
            <div style={{ fontSize: '12px', color: 'var(--color-text-tertiary)', marginBottom: '8px', fontWeight: 500 }}>Recent queries</div>

            {loadingQueries ? (
              <div style={{ display: 'flex', justifyContent: 'center', padding: '16px' }}>
                <Loader2 className="animate-spin" size={16} style={{ color: 'var(--color-text-tertiary)' }} />
              </div>
            ) : selectedBusiness && recentQueries.length > 0 ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                {recentQueries.map((q) => (
                  <button
                    key={q.id}
                    type="button"
                    className="table-row"
                    style={{ width: '100%', textAlign: 'left', padding: '8px 10px', borderRadius: 'var(--border-radius-md)', border: 'none', background: 'transparent', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '8px' }}
                    onClick={() => setQuery(q.question)}
                  >
                    <Clock size={14} style={{ color: 'var(--color-text-tertiary)' }} />
                    <span style={{ fontSize: '13px', color: 'var(--color-text-secondary)', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {q.question}
                    </span>
                    <ArrowRight size={12} style={{ color: 'var(--color-text-tertiary)' }} />
                  </button>
                ))}
              </div>
            ) : (
              <div style={{ fontSize: '12px', color: 'var(--color-text-tertiary)', padding: '8px 0' }}>
                No recent queries found for this business.
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
