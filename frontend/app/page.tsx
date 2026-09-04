import Link from "next/link";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { ArrowRight, ShieldCheck, Database, Layers } from "lucide-react";
import { MarketingFooter, MarketingHeader } from "@/components/MarketingNavigation";

export default async function Home() {
  const cookieStore = await cookies();
  const cookieName = process.env.NODE_ENV === "production" ? "__Host-token" : "token";
  const hasSession = cookieStore.has(cookieName);

  if (hasSession) {
    redirect("/search");
  }

  return (
    <div className="screen" style={{ position: 'relative', overflowX: 'hidden', minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      {/* Responsive media query to stack cards and handle mobile navigation */}
      <style>{`
        @media (max-width: 768px) {
          .feature-grid {
            grid-template-columns: 1fr !important;
          }
        }
      `}</style>

      <MarketingHeader />

      {/* Main Content Area */}
      <main style={{ padding: '40px 24px', maxWidth: '1000px', margin: '0 auto', width: '100%', flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
        {/* Hero Card */}
        <div className="card" style={{ padding: '32px', marginBottom: '20px' }}>
          <div style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', padding: '4px 10px', borderRadius: '20px', background: 'var(--color-background-secondary, #f4f4f5)', fontSize: '11px', fontWeight: 500, color: 'var(--color-text-secondary, #71717a)', marginBottom: '16px' }}>
            <span style={{ width: '6px', height: '6px', borderRadius: '50%', background: '#10b981' }} />
            Enterprise RAG & Knowledge Platform
          </div>
          <h1 style={{ fontSize: '26px', fontWeight: 600, color: 'var(--color-text-primary, #18181b)', marginBottom: '12px', letterSpacing: '-0.02em' }}>
            Instant intelligence across all your business branches.
          </h1>
          <p style={{ fontSize: '13px', color: 'var(--color-text-secondary, #71717a)', lineHeight: '1.5', marginBottom: '24px', maxWidth: '600px' }}>
            Upload documents per location, manage multi-tenant organization workspaces, and query your enterprise knowledge base with precise RAG intelligence.
          </p>
          <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
            <Link href="/demo" className="btn btn-primary" style={{ fontSize: '13px', textDecoration: 'none', padding: '8px 16px' }}>
              Book a Demo <ArrowRight size={14} style={{ marginLeft: '6px' }} />
            </Link>
            <Link href="/auth?mode=signup" className="btn btn-secondary" style={{ fontSize: '13px', textDecoration: 'none', padding: '8px 16px' }}>
              Get Started Free
            </Link>
          </div>
        </div>

        {/* Feature Cards Grid (3 Columns on Desktop, Stacks vertically on Mobile) */}
        <div className="feature-grid" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '12px' }}>
          <div className="card">
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px', fontSize: '14px', fontWeight: 500 }}>
              <Database size={16} style={{ color: 'var(--color-text-secondary)' }} />
              Multi-Branch RAG
            </div>
            <p style={{ fontSize: '12px', color: 'var(--color-text-secondary)', lineHeight: '1.4' }}>
              Upload specialized documentation for separate business branches and query them independently.
            </p>
          </div>

          <div className="card">
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px', fontSize: '14px', fontWeight: 500 }}>
              <Layers size={16} style={{ color: 'var(--color-text-secondary)' }} />
              Organization Workspaces
            </div>
            <p style={{ fontSize: '12px', color: 'var(--color-text-secondary)', lineHeight: '1.4' }}>
              Seamlessly group locations under clean organizational frameworks with usage tracking.
            </p>
          </div>

          <div className="card">
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px', fontSize: '14px', fontWeight: 500 }}>
              <ShieldCheck size={16} style={{ color: 'var(--color-text-secondary)' }} />
              Enterprise Security
            </div>
            <p style={{ fontSize: '12px', color: 'var(--color-text-secondary)', lineHeight: '1.4' }}>
              Robust cookie-based sessions, bot defense, and isolated data partitions keeping your data secure.
            </p>
          </div>
        </div>
      </main>

      <MarketingFooter />
    </div>
  );
}
