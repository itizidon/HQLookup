import Link from "next/link";
import { ArrowRight, CheckCircle2, Search, FileText, Database, Layers, Users, FolderPlus, History, Cpu, ShieldCheck } from "lucide-react";
import { MarketingFooter, MarketingHeader } from "@/components/MarketingNavigation";

export const metadata = {
  title: "AI Document Search Features | HQLookup Capabilities",
  description: "Explore HQLookup features. Discover how AI-powered search, Excel table and chart understanding, cross-document retrieval, and secure workspaces help teams find answers.",
};

export default function FeaturesPage() {
  return (
    <div className="screen" style={{ position: 'relative', overflowX: 'hidden', minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      <style>{`
        @media (max-width: 768px) {
          .features-grid {
            grid-template-columns: 1fr !important;
          }
        }
      `}</style>

      <MarketingHeader activePage="features" />

      {/* Main Content Area */}
      <main style={{ padding: '48px 24px', maxWidth: '840px', margin: '0 auto', width: '100%', flex: 1, display: 'flex', flexDirection: 'column', gap: '48px' }}>
        
        {/* Hero Section */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <div style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', padding: '4px 10px', borderRadius: '20px', background: 'var(--color-background-secondary, #f4f4f5)', fontSize: '11px', fontWeight: 500, color: 'var(--color-text-secondary, #71717a)', width: 'fit-content' }}>
            Platform Capabilities
          </div>
          <h1 style={{ fontSize: '32px', fontWeight: 600, color: 'var(--color-text-primary, #18181b)', letterSpacing: '-0.02em', lineHeight: '1.2' }}>
            What does HQLookup actually do?
          </h1>
          <p style={{ fontSize: '15px', color: 'var(--color-text-secondary, #71717a)', lineHeight: '1.6' }}>
            HQLookup is engineered specifically for document-heavy business workflows. Instead of standard keyword searches or tedious manual digging, our platform combines advanced retrieval engines with deep file understanding to surface precise answers instantly.
          </p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', marginTop: '8px' }}>
            <Link href="/auth?mode=signup" className="btn btn-primary" style={{ fontSize: '13px', textDecoration: 'none', padding: '10px 20px', width: 'fit-content', display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
              Get Started Free <ArrowRight size={14} />
            </Link>
            <span style={{ fontSize: '11px', color: 'var(--color-text-secondary, #71717a)' }}>No credit card required.</span>
          </div>
        </div>

        {/* Detailed Features Grid */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
          <div>
            <h2 style={{ fontSize: '22px', fontWeight: 600, color: 'var(--color-text-primary, #18181b)', marginBottom: '8px' }}>
              Core search & intelligence features
            </h2>
            <p style={{ fontSize: '14px', color: 'var(--color-text-secondary, #71717a)' }}>
              Built from the ground up to handle the messy, multi-format reality of business documentation.
            </p>
          </div>

          <div className="features-grid" style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '16px' }}>
            
            {/* Search Across Multiple Documents */}
            <div className="card" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '15px', fontWeight: 600, color: 'var(--color-text-primary, #18181b)' }}>
                <Search size={18} style={{ color: 'var(--color-text-secondary)' }} />
                Search across multiple documents
              </div>
              <p style={{ fontSize: '13px', color: 'var(--color-text-secondary, #71717a)', lineHeight: '1.5', margin: 0 }}>
                Ask a question without knowing which file contains the answer. HQLookup scans across your entire knowledge base to find and synthesize the most relevant details.
              </p>
            </div>

            {/* Understand Excel Tables and Charts */}
            <div className="card" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '15px', fontWeight: 600, color: 'var(--color-text-primary, #18181b)' }}>
                <Database size={18} style={{ color: 'var(--color-text-secondary)' }} />
                Tables & chart understanding
              </div>
              <p style={{ fontSize: '13px', color: 'var(--color-text-secondary, #71717a)', lineHeight: '1.5', margin: 0 }}>
                Search structured spreadsheet rows, columns, tables, and visualization charts so vital financial and numerical data never stays trapped inside workbooks.
              </p>
            </div>

            {/* Source-Backed Answers */}
            <div className="card" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '15px', fontWeight: 600, color: 'var(--color-text-primary, #18181b)' }}>
                <ShieldCheck size={18} style={{ color: 'var(--color-text-secondary)' }} />
                Source-backed answers
              </div>
              <p style={{ fontSize: '13px', color: 'var(--color-text-secondary, #71717a)', lineHeight: '1.5', margin: 0 }}>
                Every answer comes with direct references and excerpts from the original source files, allowing you to easily verify numbers, clauses, and policies.
              </p>
            </div>

            {/* Multi-Query & HyDE Retrieval */}
            <div className="card" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '15px', fontWeight: 600, color: 'var(--color-text-primary, #18181b)' }}>
                <Cpu size={18} style={{ color: 'var(--color-text-secondary)' }} />
                Advanced AI retrieval (HyDE)
              </div>
              <p style={{ fontSize: '13px', color: 'var(--color-text-secondary, #71717a)', lineHeight: '1.5', margin: 0 }}>
                Utilizes multi-query expansion and Hypothetical Document Embeddings (HyDE) to bridge the gap between how you phrase a question and how documents are written.
              </p>
            </div>

          </div>

          {/* Full width card for document types */}
          <div className="card" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '16px', fontWeight: 600, color: 'var(--color-text-primary, #18181b)' }}>
              <FileText size={18} style={{ color: 'var(--color-text-secondary)' }} />
              Comprehensive file format support
            </div>
            <p style={{ fontSize: '13px', color: 'var(--color-text-secondary, #71717a)', lineHeight: '1.5', margin: 0 }}>
              You shouldn&apos;t have to reorganize your office before searching. HQLookup supports the exact files your business already uses every day:
            </p>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '10px' }}>
              {[
                "PDF documents",
                "Excel spreadsheets (.xlsx)",
                "Spreadsheet tables & rows",
                "Charts & visualizations",
                "Word documents (.docx)",
                "CSV & tabular files",
                "Reports & manuals",
                "Corporate policies & SOPs",
                "Contracts & invoices"
              ].map((fmt, idx) => (
                <div key={idx} style={{ padding: '10px 12px', borderRadius: '6px', background: 'var(--color-background-secondary, #f4f4f5)', fontSize: '12px', fontWeight: 500, color: 'var(--color-text-primary, #18181b)', display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <CheckCircle2 size={13} style={{ color: '#10b981', flexShrink: 0 }} />
                  {fmt}
                </div>
              ))}
            </div>
          </div>

        </div>

        {/* Workspace & Collaboration Features */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
          <div>
            <h2 style={{ fontSize: '22px', fontWeight: 600, color: 'var(--color-text-primary, #18181b)', marginBottom: '8px' }}>
              Workspaces, team access & management
            </h2>
            <p style={{ fontSize: '14px', color: 'var(--color-text-secondary, #71717a)' }}>
              Designed for teams and multi-location businesses that require structure and oversight.
            </p>
          </div>

          <div className="features-grid" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '16px' }}>
            
            <div className="card" style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
              <Layers size={18} style={{ color: 'var(--color-text-secondary)' }} />
              <h3 style={{ fontSize: '14px', fontWeight: 600, color: 'var(--color-text-primary, #18181b)', margin: 0 }}>Business Workspaces</h3>
              <p style={{ fontSize: '12px', color: 'var(--color-text-secondary, #71717a)', lineHeight: '1.5', margin: 0 }}>
                Keep separate knowledge bases organized by business unit, property, or department under a single overarching organization.
              </p>
            </div>

            <div className="card" style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
              <Users size={18} style={{ color: 'var(--color-text-secondary)' }} />
              <h3 style={{ fontSize: '14px', fontWeight: 600, color: 'var(--color-text-primary, #18181b)', margin: 0 }}>Team Access</h3>
              <p style={{ fontSize: '12px', color: 'var(--color-text-secondary, #71717a)', lineHeight: '1.5', margin: 0 }}>
                Invite teammates to collaborate, share document insights, and find information together without friction.
              </p>
            </div>

            <div className="card" style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
              <FolderPlus size={18} style={{ color: 'var(--color-text-secondary)' }} />
              <h3 style={{ fontSize: '14px', fontWeight: 600, color: 'var(--color-text-primary, #18181b)', margin: 0 }}>Document Management</h3>
              <p style={{ fontSize: '12px', color: 'var(--color-text-secondary, #71717a)', lineHeight: '1.5', margin: 0 }}>
                Easily upload, organize, update, or remove files as your operational records evolve over time.
              </p>
            </div>

          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '16px' }}>
            <div className="card" style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '14px', fontWeight: 600, color: 'var(--color-text-primary, #18181b)' }}>
                <History size={16} style={{ color: 'var(--color-text-secondary)' }} />
                Query History
              </div>
              <p style={{ fontSize: '12px', color: 'var(--color-text-secondary, #71717a)', lineHeight: '1.5', margin: 0 }}>
                Review past searches and questions to quickly retrieve previous answers and track recurring inquiries across your team.
              </p>
            </div>

            <div className="card" style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '14px', fontWeight: 600, color: 'var(--color-text-primary, #18181b)' }}>
                <Cpu size={16} style={{ color: 'var(--color-text-secondary)' }} />
                Upcoming Integrations
              </div>
              <p style={{ fontSize: '12px', color: 'var(--color-text-secondary, #71717a)', lineHeight: '1.5', margin: 0 }}>
                Roadmap features include direct cloud storage connectors (Google Drive, OneDrive, Dropbox) to sync documents automatically.
              </p>
            </div>
          </div>
        </div>

        {/* Call to Action Box */}
        <div className="card" style={{ padding: '32px', textAlign: 'center', background: 'var(--color-background-secondary, #f4f4f5)', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '16px' }}>
          <h3 style={{ fontSize: '20px', fontWeight: 600, color: 'var(--color-text-primary, #18181b)', margin: 0 }}>
            Experience HQLookup with your own documents
          </h3>
          <p style={{ fontSize: '14px', color: 'var(--color-text-secondary, #71717a)', maxWidth: '480px', margin: 0 }}>
            Upload PDFs, spreadsheets, or reports and start asking questions in seconds.
          </p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', alignItems: 'center', marginTop: '8px' }}>
            <Link href="/auth?mode=signup" className="btn btn-primary" style={{ fontSize: '13px', textDecoration: 'none', padding: '10px 20px', display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
              Get Started Free <ArrowRight size={14} />
            </Link>
            <span style={{ fontSize: '11px', color: 'var(--color-text-secondary, #71717a)' }}>No credit card required.</span>
          </div>
        </div>

      </main>

      <MarketingFooter activePage="features" />
    </div>
  );
}
