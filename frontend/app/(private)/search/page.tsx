'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import { Search, ChevronDown, History, Clock, Loader2, Building2, MessageSquare, ArrowRight, Plus } from 'lucide-react';
import { useBusiness } from '@/app/context/BusinessContext';
import { DebounceContainer } from '@/components/Debounce';

interface RagResponse {
  answer: {
    answers: Array<{ fact: string;[key: string]: any }>;
  };
  sources: string[];
  chunks_used: number;
  hasMore: boolean;
  nextOffset: number | null;
}

interface RecentQuery {
  id: number;
  question: string;
  answer: string;
}

export default function SearchHome() {
  const { selectedBusiness, businesses, selectBusiness } = useBusiness();
  const [isDropdownOpen, setIsDropdownOpen] = useState(false);

  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [result, setResult] = useState<RagResponse | null>(null);

  const [recentQueries, setRecentQueries] = useState<RecentQuery[]>([]);
  const [loadingQueries, setLoadingQueries] = useState(false);

  useEffect(() => {
    if (!selectedBusiness) {
      setRecentQueries([]);
      return;
    }

    const fetchRecentQueries = async () => {
      setLoadingQueries(true);
      try {
        const res = await fetch(`http://localhost:8000/queries/recent?business_id=${selectedBusiness.id}&page=1&page_size=5`, {
          method: "GET",
          credentials: "include",
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
      const response = await fetch("http://localhost:8000/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          question: query,
          business_id: selectedBusiness.id,
          get_k: 5,
          offset: 0
        })
      });

      if (!response.ok) throw new Error("Search execution failed");
      const data = await response.json();
      setResult(data);

      const updatedRes = await fetch(`http://localhost:8000/queries/recent?business_id=${selectedBusiness.id}&page=1&page_size=5`, {
        method: "GET",
        credentials: "include",
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
      const response = await fetch("http://localhost:8000/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
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
            answers: [...prev.answer.answers, ...(data.answer?.answers || [])]
          },
          sources: Array.from(new Set([...prev.sources, ...data.sources])),
          chunks_used: prev.chunks_used + data.chunks_used
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
          <Link
            href="/dashboard"
            style={{ display: 'flex', alignItems: 'center', gap: '8px', textDecoration: 'none', color: 'var(--color-text-primary)' }}
          >
            <div style={{ width: '24px', height: '24px', borderRadius: '6px', background: 'var(--color-primary, #4f46e5)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#fff', fontSize: '11px', fontWeight: 700 }}>
              AI
            </div>
            <span style={{ fontSize: '14px', fontWeight: 600, letterSpacing: '-0.2px' }}>AskAI</span>
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
                    selectBusiness(biz);
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

        <div className="nav-right" style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <button className="nav-link" style={{ display: 'flex', alignItems: 'center', gap: '4px', background: 'transparent', border: 'none', cursor: 'pointer' }}>
            <History size={13} /> History
          </button>
          <div className="avatar">BS</div>
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
                  {result.answer?.answers?.map((item: any, idx: number) => (
                    <div key={idx} style={{ fontSize: '13px', color: 'var(--color-text-primary)', lineHeight: '1.5' }}>
                      • {item.answer}
                    </div>
                  ))}
                </div>
              </div>

              {result.sources.length > 0 && (
                <div style={{ borderTop: '0.5px solid var(--color-border-tertiary)', paddingTop: '10px', marginTop: '10px' }}>
                  <div style={{ fontSize: '11px', color: 'var(--color-text-tertiary)', fontWeight: 500, marginBottom: '4px' }}>Sources Verified:</div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px' }}>
                    {result.sources.map((src, idx) => (
                      <span key={idx} className="badge badge-success" style={{ fontSize: '10px', padding: '2px 6px' }}>{src}</span>
                    ))}
                  </div>
                </div>
              )}
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
            ) : recentQueries.length > 0 ? (
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