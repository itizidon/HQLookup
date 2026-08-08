import Link from 'next/link';
import { FileText } from 'lucide-react';

export default function Navbar({ avatarInitials = 'JD' }) {
  return (
    <div className="nav">
      <Link href="/dashboard" className="nav-logo" style={{ textDecoration: 'none' }}>
        <FileText size={18} style={{ color: 'var(--color-text-info)' }} /> HQLookup
      </Link>
      <div className="nav-right">
        <Link href="/billing" className="nav-link">Billing</Link>
        <div className="avatar" style={{ cursor: 'pointer' }}>{avatarInitials}</div>
      </div>
    </div>
  );
}