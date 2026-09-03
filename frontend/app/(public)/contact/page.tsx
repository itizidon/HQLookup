"use client";

import { ArrowRight, Mail, MessageSquare, Send } from "lucide-react";
import { MarketingFooter, MarketingHeader } from "@/components/MarketingNavigation";

export default function ContactPage() {
  return (
    <div className="screen" style={{ position: 'relative', overflowX: 'hidden', minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      <style>{`
        @media (max-width: 768px) {
          .contact-grid {
            grid-template-columns: 1fr !important;
          }
        }
      `}</style>

      <MarketingHeader activePage="contact" />

      {/* Main Content Area */}
      <main style={{ padding: '48px 24px', maxWidth: '840px', margin: '0 auto', width: '100%', flex: 1, display: 'flex', flexDirection: 'column', gap: '48px' }}>
        
        {/* Hero Section */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <div style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', padding: '4px 10px', borderRadius: '20px', background: 'var(--color-background-secondary, #f4f4f5)', fontSize: '11px', fontWeight: 500, color: 'var(--color-text-secondary, #71717a)', width: 'fit-content' }}>
            Get in Touch
          </div>
          <h1 style={{ fontSize: '32px', fontWeight: 600, color: 'var(--color-text-primary, #18181b)', letterSpacing: '-0.02em', lineHeight: '1.2' }}>
            We&apos;d love to hear from you
          </h1>
          <p style={{ fontSize: '15px', color: 'var(--color-text-secondary, #71717a)', lineHeight: '1.6' }}>
            Have questions about HQLookup, need help setting up your workspace, or want to discuss custom requirements? Reach out directly and our team will get back to you promptly.
          </p>
        </div>

        {/* Contact Info Grid */}
        <div className="contact-grid" style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '20px', alignItems: 'stretch' }}>
          
          {/* Direct Email Card */}
          <div className="card" style={{ padding: '32px', display: 'flex', flexDirection: 'column', justifyContent: 'space-between', gap: '24px' }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <div style={{ padding: '10px', borderRadius: '8px', background: 'var(--color-background-secondary, #f4f4f5)', width: 'fit-content', color: 'var(--color-text-primary)' }}>
                <Mail size={20} />
              </div>
              <div>
                <h3 style={{ fontSize: '18px', fontWeight: 600, color: 'var(--color-text-primary, #18181b)', marginBottom: '4px' }}>
                  Email Us Directly
                </h3>
                <p style={{ fontSize: '13px', color: 'var(--color-text-secondary, #71717a)', lineHeight: '1.5', margin: 0 }}>
                  For general inquiries, support, or feedback, drop us an email anytime.
                </p>
              </div>
            </div>

            <div>
              <a href="mailto:contact@hqlookup.com" style={{ fontSize: '14px', fontWeight: 600, color: 'var(--color-text-primary, #18181b)', textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
                contact@hqlookup.com <ArrowRight size={14} />
              </a>
            </div>
          </div>

          {/* Quick Support Card */}
          <div className="card" style={{ padding: '32px', display: 'flex', flexDirection: 'column', justifyContent: 'space-between', gap: '24px' }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <div style={{ padding: '10px', borderRadius: '8px', background: 'var(--color-background-secondary, #f4f4f5)', width: 'fit-content', color: 'var(--color-text-primary)' }}>
                <MessageSquare size={20} />
              </div>
              <div>
                <h3 style={{ fontSize: '18px', fontWeight: 600, color: 'var(--color-text-primary, #18181b)', marginBottom: '4px' }}>
                  Product Support
                </h3>
                <p style={{ fontSize: '13px', color: 'var(--color-text-secondary, #71717a)', lineHeight: '1.5', margin: 0 }}>
                  Already using HQLookup? Reach out with your account email for priority assistance.
                </p>
              </div>
            </div>

            <div>
              <span style={{ fontSize: '13px', color: 'var(--color-text-secondary, #71717a)' }}>
                Average response time: &lt; 72 hours
              </span>
            </div>
          </div>

        </div>

        {/* Contact Form Section */}
        <div className="card" style={{ padding: '32px', display: 'flex', flexDirection: 'column', gap: '24px' }}>
          <div>
            <h3 style={{ fontSize: '18px', fontWeight: 600, color: 'var(--color-text-primary, #18181b)', marginBottom: '4px' }}>
              Send us a message
            </h3>
            <p style={{ fontSize: '13px', color: 'var(--color-text-secondary, #71717a)' }}>
              Fill out the form below and we’ll route your message straight to our team.
            </p>
          </div>

          <form onSubmit={(e) => e.preventDefault()} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '16px' }}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                <label style={{ fontSize: '12px', fontWeight: 500, color: 'var(--color-text-primary)' }}>Your Name</label>
                <input 
                  type="text" 
                  placeholder="Jane Doe" 
                  style={{ padding: '10px 12px', borderRadius: '6px', border: '1px solid var(--color-border-tertiary, #e4e4e7)', background: 'var(--color-background-primary)', color: 'var(--color-text-primary)', fontSize: '13px', outline: 'none' }}
                />
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                <label style={{ fontSize: '12px', fontWeight: 500, color: 'var(--color-text-primary)' }}>Email Address</label>
                <input 
                  type="email" 
                  placeholder="jane@company.com" 
                  style={{ padding: '10px 12px', borderRadius: '6px', border: '1px solid var(--color-border-tertiary, #e4e4e7)', background: 'var(--color-background-primary)', color: 'var(--color-text-primary)', fontSize: '13px', outline: 'none' }}
                />
              </div>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <label style={{ fontSize: '12px', fontWeight: 500, color: 'var(--color-text-primary)' }}>Message</label>
              <textarea 
                rows={4}
                placeholder="How can we help you?" 
                style={{ padding: '10px 12px', borderRadius: '6px', border: '1px solid var(--color-border-tertiary, #e4e4e7)', background: 'var(--color-background-primary)', color: 'var(--color-text-primary)', fontSize: '13px', outline: 'none', resize: 'vertical' }}
              />
            </div>

            <button type="submit" className="btn btn-primary" style={{ fontSize: '13px', padding: '10px 20px', width: 'fit-content', display: 'inline-flex', alignItems: 'center', gap: '6px', cursor: 'pointer', border: 'none' }}>
              Send Message <Send size={14} />
            </button>
          </form>
        </div>

      </main>

      <MarketingFooter activePage="contact" />
    </div>
  );
}
