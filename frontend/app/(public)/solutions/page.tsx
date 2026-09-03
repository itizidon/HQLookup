import Link from "next/link";
import { Building2, ArrowRight, Home, Calculator, Shield, Building, Briefcase, FileText, Database, Layers, CheckCircle2, Search } from "lucide-react";

export default function SolutionsPage() {
  return (
    <div className="screen" style={{ position: 'relative', overflowX: 'hidden', minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      <style>{`
        @media (max-width: 768px) {
          .nav-links {
            display: none !important;
          }
          .solutions-grid {
            grid-template-columns: 1fr !important;
          }
          .formats-grid {
            grid-template-columns: 1fr !important;
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
            <Link href="/pricing" style={{ fontSize: '13px', color: 'var(--color-text-secondary, #71717a)', textDecoration: 'none', fontWeight: 500 }}>
              Pricing
            </Link>
            <Link href="/solutions" style={{ fontSize: '13px', color: 'var(--color-text-primary, #18181b)', textDecoration: 'none', fontWeight: 600 }}>
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
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <div style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', padding: '4px 10px', borderRadius: '20px', background: 'var(--color-background-secondary, #f4f4f5)', fontSize: '11px', fontWeight: 500, color: 'var(--color-text-secondary, #71717a)', width: 'fit-content' }}>
            Solutions
          </div>
          <h1 style={{ fontSize: '32px', fontWeight: 600, color: 'var(--color-text-primary, #18181b)', letterSpacing: '-0.02em', lineHeight: '1.2' }}>
            AI document search built for real business workflows
          </h1>
          <p style={{ fontSize: '15px', color: 'var(--color-text-secondary, #71717a)', lineHeight: '1.6' }}>
            HQLookup helps businesses search across PDFs, Excel spreadsheets, reports, policies, contracts, tables, charts, and other internal documents using natural language.
          </p>
          <p style={{ fontSize: '14px', color: 'var(--color-text-secondary, #71717a)', lineHeight: '1.6' }}>
            Instead of manually digging through files, teams can upload their business documents, ask questions, and get answers grounded in the information they already have. Whether you manage properties, financial records, insurance policies, operational documents, or information across multiple locations, HQLookup helps turn scattered files into searchable business knowledge.
          </p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', marginTop: '8px' }}>
            <Link href="/auth?mode=signup" className="btn btn-primary" style={{ fontSize: '13px', textDecoration: 'none', padding: '10px 20px', width: 'fit-content', display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
              Get Started Free <ArrowRight size={14} />
            </Link>
            <span style={{ fontSize: '11px', color: 'var(--color-text-secondary, #71717a)' }}>No credit card required.</span>
          </div>
        </div>

        {/* Industry Solutions Section */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
          <div>
            <h2 style={{ fontSize: '22px', fontWeight: 600, color: 'var(--color-text-primary, #18181b)', marginBottom: '8px' }}>
              Built for document-heavy teams
            </h2>
            <p style={{ fontSize: '14px', color: 'var(--color-text-secondary, #71717a)' }}>
              Business knowledge rarely lives in one place. HQLookup brings information together into a searchable knowledge base so teams can find answers faster.
            </p>
          </div>

          <div className="solutions-grid" style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '16px' }}>
            
            {/* Property Management */}
            <div className="card" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '16px', fontWeight: 600, color: 'var(--color-text-primary, #18181b)' }}>
                <Home size={18} style={{ color: 'var(--color-text-secondary)' }} />
                Property Management
              </div>
              <p style={{ fontSize: '13px', color: 'var(--color-text-secondary, #71717a)', lineHeight: '1.5', margin: 0 }}>
                Search across leases, maintenance records, inspection reports, invoices, insurance documents, rent rolls, and property records.
              </p>
              <div style={{ fontSize: '12px', color: 'var(--color-text-secondary, #71717a)', background: 'var(--color-background-secondary, #f4f4f5)', padding: '12px', borderRadius: '8px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
                <strong style={{ color: 'var(--color-text-primary, #18181b)', marginBottom: '2px', display: 'block' }}>Example questions:</strong>
                <span>• Which leases expire soon?</span>
                <span>• How much did we spend on repairs?</span>
                <span>• What insurance coverage does this property have?</span>
                <span>• Which documents mention a specific tenant?</span>
              </div>
            </div>

            {/* Accounting & Bookkeeping */}
            <div className="card" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '16px', fontWeight: 600, color: 'var(--color-text-primary, #18181b)' }}>
                <Calculator size={18} style={{ color: 'var(--color-text-secondary)' }} />
                Accounting & Bookkeeping
              </div>
              <p style={{ fontSize: '13px', color: 'var(--color-text-secondary, #71717a)', lineHeight: '1.5', margin: 0 }}>
                Search client documents, financial reports, invoices, expense spreadsheets, statements, and other accounting records without opening files one by one.
              </p>
              <div style={{ fontSize: '12px', color: 'var(--color-text-secondary, #71717a)', background: 'var(--color-background-secondary, #f4f4f5)', padding: '12px', borderRadius: '8px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
                <strong style={{ color: 'var(--color-text-primary, #18181b)', marginBottom: '2px', display: 'block' }}>Example questions:</strong>
                <span>• What were this client's largest expenses?</span>
                <span>• Which invoices are still outstanding?</span>
                <span>• How did expenses change month over month?</span>
                <span>• What does this spreadsheet chart show?</span>
              </div>
            </div>

            {/* Insurance */}
            <div className="card" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '16px', fontWeight: 600, color: 'var(--color-text-primary, #18181b)' }}>
                <Shield size={18} style={{ color: 'var(--color-text-secondary)' }} />
                Insurance
              </div>
              <p style={{ fontSize: '13px', color: 'var(--color-text-secondary, #71717a)', lineHeight: '1.5', margin: 0 }}>
                Make insurance documents easier to search and understand across policies, quotes, endorsements, coverage documents, and supporting records.
              </p>
              <div style={{ fontSize: '12px', color: 'var(--color-text-secondary, #71717a)', background: 'var(--color-background-secondary, #f4f4f5)', padding: '12px', borderRadius: '8px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
                <strong style={{ color: 'var(--color-text-primary, #18181b)', marginBottom: '2px', display: 'block' }}>Example questions:</strong>
                <span>• What is the liability coverage limit?</span>
                <span>• What deductible applies?</span>
                <span>• When does this policy expire?</span>
                <span>• What exclusions are listed?</span>
              </div>
            </div>

            {/* Real Estate */}
            <div className="card" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '16px', fontWeight: 600, color: 'var(--color-text-primary, #18181b)' }}>
                <Building size={18} style={{ color: 'var(--color-text-secondary)' }} />
                Real Estate
              </div>
              <p style={{ fontSize: '13px', color: 'var(--color-text-secondary, #71717a)', lineHeight: '1.5', margin: 0 }}>
                Search across property documents, leases, financial spreadsheets, inspection reports, insurance policies, contracts, and other records.
              </p>
              <div style={{ fontSize: '12px', color: 'var(--color-text-secondary, #71717a)', background: 'var(--color-background-secondary, #f4f4f5)', padding: '12px', borderRadius: '8px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
                <strong style={{ color: 'var(--color-text-primary, #18181b)', marginBottom: '2px', display: 'block' }}>Example questions:</strong>
                <span>• When does this lease expire?</span>
                <span>• What expenses are associated with this property?</span>
                <span>• What does the insurance policy cover?</span>
                <span>• Which properties have upcoming renewals?</span>
              </div>
            </div>

          </div>

          {/* Business Operations (Full width card) */}
          <div className="card" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '16px', fontWeight: 600, color: 'var(--color-text-primary, #18181b)' }}>
              <Briefcase size={18} style={{ color: 'var(--color-text-secondary)' }} />
              Business Operations & Multi-Branch Enterprises
            </div>
            <p style={{ fontSize: '13px', color: 'var(--color-text-secondary, #71717a)', lineHeight: '1.5', margin: 0 }}>
              Turn internal documents into a searchable knowledge base for day-to-day operations. Search SOPs, policies, reports, spreadsheets, internal documentation, vendor agreements, and operational records.
            </p>
            <div style={{ fontSize: '12px', color: 'var(--color-text-secondary, #71717a)', background: 'var(--color-background-secondary, #f4f4f5)', padding: '12px', borderRadius: '8px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
              <strong style={{ color: 'var(--color-text-primary, #18181b)', marginBottom: '2px', display: 'block' }}>Example questions:</strong>
              <span>• What is our policy for this situation?</span>
              <span>• Which vendor agreement contains this requirement?</span>
              <span>• What were the key findings in this report?</span>
              <span>• Where is this process documented?</span>
            </div>
          </div>

        </div>

        {/* Feature Capabilities Breakdown */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
          <div>
            <h2 style={{ fontSize: '22px', fontWeight: 600, color: 'var(--color-text-primary, #18181b)', marginBottom: '8px' }}>
              Search more than PDFs
            </h2>
            <p style={{ fontSize: '14px', color: 'var(--color-text-secondary, #71717a)' }}>
              Business information comes in many formats. HQLookup is designed to work with the files businesses already use without requiring you to reorganize your information beforehand.
            </p>
          </div>

          <div className="formats-grid" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '12px' }}>
            {[
              "PDF documents",
              "Excel spreadsheets",
              "Tables and structured data",
              "Charts and visualizations",
              "Word documents",
              "CSV files",
              "Reports and policies",
              "Contracts and invoices",
              "Operational records"
            ].map((format, idx) => (
              <div key={idx} style={{ padding: '12px 16px', borderRadius: '8px', background: 'var(--color-background-secondary, #f4f4f5)', fontSize: '13px', color: 'var(--color-text-primary, #18181b)', fontWeight: 500, display: 'flex', alignItems: 'center', gap: '8px' }}>
                <CheckCircle2 size={14} style={{ color: '#10b981', flexShrink: 0 }} />
                {format}
              </div>
            ))}
          </div>
        </div>

        {/* Spreadsheets and Charts Section */}
        <div className="card" style={{ padding: '32px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <h3 style={{ fontSize: '18px', fontWeight: 600, color: 'var(--color-text-primary, #18181b)', margin: 0 }}>
            Understand spreadsheets and charts
          </h3>
          <p style={{ fontSize: '14px', color: 'var(--color-text-secondary, #71717a)', lineHeight: '1.6', margin: 0 }}>
            Traditional document search often stops at text. HQLookup is designed to work with structured spreadsheet information including tables, rows, and charts, making it easier to ask questions about the numbers stored inside business workbooks.
          </p>
          <div style={{ fontSize: '13px', color: 'var(--color-text-secondary, #71717a)', background: 'var(--color-background-secondary, #f4f4f5)', padding: '16px', borderRadius: '8px', display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <strong style={{ color: 'var(--color-text-primary, #18181b)', marginBottom: '4px', display: 'block' }}>Ask questions such as:</strong>
            <span>• What was revenue in March?</span>
            <span>• Which month had the highest expenses?</span>
            <span>• What does the Monthly Revenue vs Expenses chart show?</span>
            <span>• How did these numbers change over time?</span>
          </div>
        </div>

        {/* Multi-document & Verification Section */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: '16px' }}>
          <div className="card" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
            <h4 style={{ fontSize: '16px', fontWeight: 600, color: 'var(--color-text-primary, #18181b)', margin: 0 }}>
              Search across multiple documents
            </h4>
            <p style={{ fontSize: '13px', color: 'var(--color-text-secondary, #71717a)', lineHeight: '1.5', margin: 0 }}>
              Business questions often require information spread across multiple files. Instead of wondering <em style={{ color: 'var(--color-text-primary)' }}>"Which file was that information in?"</em> you can start directly with <em style={{ color: 'var(--color-text-primary)' }}>"What do our documents say about this?"</em>
            </p>
          </div>

          <div className="card" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
            <h4 style={{ fontSize: '16px', fontWeight: 600, color: 'var(--color-text-primary, #18181b)', margin: 0 }}>
              Answers you can verify
            </h4>
            <p style={{ fontSize: '13px', color: 'var(--color-text-secondary, #71717a)', lineHeight: '1.5', margin: 0 }}>
              AI is more useful when you can understand where an answer came from. HQLookup returns answers alongside supporting source information so you can verify critical details against original business files.
            </p>
          </div>
        </div>

        {/* How HQLookup Works */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
          <h3 style={{ fontSize: '20px', fontWeight: 600, color: 'var(--color-text-primary, #18181b)' }}>
            How HQLookup works
          </h3>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '12px' }}>
            {[
              { step: "1", title: "Upload your documents", desc: "Add PDFs, spreadsheets, reports, policies, and contracts." },
              { step: "2", title: "Build knowledge base", desc: "HQLookup processes your files and makes information searchable." },
              { step: "3", title: "Ask questions", desc: "Ask questions in plain English instead of searching files manually." },
              { step: "4", title: "Review sources", desc: "Use supporting document context to verify where answers came from." }
            ].map((item, idx) => (
              <div key={idx} className="card" style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                <span style={{ fontSize: '12px', fontWeight: 600, color: 'var(--color-text-secondary)', background: 'var(--color-background-secondary)', width: '24px', height: '24px', borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  {item.step}
                </span>
                <h4 style={{ fontSize: '14px', fontWeight: 600, color: 'var(--color-text-primary, #18181b)', margin: 0 }}>{item.title}</h4>
                <p style={{ fontSize: '12px', color: 'var(--color-text-secondary, #71717a)', lineHeight: '1.4', margin: 0 }}>{item.desc}</p>
              </div>
            ))}
          </div>
        </div>

        {/* Call to Action Box */}
        <div className="card" style={{ padding: '32px', textAlign: 'center', background: 'var(--color-background-secondary, #f4f4f5)', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '16px' }}>
          <h3 style={{ fontSize: '20px', fontWeight: 600, color: 'var(--color-text-primary, #18181b)', margin: 0 }}>
            Find the information your business already has
          </h3>
          <p style={{ fontSize: '14px', color: 'var(--color-text-secondary, #71717a)', maxWidth: '480px', margin: 0 }}>
            Your team shouldn't have to remember which folder or spreadsheet contains the answer. Turn existing documents into searchable business knowledge.
          </p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', alignItems: 'center', marginTop: '8px' }}>
            <Link href="/auth?mode=signup" className="btn btn-primary" style={{ fontSize: '13px', textDecoration: 'none', padding: '10px 20px', display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
              Get Started Free <ArrowRight size={14} />
            </Link>
            <span style={{ fontSize: '11px', color: 'var(--color-text-secondary, #71717a)' }}>No credit card required.</span>
          </div>
        </div>

      </main>

      {/* Footer */}
      <footer style={{ borderTop: '1px solid var(--color-border-tertiary, #e4e4e7)', padding: '24px', display: 'flex', flexDirection: 'column', gap: '12px', alignItems: 'center', fontSize: '12px', color: 'var(--color-text-secondary, #71717a)', background: 'var(--color-background-primary, #ffffff)' }}>
        <div style={{ display: 'flex', gap: '20px', flexWrap: 'wrap', justifyContent: 'center' }}>
          <Link href="/features" style={{ color: 'inherit', textDecoration: 'none' }}>Features</Link>
          <Link href="/pricing" style={{ color: 'inherit', textDecoration: 'none' }}>Pricing</Link>
          <Link href="/solutions" style={{ color: 'inherit', textDecoration: 'none', fontWeight: 500 }}>Solutions</Link>
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