import Link from 'next/link';
import { X } from 'lucide-react';
import { BrandIcon } from '@/components/BrandIcon';

export default function UpgradeGate() {
  return (
    <div className="screen">
      <div className="nav">
        <div className="nav-logo"><BrandIcon /> HQLookup</div>
        <div className="nav-right"><div className="avatar">JD</div></div>
      </div>
      <div className="modal-overlay">
        <div className="modal">
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
            <div style={{ fontSize: '16px', fontWeight: 500 }}>Upgrade to add more businesses</div>
            <Link href="/dashboard" className="btn" style={{ padding: '4px 8px', border: 'none' }}><X size={16} /></Link>
          </div>
          <div style={{ fontSize: '13px', color: 'var(--color-text-secondary)', marginBottom: '20px', lineHeight: 1.6 }}>
            You&apos;re on the <strong>Starter</strong> plan which includes 1 business. Upgrade to manage multiple locations.
          </div>
          <div style={{ display: 'flex', gap: '8px' }}>
            <Link href="/dashboard" className="btn" style={{ flex: 1, justifyContent: 'center' }}>Maybe later</Link>
            <button className="btn btn-primary" style={{ flex: 1, justifyContent: 'center' }}>Upgrade to Pro</button>
          </div>
        </div>
      </div>
    </div>
  );
}
