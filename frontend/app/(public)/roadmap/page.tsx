import Link from "next/link";
import { ArrowRight, MessageSquareText, BarChart3, FileStack, Users, Webhook, Clock, Sparkles } from "lucide-react";
import { MarketingFooter, MarketingHeader } from "@/components/MarketingNavigation";

export const metadata = {
  title: "Product Roadmap | HQLookup",
  description: "Explore what's next for HQLookup, including SMS text queries, advanced analytical plans, and expanded document ingestion capabilities.",
};

export default function RoadmapPage() {
  return (
    <div className="screen" style={{ position: 'relative', overflowX: 'hidden', minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      <style>{`
        @media (max-width: 768px) {
          .roadmap-grid {
            grid-template-columns: 1fr !important;
          }
        }
      `}</style>

      <MarketingHeader activePage="roadmap" />

      {/* Main Content Area */}
      <main style={{ padding: '48px 24px', maxWidth: '840px', margin: '0 auto', width: '100%', flex: 1, display: 'flex', flexDirection: 'column', gap: '48px' }}>
        
        {/* Hero Section */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <div style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', padding: '4px 10px', borderRadius: '20px', background: 'var(--color-background-secondary, #f4f4f5)', fontSize: '11px', fontWeight: 500, color: 'var(--color-text-secondary, #71717a)', width: 'fit-content' }}>
            <Sparkles size={12} /> Product Roadmap
          </div>
          <h1 style={{ fontSize: '32px', fontWeight: 600, color: 'var(--color-text-primary, #18181b)', letterSpacing: '-0.02em', lineHeight: '1.2' }}>
            What’s next for HQLookup
          </h1>
          <p style={{ fontSize: '15px', color: 'var(--color-text-secondary, #71717a)', lineHeight: '1.6' }}>
            We are continuously expanding how teams interact with their business data. See what features, integrations, and capabilities we are actively building to make finding answers even easier.
          </p>
        </div>

        {/* Roadmap Highlights / Focus Areas */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
          <h2 style={{ fontSize: '20px', fontWeight: 600, color: 'var(--color-text-primary, #18181b)' }}>
            Upcoming Capabilities
          </h2>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
            
            {/* Feature 1: Text Your Business */}
            <div className="card" style={{ padding: '28px', display: 'flex', flexDirection: 'column', gap: '16px', borderLeft: '4px solid var(--color-text-primary, #18181b)' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '12px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                  <div style={{ padding: '8px', borderRadius: '8px', background: 'var(--color-background-secondary, #f4f4f5)', color: 'var(--color-text-primary)' }}>
                    <MessageSquareText size={20} />
                  </div>
                  <div>
                    <h3 style={{ fontSize: '18px', fontWeight: 600, color: 'var(--color-text-primary, #18181b)', margin: 0 }}>
                      Text Your Business (SMS & Messaging)
                    </h3>
                    <span style={{ fontSize: '12px', color: 'var(--color-text-secondary, #71717a)' }}>Mobile & SMS Integration</span>
                  </div>
                </div>
                <span style={{ fontSize: '11px', fontWeight: 600, padding: '4px 10px', borderRadius: '12px', background: '#e0f2fe', color: '#0369a1' }}>
                  In Progress
                </span>
              </div>
              <p style={{ fontSize: '14px', color: 'var(--color-text-secondary, #71717a)', lineHeight: '1.6', margin: 0 }}>
                Query your company documents, policies, and knowledge base instantly via SMS or preferred messaging apps. Eliminate the friction of opening a browser or logging into the web app when you need a quick answer on the go.
              </p>
              <div style={{ fontSize: '12px', color: 'var(--color-text-secondary, #71717a)', background: 'var(--color-background-secondary, #f4f4f5)', padding: '12px', borderRadius: '8px', display: 'flex', gap: '8px', alignItems: 'center' }}>
                <Clock size={14} style={{ flexShrink: 0 }} />
                <span>Target Release: Q2 2027</span>
              </div>
            </div>

            {/* Feature 2: Analytical Plan */}
            <div className="card" style={{ padding: '28px', display: 'flex', flexDirection: 'column', gap: '16px', borderLeft: '4px solid var(--color-text-secondary, #71717a)' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '12px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                  <div style={{ padding: '8px', borderRadius: '8px', background: 'var(--color-background-secondary, #f4f4f5)', color: 'var(--color-text-primary)' }}>
                    <BarChart3 size={20} />
                  </div>
                  <div>
                    <h3 style={{ fontSize: '18px', fontWeight: 600, color: 'var(--color-text-primary, #18181b)', margin: 0 }}>
                      Advanced Analytical Plan & Reporting
                    </h3>
                    <span style={{ fontSize: '12px', color: 'var(--color-text-secondary, #71717a)' }}>Data Intelligence Tier</span>
                  </div>
                </div>
                <span style={{ fontSize: '11px', fontWeight: 600, padding: '4px 10px', borderRadius: '12px', background: '#fef3c7', color: '#b45309' }}>
                  Planned
                </span>
              </div>
              <p style={{ fontSize: '14px', color: 'var(--color-text-secondary, #71717a)', lineHeight: '1.6', margin: 0 }}>
                A specialized plan and toolkit for financial, operational, and property management teams. Features deep spreadsheet aggregations, cross-workbook formula reasoning, automated metric extraction, and visual trend forecasting.
              </p>
              <div style={{ fontSize: '12px', color: 'var(--color-text-secondary, #71717a)', background: 'var(--color-background-secondary, #f4f4f5)', padding: '12px', borderRadius: '8px', display: 'flex', gap: '8px', alignItems: 'center' }}>
                <Clock size={14} style={{ flexShrink: 0 }} />
                <span>Target Release: Q2 2027</span>
              </div>
            </div>

            {/* Feature 3: Expanded Document Ingestion */}
            <div className="card" style={{ padding: '28px', display: 'flex', flexDirection: 'column', gap: '16px', borderLeft: '4px solid var(--color-text-primary, #18181b)' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '12px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                  <div style={{ padding: '8px', borderRadius: '8px', background: 'var(--color-background-secondary, #f4f4f5)', color: 'var(--color-text-primary)' }}>
                    <FileStack size={20} />
                  </div>
                  <div>
                    <h3 style={{ fontSize: '18px', fontWeight: 600, color: 'var(--color-text-primary, #18181b)', margin: 0 }}>
                      Expanded Document Ingestion Formats
                    </h3>
                    <span style={{ fontSize: '12px', color: 'var(--color-text-secondary, #71717a)' }}>Core Engine Upgrade</span>
                  </div>
                </div>
                <span style={{ fontSize: '11px', fontWeight: 600, padding: '4px 10px', borderRadius: '12px', background: '#e0f2fe', color: '#0369a1' }}>
                  In Progress
                </span>
              </div>
              <p style={{ fontSize: '14px', color: 'var(--color-text-secondary, #71717a)', lineHeight: '1.6', margin: 0 }}>
                Broadening our file parser to ingest and index more complex business formats natively, including specialized CAD files, encrypted financial archives, multi-tab accounting ledgers, and rich media transcripts.
              </p>
              <div style={{ fontSize: '12px', color: 'var(--color-text-secondary, #71717a)', background: 'var(--color-background-secondary, #f4f4f5)', padding: '12px', borderRadius: '8px', display: 'flex', gap: '8px', alignItems: 'center' }}>
                <Clock size={14} style={{ flexShrink: 0 }} />
                <span>Target Release: Q1 2027</span>
              </div>
            </div>

          </div>
        </div>

        {/* Other Planned Improvements */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
          <h2 style={{ fontSize: '18px', fontWeight: 600, color: 'var(--color-text-primary, #18181b)' }}>
            Other items on our radar
          </h2>
          <div className="roadmap-grid" style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '16px' }}>
            <div className="card" style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '14px', fontWeight: 600, color: 'var(--color-text-primary)' }}>
                <Users size={16} /> Team Workspaces & Roles
              </div>
              <p style={{ fontSize: '12px', color: 'var(--color-text-secondary, #71717a)', lineHeight: '1.5', margin: 0 }}>
                Granular permission controls and shared knowledge repositories for growing organizations.
              </p>
            </div>

            <div className="card" style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '14px', fontWeight: 600, color: 'var(--color-text-primary)' }}>
                <Webhook size={16} /> Webhooks & API Access
              </div>
              <p style={{ fontSize: '12px', color: 'var(--color-text-secondary, #71717a)', lineHeight: '1.5', margin: 0 }}>
                Integrate HQLookup search directly into your custom internal software stack and tools.
              </p>
            </div>
          </div>
        </div>

        {/* Feedback Callout */}
        <div className="card" style={{ padding: '32px', textAlign: 'center', background: 'var(--color-background-secondary, #f4f4f5)', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '16px' }}>
          <h3 style={{ fontSize: '20px', fontWeight: 600, color: 'var(--color-text-primary, #18181b)', margin: 0 }}>
            Have a feature request?
          </h3>
          <p style={{ fontSize: '14px', color: 'var(--color-text-secondary, #71717a)', maxWidth: '480px', margin: 0 }}>
            We build HQLookup based on what our users need. Let us know what workflows or documents you&apos;d like us to support next.
          </p>
          <Link href="/contact" className="btn btn-primary" style={{ fontSize: '13px', textDecoration: 'none', padding: '10px 20px', display: 'inline-flex', alignItems: 'center', gap: '6px', marginTop: '8px' }}>
            Send Feedback <ArrowRight size={14} />
          </Link>
        </div>

      </main>

      <MarketingFooter activePage="roadmap" />
    </div>
  );
}
