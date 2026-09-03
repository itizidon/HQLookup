import Link from "next/link";
import { Building2, ArrowRight } from "lucide-react";

export default function AboutPage() {
  return (
    <div className="screen" style={{ position: 'relative', overflowX: 'hidden', minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      <style>{`
        @media (max-width: 768px) {
          .nav-links {
            display: none !important;
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
            <Link href="/demo" style={{ fontSize: '13px', color: 'var(--color-text-secondary, #71717a)', textDecoration: 'none', fontWeight: 500 }}>
              Demo
            </Link>
            <Link href="/about" style={{ fontSize: '13px', color: 'var(--color-text-primary, #18181b)', textDecoration: 'none', fontWeight: 600 }}>
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
      <main style={{ padding: '48px 24px', maxWidth: '760px', margin: '0 auto', width: '100%', flex: 1, display: 'flex', flexDirection: 'column', gap: '32px' }}>
        
        {/* Header Section */}
        <div>
          <div style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', padding: '4px 10px', borderRadius: '20px', background: 'var(--color-background-secondary, #f4f4f5)', fontSize: '11px', fontWeight: 500, color: 'var(--color-text-secondary, #71717a)', marginBottom: '16px' }}>
            About HQLookup
          </div>
          <h1 style={{ fontSize: '32px', fontWeight: 600, color: 'var(--color-text-primary, #18181b)', marginBottom: '16px', letterSpacing: '-0.02em' }}>
            Making business knowledge easier to find
          </h1>
          <p style={{ fontSize: '15px', color: 'var(--color-text-secondary, #71717a)', lineHeight: '1.6' }}>
            HQLookup is an AI-powered document search and business knowledge platform designed to help teams find answers across the files they already use every day.
          </p>
        </div>

        <div className="card" style={{ padding: '32px', display: 'flex', flexDirection: 'column', gap: '24px' }}>
          <p style={{ fontSize: '14px', color: 'var(--color-text-secondary, #71717a)', lineHeight: '1.6', margin: 0 }}>
            Important business information is often scattered across PDFs, Excel spreadsheets, reports, policies, tables, charts, and other internal documents. Finding one answer can mean opening multiple files, searching through folders, or relying on someone who remembers where the information was stored.
          </p>
          <p style={{ fontSize: '15px', fontWeight: 600, color: 'var(--color-text-primary, #18181b)', margin: 0 }}>
            HQLookup makes that information searchable.
          </p>
          <p style={{ fontSize: '14px', color: 'var(--color-text-secondary, #71717a)', lineHeight: '1.6', margin: 0 }}>
            Upload your business documents, ask questions in plain English, and get answers based on the information contained in your knowledge base.
          </p>
        </div>

        {/* Why we built HQLookup */}
        <section style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <h2 style={{ fontSize: '20px', fontWeight: 600, color: 'var(--color-text-primary, #18181b)' }}>Why we built HQLookup</h2>
          <p style={{ fontSize: '14px', color: 'var(--color-text-secondary, #71717a)', lineHeight: '1.6' }}>
            Modern businesses generate more information than ever, but much of that knowledge remains trapped inside individual files. Traditional file search can help you find a document, but it usually cannot answer questions such as:
          </p>
          <ul style={{ paddingLeft: '20px', display: 'flex', flexDirection: 'column', gap: '8px', fontSize: '14px', color: 'var(--color-text-secondary, #71717a)' }}>
            <li>What does this insurance policy cover?</li>
            <li>What was revenue in March?</li>
            <li>What does this Excel chart show?</li>
            <li>Which documents mention a specific requirement?</li>
          </ul>
          <p style={{ fontSize: '14px', color: 'var(--color-text-secondary, #71717a)', lineHeight: '1.6' }}>
            HQLookup was built to make asking those questions easier. Our goal is to give businesses a simple way to use AI with their own documents without requiring them to build or maintain their own document-processing, search, or retrieval infrastructure.
          </p>
        </section>

        {/* AI search for real business documents */}
        <section style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <h2 style={{ fontSize: '20px', fontWeight: 600, color: 'var(--color-text-primary, #18181b)' }}>AI search for real business documents</h2>
          <p style={{ fontSize: '14px', color: 'var(--color-text-secondary, #71717a)', lineHeight: '1.6' }}>
            Business information rarely arrives in one clean format. HQLookup is designed to search and understand information across common business files, including:
          </p>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '12px' }}>
            {[
              "PDF documents",
              "Excel spreadsheets",
              "Tables and structured data",
              "Spreadsheet charts and visualizations",
              "Word documents",
              "CSV files",
              "Policies, reports, invoices, contracts, and operational records"
            ].map((item, idx) => (
              <div key={idx} style={{ padding: '12px 16px', borderRadius: '8px', background: 'var(--color-background-secondary, #f4f4f5)', fontSize: '13px', color: 'var(--color-text-primary, #18181b)', fontWeight: 500 }}>
                {item}
              </div>
            ))}
          </div>
          <p style={{ fontSize: '14px', color: 'var(--color-text-secondary, #71717a)', lineHeight: '1.6' }}>
            Documents are organized into searchable knowledge bases so teams can ask questions across their information instead of manually reviewing files one by one.
          </p>
        </section>

        {/* Built for businesses, teams, and multiple locations */}
        <section style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <h2 style={{ fontSize: '20px', fontWeight: 600, color: 'var(--color-text-primary, #18181b)' }}>Built for businesses, teams, and multiple locations</h2>
          <p style={{ fontSize: '14px', color: 'var(--color-text-secondary, #71717a)', lineHeight: '1.6' }}>
            HQLookup is designed for organizations that need to keep knowledge organized across different businesses, teams, or locations. Each business can maintain its own document library and searchable knowledge base while still being managed within a larger organization.
          </p>
          <p style={{ fontSize: '14px', color: 'var(--color-text-secondary, #71717a)', lineHeight: '1.6' }}>
            This makes HQLookup useful for document-heavy workflows in industries such as property management, accounting, insurance, real estate, operations, and other businesses that rely heavily on PDFs and spreadsheets.
          </p>
        </section>

        {/* Built with transparency in mind */}
        <section style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <h2 style={{ fontSize: '20px', fontWeight: 600, color: 'var(--color-text-primary, #18181b)' }}>Built with transparency in mind</h2>
          <p style={{ fontSize: '14px', color: 'var(--color-text-secondary, #71717a)', lineHeight: '1.6' }}>
            AI-generated answers are much more useful when users can understand where the information came from. HQLookup is designed to connect answers back to the business documents and source context used to produce them, making it easier to verify important information rather than treating an AI response as a black box.
          </p>
        </section>

        {/* Meet the founder */}
        <section style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <h2 style={{ fontSize: '20px', fontWeight: 600, color: 'var(--color-text-primary, #18181b)' }}>Meet the founder</h2>
          <div className="card" style={{ padding: '24px' }}>
            <h3 style={{ fontSize: '16px', fontWeight: 600, color: 'var(--color-text-primary, #18181b)', marginBottom: '8px' }}>
              Don Ng — Founder & Software Engineer
            </h3>
            <p style={{ fontSize: '14px', color: 'var(--color-text-secondary, #71717a)', lineHeight: '1.6', marginBottom: '16px' }}>
              HQLookup was founded and built by Don Ng, a software engineer with experience building web applications across frontend and backend systems.
            </p>
            <p style={{ fontSize: '14px', color: 'var(--color-text-secondary, #71717a)', lineHeight: '1.6', marginBottom: '16px' }}>
              HQLookup began with a simple idea: businesses already possess valuable knowledge, but accessing that knowledge is unnecessarily difficult when it is spread across dozens or hundreds of documents.
            </p>
            <p style={{ fontSize: '14px', color: 'var(--color-text-secondary, #71717a)', lineHeight: '1.6', margin: 0 }}>
              The product is being built to make that information easier to search, understand, and use.
            </p>
          </div>
        </section>

        {/* What we're building toward */}
        <section style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <h2 style={{ fontSize: '20px', fontWeight: 600, color: 'var(--color-text-primary, #18181b)' }}>What we're building toward</h2>
          <p style={{ fontSize: '14px', color: 'var(--color-text-secondary, #71717a)', lineHeight: '1.6' }}>
            We believe searching business knowledge should eventually feel as natural as asking a question. Instead of remembering which spreadsheet contains a number, which policy contains a coverage limit, or which report contains an important detail, teams should be able to ask the question directly and quickly find the supporting information.
          </p>
          <p style={{ fontSize: '14px', color: 'var(--color-text-secondary, #71717a)', lineHeight: '1.6' }}>
            HQLookup is being built to make that possible across documents, spreadsheets, tables, charts, and the other files businesses already depend on.
          </p>
        </section>

        {/* Call to Action Box */}
        <div className="card" style={{ padding: '32px', textAlign: 'center', background: 'var(--color-background-secondary, #f4f4f5)', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '16px' }}>
          <h3 style={{ fontSize: '20px', fontWeight: 600, color: 'var(--color-text-primary, #18181b)', margin: 0 }}>
            Turn your documents into searchable knowledge
          </h3>
          <p style={{ fontSize: '14px', color: 'var(--color-text-secondary, #71717a)', maxWidth: '480px', margin: 0 }}>
            Upload your first documents and start asking questions across your business knowledge.
          </p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', alignItems: 'center', marginTop: '8px' }}>
            <Link href="/auth?mode=signup" className="btn btn-primary" style={{ fontSize: '13px', textDecoration: 'none', padding: '10px 20px' }}>
              Get Started Free <ArrowRight size={14} style={{ marginLeft: '6px' }} />
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
          <Link href="/demo" style={{ color: 'inherit', textDecoration: 'none' }}>Demo</Link>
          <Link href="/about" style={{ color: 'inherit', textDecoration: 'none', fontWeight: 500 }}>About</Link>
          <Link href="/contact" style={{ color: 'inherit', textDecoration: 'none' }}>Contact</Link>
        </div>
        <div>
          © {new Date().getFullYear()} HQLookup. All rights reserved.
        </div>
      </footer>
    </div>
  );
}