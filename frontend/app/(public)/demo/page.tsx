import Link from "next/link";
import Image from "next/image";
import { ArrowRight, PlayCircle, PlusCircle, FileUp, Sliders, MessageSquareCode } from "lucide-react";
import { MarketingFooter, MarketingHeader } from "@/components/MarketingNavigation";
import answerImage from "@/assets/answer.png";
import ingestImage from "@/assets/ingest.png";
import newBusinessImage from "@/assets/new_business_with_card.png";
import selectFilesImage from "@/assets/select_files.png";

export const metadata = {
  title: "Interactive Demo | HQLookup",
  description: "Step-by-step walkthrough showing how to create a business, upload documents, configure ingestion notes, and query your knowledge base.",
};

export default function DemoPage() {
  return (
    <div className="screen" style={{ position: 'relative', overflowX: 'hidden', minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      <MarketingHeader activePage="demo" />

      {/* Main Content Area */}
      <main style={{ padding: '36px 24px', maxWidth: '800px', margin: '0 auto', width: '100%', flex: 1, display: 'flex', flexDirection: 'column', gap: '32px' }}>
        
        {/* Hero Section */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', textAlign: 'center', alignItems: 'center' }}>
          <div style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', padding: '4px 10px', borderRadius: '20px', background: 'var(--color-background-secondary, #f4f4f5)', fontSize: '11px', fontWeight: 500, color: 'var(--color-text-secondary, #71717a)' }}>
            <PlayCircle size={12} /> Step-by-Step Walkthrough
          </div>
          <h1 style={{ fontSize: '28px', fontWeight: 600, color: 'var(--color-text-primary, #18181b)', letterSpacing: '-0.02em', lineHeight: '1.2', margin: 0 }}>
            How to ingest documents and query your business
          </h1>
          <p style={{ fontSize: '14px', color: 'var(--color-text-secondary, #71717a)', lineHeight: '1.5', maxWidth: '600px', margin: 0 }}>
            Follow this clear visual guide from setting up your business location and selecting files to configuring spreadsheet notes and asking natural language questions.
          </p>
        </div>

        {/* Step-by-Step Walkthrough Container with tighter spacing */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px', position: 'relative' }}>
          
          {/* Step 1 */}
          <div className="card" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '16px', border: '1px solid var(--color-border-tertiary, #e4e4e7)', position: 'relative' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '8px', borderBottom: '1px solid var(--color-border-tertiary, #e4e4e7)', paddingBottom: '12px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <span style={{ fontSize: '12px', fontWeight: 700, color: '#ffffff', background: 'var(--color-text-primary, #18181b)', width: '24px', height: '24px', borderRadius: '6px', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                  01
                </span>
                <span style={{ fontSize: '11px', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--color-text-secondary, #71717a)' }}>
                  Workspace Setup
                </span>
              </div>
              <div style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', fontSize: '11px', fontWeight: 500, color: 'var(--color-text-secondary)', background: 'var(--color-background-secondary)', padding: '3px 8px', borderRadius: '6px' }}>
                <PlusCircle size={12} /> Organization & Branch Creation
              </div>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <h3 style={{ fontSize: '16px', fontWeight: 600, color: 'var(--color-text-primary, #18181b)', margin: 0 }}>
                Create a New Business or Location
              </h3>
              <p style={{ fontSize: '13px', color: 'var(--color-text-secondary, #71717a)', margin: 0, lineHeight: '1.4' }}>
                Start from your main dashboard overview to track active instances, query pools, and spin up new branches.
              </p>
            </div>

            <div style={{ borderRadius: '8px', overflow: 'hidden', border: '1px solid var(--color-border-tertiary, #e4e4e7)', background: '#ffffff', boxShadow: '0 1px 3px rgba(0,0,0,0.02)' }}>
              <Image src={newBusinessImage} alt="HQ Lookup dashboard showing New Business action and monthly usage quotas" sizes="(max-width: 800px) calc(100vw - 80px), 720px" style={{ width: '100%', height: 'auto', display: 'block' }} />
            </div>
          </div>

          {/* Step Divider */}
          <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', color: 'var(--color-text-secondary)', opacity: 0.4, height: '8px' }}>
            <div style={{ height: '16px', width: '2px', background: 'var(--color-border-tertiary, #e4e4e7)' }}></div>
          </div>

          {/* Step 2 */}
          <div className="card" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '16px', border: '1px solid var(--color-border-tertiary, #e4e4e7)', position: 'relative' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '8px', borderBottom: '1px solid var(--color-border-tertiary, #e4e4e7)', paddingBottom: '12px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <span style={{ fontSize: '12px', fontWeight: 700, color: '#ffffff', background: 'var(--color-text-primary, #18181b)', width: '24px', height: '24px', borderRadius: '6px', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                  02
                </span>
                <span style={{ fontSize: '11px', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--color-text-secondary, #71717a)' }}>
                  Document Staging
                </span>
              </div>
              <div style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', fontSize: '11px', fontWeight: 500, color: 'var(--color-text-secondary)', background: 'var(--color-background-secondary)', padding: '3px 8px', borderRadius: '6px' }}>
                <FileUp size={12} /> Knowledge Base Library
              </div>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <h3 style={{ fontSize: '16px', fontWeight: 600, color: 'var(--color-text-primary, #18181b)', margin: 0 }}>
                Select Files for Your Knowledge Base
              </h3>
              <p style={{ fontSize: '13px', color: 'var(--color-text-secondary, #71717a)', margin: 0, lineHeight: '1.4' }}>
                Navigate to your location&apos;s document library tab and click <strong style={{ color: 'var(--color-text-primary)' }}>Select Files</strong> to upload spreadsheets or reports.
              </p>
            </div>

            <div style={{ borderRadius: '8px', overflow: 'hidden', border: '1px solid var(--color-border-tertiary, #e4e4e7)', background: '#ffffff', boxShadow: '0 1px 3px rgba(0,0,0,0.02)' }}>
              <Image src={selectFilesImage} alt="Location document library view with Select Files button" sizes="(max-width: 800px) calc(100vw - 80px), 720px" style={{ width: '100%', height: 'auto', display: 'block' }} />
            </div>
          </div>

          {/* Step Divider */}
          <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', color: 'var(--color-text-secondary)', opacity: 0.4, height: '8px' }}>
            <div style={{ height: '16px', width: '2px', background: 'var(--color-border-tertiary, #e4e4e7)' }}></div>
          </div>

          {/* Step 3 */}
          <div className="card" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '16px', border: '1px solid var(--color-border-tertiary, #e4e4e7)', position: 'relative' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '8px', borderBottom: '1px solid var(--color-border-tertiary, #e4e4e7)', paddingBottom: '12px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <span style={{ fontSize: '12px', fontWeight: 700, color: '#ffffff', background: 'var(--color-text-primary, #18181b)', width: '24px', height: '24px', borderRadius: '6px', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                  03
                </span>
                <span style={{ fontSize: '11px', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--color-text-secondary, #71717a)' }}>
                  AI Context Configuration
                </span>
              </div>
              <div style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', fontSize: '11px', fontWeight: 500, color: 'var(--color-text-secondary)', background: 'var(--color-background-secondary)', padding: '3px 8px', borderRadius: '6px' }}>
                <Sliders size={12} /> Ingestion Notes & Presets
              </div>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <h3 style={{ fontSize: '16px', fontWeight: 600, color: 'var(--color-text-primary, #18181b)', margin: 0 }}>
                Configure Ingestion Notes & Presets
              </h3>
              <p style={{ fontSize: '13px', color: 'var(--color-text-secondary, #71717a)', margin: 0, lineHeight: '1.4' }}>
                Provide optional context or click quick presets to help the AI engine understand cell highlights, table structures, and KPIs before confirming ingestion.
              </p>
            </div>

            <div style={{ borderRadius: '8px', overflow: 'hidden', border: '1px solid var(--color-border-tertiary, #e4e4e7)', background: '#ffffff', boxShadow: '0 1px 3px rgba(0,0,0,0.02)' }}>
              <Image src={ingestImage} alt="Staged spreadsheet file with optional AI notes and preset buttons" sizes="(max-width: 800px) calc(100vw - 80px), 720px" style={{ width: '100%', height: 'auto', display: 'block' }} />
            </div>
          </div>

          {/* Step Divider */}
          <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', color: 'var(--color-text-secondary)', opacity: 0.4, height: '8px' }}>
            <div style={{ height: '16px', width: '2px', background: 'var(--color-border-tertiary, #e4e4e7)' }}></div>
          </div>

          {/* Step 4 */}
          <div className="card" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '16px', border: '1px solid var(--color-border-tertiary, #e4e4e7)', position: 'relative' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '8px', borderBottom: '1px solid var(--color-border-tertiary, #e4e4e7)', paddingBottom: '12px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <span style={{ fontSize: '12px', fontWeight: 700, color: '#ffffff', background: 'var(--color-text-primary, #18181b)', width: '24px', height: '24px', borderRadius: '6px', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                  04
                </span>
                <span style={{ fontSize: '11px', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--color-text-secondary, #71717a)' }}>
                  Query & Verification
                </span>
              </div>
              <div style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', fontSize: '11px', fontWeight: 500, color: 'var(--color-text-secondary)', background: 'var(--color-background-secondary)', padding: '3px 8px', borderRadius: '6px' }}>
                <MessageSquareCode size={12} /> Natural Language RAG
              </div>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <h3 style={{ fontSize: '16px', fontWeight: 600, color: 'var(--color-text-primary, #18181b)', margin: 0 }}>
                Ask Questions & Verify Answer Sources
              </h3>
              <p style={{ fontSize: '13px', color: 'var(--color-text-secondary, #71717a)', margin: 0, lineHeight: '1.4' }}>
                Type any question in plain language and review generated answers backed by exact source chunks and correlation percentages.
              </p>
            </div>

            <div style={{ borderRadius: '8px', overflow: 'hidden', border: '1px solid var(--color-border-tertiary, #e4e4e7)', background: '#ffffff', boxShadow: '0 1px 3px rgba(0,0,0,0.02)' }}>
              <Image src={answerImage} alt="Search query results showing generated answer points with source chunks and correlation metrics" sizes="(max-width: 800px) calc(100vw - 80px), 720px" style={{ width: '100%', height: 'auto', display: 'block' }} />
            </div>
          </div>

        </div>

        {/* Call to Action Box */}
        <div className="card" style={{ padding: '24px', textAlign: 'center', background: 'var(--color-background-secondary, #f4f4f5)', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '12px' }}>
          <h3 style={{ fontSize: '18px', fontWeight: 600, color: 'var(--color-text-primary, #18181b)', margin: 0 }}>
            Ready to test it with your own files?
          </h3>
          <p style={{ fontSize: '13px', color: 'var(--color-text-secondary, #71717a)', maxWidth: '440px', margin: 0 }}>
            Create your account and upload your first spreadsheet or document in seconds.
          </p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', alignItems: 'center', marginTop: '4px' }}>
            <Link href="/auth?mode=signup" className="btn btn-primary" style={{ fontSize: '13px', textDecoration: 'none', padding: '8px 18px', display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
              Get Started Free <ArrowRight size={14} />
            </Link>
            <span style={{ fontSize: '11px', color: 'var(--color-text-secondary, #71717a)' }}>No credit card required.</span>
          </div>
        </div>

      </main>

      <MarketingFooter activePage="demo" />
    </div>
  );
}