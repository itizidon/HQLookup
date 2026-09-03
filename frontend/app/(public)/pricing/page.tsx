import Link from "next/link";
import { Building2, ArrowRight, CheckCircle2 } from "lucide-react";

export const metadata = {
  title: "HQLookup Pricing | Free & Starter AI Document Search Plans",
  description: "Compare HQLookup pricing plans. Start free with 50 monthly searches or upgrade to Starter for $50/month with 2,000 searches, larger files, more users, and additional business workspaces.",
};

export default function PricingPage() {
  return (
    <div className="screen" style={{ position: 'relative', overflowX: 'hidden', minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      <style>{`
        @media (max-width: 768px) {
          .nav-links {
            display: none !important;
          }
          .pricing-grid {
            grid-template-columns: 1fr !important;
          }
          .comparison-table {
            display: block;
            overflow-x: auto;
          }
        }
      `}</style>

      {/* Top Header */}
      <header style={{ borderBottom: '1px solid var(--color-border-tertiary, #e4e4e7)', background: 'var(--color-background-primary, #ffffff)', padding: '16px 24px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '24px' }}>
          <Link href="/" style={{ display: 'flex', alignItems: 'center', gap: '8px', textDecoration: 'none' }}>
            <div style={{ padding: '6px', borderRadius: '6px', background: 'var(--color-background-secondary, #f4f4f5)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--color-text-primary, #18181b)' }}>
              <Building2 size={18} />
            </div>
            <span style={{ fontSize: '16px', fontWeight: 600, color: 'var(--color-text-primary, #18181b)' }}>HQLookup</span>
          </Link>

          <nav className="nav-links" style={{ display: 'flex', alignItems: 'center', gap: '20px' }}>
            <Link href="/features" style={{ fontSize: '13px', color: 'var(--color-text-secondary, #71717a)', textDecoration: 'none', fontWeight: 500 }}>
              Features
            </Link>
            <Link href="/pricing" style={{ fontSize: '13px', color: 'var(--color-text-primary, #18181b)', textDecoration: 'none', fontWeight: 600 }}>
              Pricing
            </Link>
            <Link href="/solutions" style={{ fontSize: '13px', color: 'var(--color-text-secondary, #71717a)', textDecoration: 'none', fontWeight: 500 }}>
              Solutions
            </Link>
            <Link href="/demo" style={{ fontSize: '13px', color: 'var(--color-text-secondary, #71717a)', textDecoration: 'none', fontWeight: 500 }}>
              Demo
            </Link>
            <Link href="/about" style={{ fontSize: '13px', color: 'var(--color-text-secondary, #71717a)', textDecoration: 'none', fontWeight: 500 }}>
              About
            </Link>
            <Link href="/contact" style={{ fontSize: '13px', color: 'var(--color-text-secondary, #71717a)', textDecoration: 'none', fontWeight: 500 }}>
              Contact
            </Link>
          </nav>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <Link href="/auth" className="btn btn-secondary" style={{ fontSize: '13px', textDecoration: 'none' }}>
            Sign in
          </Link>
          <Link href="/demo" className="btn btn-primary" style={{ fontSize: '13px', textDecoration: 'none' }}>
            Get a Demo <ArrowRight size={14} style={{ marginLeft: '4px' }} />
          </Link>
        </div>
      </header>

      {/* Main Content Area */}
      <main style={{ padding: '48px 24px', maxWidth: '840px', margin: '0 auto', width: '100%', flex: 1, display: 'flex', flexDirection: 'column', gap: '48px' }}>
        
        {/* Hero Section */}
        <div style={{ textAlign: 'center', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '16px' }}>
          <div style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', padding: '4px 10px', borderRadius: '20px', background: 'var(--color-background-secondary, #f4f4f5)', fontSize: '11px', fontWeight: 500, color: 'var(--color-text-secondary, #71717a)' }}>
            Simple Pricing
          </div>
          <h1 style={{ fontSize: '32px', fontWeight: 600, color: 'var(--color-text-primary, #18181b)', letterSpacing: '-0.02em', lineHeight: '1.2' }}>
            Simple pricing that grows with your business
          </h1>
          <p style={{ fontSize: '15px', color: 'var(--color-text-secondary, #71717a)', lineHeight: '1.6', maxWidth: '600px' }}>
            Start free and upgrade when you need more searches, larger files, more users, or additional business workspaces. HQLookup helps you search across PDFs, Excel spreadsheets, tables, charts, reports, policies, and other business documents using AI.
          </p>
          <span style={{ fontSize: '12px', color: 'var(--color-text-secondary, #71717a)' }}>No credit card required to get started.</span>
        </div>

        {/* Pricing Cards Grid */}
        <div className="pricing-grid" style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '20px', alignItems: 'stretch' }}>
          
          {/* Free Plan */}
          <div className="card" style={{ padding: '32px', display: 'flex', flexDirection: 'column', gap: '24px', justifyContent: 'space-between' }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <div>
                <h3 style={{ fontSize: '18px', fontWeight: 600, color: 'var(--color-text-primary, #18181b)', marginBottom: '4px' }}>Free</h3>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: '4px' }}>
                  <span style={{ fontSize: '32px', fontWeight: 700, color: 'var(--color-text-primary, #18181b)' }}>$0</span>
                  <span style={{ fontSize: '13px', color: 'var(--color-text-secondary)' }}>/ month</span>
                </div>
                <p style={{ fontSize: '13px', color: 'var(--color-text-secondary, #71717a)', marginTop: '8px' }}>
                  For individuals and small teams who want to try HQLookup with real business documents.
                </p>
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', borderTop: '1px solid var(--color-border-tertiary, #e4e4e7)', paddingTop: '16px' }}>
                {[
                  "50 searches per month",
                  "1 business workspace",
                  "Up to 2 users",
                  "1 organization",
                  "Spreadsheet support up to 500 rows",
                  "Files up to 5 MB",
                  "AI-powered document search",
                  "PDF & Excel support",
                  "Table & chart understanding",
                  "Source-backed answers",
                  "Multi-query search & HyDE retrieval"
                ].map((feature, idx) => (
                  <div key={idx} style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px', color: 'var(--color-text-primary, #18181b)' }}>
                    <CheckCircle2 size={14} style={{ color: '#10b981', flexShrink: 0 }} />
                    {feature}
                  </div>
                ))}
              </div>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <Link href="/auth?mode=signup" className="btn btn-secondary" style={{ fontSize: '13px', textDecoration: 'none', padding: '10px 20px', textAlign: 'center', width: '100%', boxSizing: 'border-box' }}>
                Start Free →
              </Link>
              <span style={{ fontSize: '11px', color: 'var(--color-text-secondary, #71717a)', textAlign: 'center' }}>No credit card required.</span>
            </div>
          </div>

          {/* Starter Plan */}
          <div className="card" style={{ padding: '32px', display: 'flex', flexDirection: 'column', gap: '24px', justifyContent: 'space-between', border: '1px solid var(--color-text-primary, #18181b)' }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                  <h3 style={{ fontSize: '18px', fontWeight: 600, color: 'var(--color-text-primary, #18181b)', margin: 0 }}>Starter</h3>
                  <span style={{ fontSize: '11px', fontWeight: 500, background: 'var(--color-background-secondary, #f4f4f5)', padding: '2px 8px', borderRadius: '12px', color: 'var(--color-text-secondary)' }}>Popular</span>
                </div>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: '4px' }}>
                  <span style={{ fontSize: '32px', fontWeight: 700, color: 'var(--color-text-primary, #18181b)' }}>$50</span>
                  <span style={{ fontSize: '13px', color: 'var(--color-text-secondary)' }}>/ month</span>
                </div>
                <p style={{ fontSize: '13px', color: 'var(--color-text-secondary, #71717a)', marginTop: '8px' }}>
                  For businesses that need significantly more search capacity and room to grow.
                </p>
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', borderTop: '1px solid var(--color-border-tertiary, #e4e4e7)', paddingTop: '16px' }}>
                {[
                  "2,000 searches per month",
                  "Up to 3 business workspaces",
                  "Up to 10 users",
                  "1 organization",
                  "Spreadsheet support up to 1,000 rows",
                  "Files up to 10 MB",
                  "AI-powered document search",
                  "PDF & Excel support",
                  "Table & chart understanding",
                  "Source-backed answers",
                  "Multi-query search & HyDE retrieval"
                ].map((feature, idx) => (
                  <div key={idx} style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px', color: 'var(--color-text-primary, #18181b)' }}>
                    <CheckCircle2 size={14} style={{ color: '#10b981', flexShrink: 0 }} />
                    {feature}
                  </div>
                ))}
              </div>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <Link href="/auth?mode=signup" className="btn btn-primary" style={{ fontSize: '13px', textDecoration: 'none', padding: '10px 20px', textAlign: 'center', width: '100%', boxSizing: 'border-box' }}>
                Upgrade to Starter →
              </Link>
              <span style={{ fontSize: '11px', color: 'transparent', textAlign: 'center' }}>&nbsp;</span>
            </div>
          </div>

        </div>

        {/* Compare Plans Table */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <h2 style={{ fontSize: '20px', fontWeight: 600, color: 'var(--color-text-primary, #18181b)' }}>Compare plans</h2>
          
          <div className="card" style={{ overflow: 'hidden', padding: 0 }}>
            <table className="comparison-table" style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px', textAlign: 'left' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--color-border-tertiary, #e4e4e7)', background: 'var(--color-background-secondary, #f4f4f5)' }}>
                  <th style={{ padding: '14px 16px', fontWeight: 600, color: 'var(--color-text-primary)' }}>Feature</th>
                  <th style={{ padding: '14px 16px', fontWeight: 600, color: 'var(--color-text-primary)', width: '120px', textAlign: 'center' }}>Free</th>
                  <th style={{ padding: '14px 16px', fontWeight: 600, color: 'var(--color-text-primary)', width: '120px', textAlign: 'center' }}>Starter</th>
                </tr>
              </thead>
              <tbody>
                {[
                  { feature: "Price", free: "$0", starter: "$50/month" },
                  { feature: "Searches per month", free: "50", starter: "2,000" },
                  { feature: "Business workspaces", free: "1", starter: "3" },
                  { feature: "Users", free: "2", starter: "10" },
                  { feature: "Organizations", free: "1", starter: "1" },
                  { feature: "Spreadsheet row limit", free: "500", starter: "1,000" },
                  { feature: "Maximum file size", free: "5 MB", starter: "10 MB" },
                  { feature: "PDF search", free: "✓", starter: "✓" },
                  { feature: "Excel search", free: "✓", starter: "✓" },
                  { feature: "Table & chart understanding", free: "✓", starter: "✓" },
                  { feature: "Source-backed answers", free: "✓", starter: "✓" },
                  { feature: "Multi-query retrieval", free: "✓", starter: "✓" },
                  { feature: "HyDE retrieval", free: "✓", starter: "✓" },
                ].map((row, idx) => (
                  <tr key={idx} style={{ borderBottom: idx < 12 ? '1px solid var(--color-border-tertiary, #e4e4e7)' : 'none' }}>
                    <td style={{ padding: '12px 16px', color: 'var(--color-text-primary)' }}>{row.feature}</td>
                    <td style={{ padding: '12px 16px', color: 'var(--color-text-secondary)', textAlign: 'center' }}>{row.free}</td>
                    <td style={{ padding: '12px 16px', color: 'var(--color-text-secondary)', textAlign: 'center' }}>{row.starter}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Same core AI search note */}
        <div className="card" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <h3 style={{ fontSize: '16px', fontWeight: 600, color: 'var(--color-text-primary, #18181b)', margin: 0 }}>
            Same core AI search on every plan
          </h3>
          <p style={{ fontSize: '13px', color: 'var(--color-text-secondary, #71717a)', lineHeight: '1.5', margin: 0 }}>
            Both Free and Starter use the same core search technology. Free users are not given a lower-quality version of HQLookup. The Starter plan increases your usage limits, file capacity, users, and business workspaces.
          </p>
        </div>

        {/* Frequently Asked Questions */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <h2 style={{ fontSize: '20px', fontWeight: 600, color: 'var(--color-text-primary, #18181b)' }}>Frequently asked questions</h2>
          
          <div style={{ display: 'grid', gridTemplateColumns: '1fr', gap: '12px' }}>
            {[
              { q: "Can I use HQLookup for free?", a: "Yes. The Free plan includes 50 searches per month, one business workspace, and support for up to two users." },
              { q: "Do I need a credit card to start?", a: "No. You can start with the Free plan without entering a credit card." },
              { q: "What happens when I reach 50 searches?", a: "You can upgrade to Starter for up to 2,000 searches per month." },
              { q: "How many users can I have?", a: "The Free plan supports up to 2 users. Starter supports up to 10 users." },
              { q: "Can I manage multiple businesses?", a: "Yes. Free supports one business workspace, while Starter supports up to three." },
              { q: "What is the spreadsheet row limit?", a: "Free supports spreadsheets up to 500 rows. Starter supports up to 1,000 rows." },
              { q: "What is the maximum file size?", a: "Free supports files up to 5 MB. Starter supports files up to 10 MB." },
              { q: "Does Starter use a better AI model?", a: "No. Both plans use the same core AI search and retrieval features. Starter primarily gives you higher limits." }
            ].map((faq, idx) => (
              <div key={idx} className="card" style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: '6px' }}>
                <h4 style={{ fontSize: '14px', fontWeight: 600, color: 'var(--color-text-primary, #18181b)', margin: 0 }}>{faq.q}</h4>
                <p style={{ fontSize: '13px', color: 'var(--color-text-secondary, #71717a)', lineHeight: '1.5', margin: 0 }}>{faq.a}</p>
              </div>
            ))}
          </div>
        </div>

        {/* Call to Action Box */}
        <div className="card" style={{ padding: '32px', textAlign: 'center', background: 'var(--color-background-secondary, #f4f4f5)', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '16px' }}>
          <h3 style={{ fontSize: '20px', fontWeight: 600, color: 'var(--color-text-primary, #18181b)', margin: 0 }}>
            Start searching your business documents
          </h3>
          <p style={{ fontSize: '14px', color: 'var(--color-text-secondary, #71717a)', maxWidth: '480px', margin: 0 }}>
            Turn PDFs, spreadsheets, reports, policies, and other business files into searchable knowledge.
          </p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', alignItems: 'center', marginTop: '8px' }}>
            <Link href="/auth?mode=signup" className="btn btn-primary" style={{ fontSize: '13px', textDecoration: 'none', padding: '10px 20px', display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
              Start Free <ArrowRight size={14} />
            </Link>
            <span style={{ fontSize: '11px', color: 'var(--color-text-secondary, #71717a)' }}>No credit card required.</span>
          </div>
        </div>

      </main>

      {/* Footer */}
      <footer style={{ borderTop: '1px solid var(--color-border-tertiary, #e4e4e7)', padding: '24px', display: 'flex', flexDirection: 'column', gap: '12px', alignItems: 'center', fontSize: '12px', color: 'var(--color-text-secondary, #71717a)', background: 'var(--color-background-primary, #ffffff)' }}>
        <div style={{ display: 'flex', gap: '20px', flexWrap: 'wrap', justifyContent: 'center' }}>
          <Link href="/features" style={{ color: 'inherit', textDecoration: 'none' }}>Features</Link>
          <Link href="/pricing" style={{ color: 'inherit', textDecoration: 'none', fontWeight: 500 }}>Pricing</Link>
          <Link href="/solutions" style={{ color: 'inherit', textDecoration: 'none' }}>Solutions</Link>
          <Link href="/demo" style={{ color: 'inherit', textDecoration: 'none' }}>Demo</Link>
          <Link href="/about" style={{ color: 'inherit', textDecoration: 'none' }}>About</Link>
          <Link href="/contact" style={{ color: 'inherit', textDecoration: 'none' }}>Contact</Link>
        </div>
        <div>
          © {new Date().getFullYear()} HQLookup. All rights reserved.
        </div>
      </footer>
    </div>
  );
}