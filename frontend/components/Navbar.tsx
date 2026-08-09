'use client';

import { useState, useRef, useEffect } from 'react';
import Link from 'next/link';
import { FileText, LogOut, CreditCard } from 'lucide-react';
import { useRouter } from 'next/navigation';

export default function Navbar({ avatarInitials = 'D' }) {
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const router = useRouter();

  // Close dropdown when clicking outside
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const handleSignOut = async () => {
    try {
      await fetch('http://localhost:8000/api/auth/logout', {
        method: 'POST',
        credentials: 'include',
      });
      router.push('/');
    } catch (err) {
      console.error('Sign out failed:', err);
    }
  };

  return (
    <div className="nav" style={{ position: 'relative' }}>
      <Link href="/dashboard" className="nav-logo" style={{ textDecoration: 'none' }}>
        <FileText size={18} style={{ color: 'var(--color-text-info)' }} /> HQLookup
      </Link>
      
      <div className="nav-right" style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
        <Link href="/billing" className="nav-link">Billing</Link>
        
        {/* Avatar with Dropdown Container */}
        <div style={{ position: 'relative' }} ref={dropdownRef}>
          <div 
            className="avatar" 
            style={{ cursor: 'pointer', userSelect: 'none' }}
            onClick={() => setIsOpen(!isOpen)}
          >
            {avatarInitials}
          </div>

          {isOpen && (
            <div style={{
              position: 'absolute',
              top: 'calc(100% + 8px)',
              right: 0,
              width: '160px',
              background: 'var(--color-background-primary, #ffffff)',
              border: '1px solid var(--color-border-tertiary, #e4e4e7)',
              borderRadius: 'var(--border-radius-md, 8px)',
              boxShadow: '0 4px 12px rgba(0,0,0,0.08)',
              zIndex: 1000,
              padding: '4px',
              display: 'flex',
              flexDirection: 'column',
              gap: '2px'
            }}>
              <button
                type="button"
                onClick={handleSignOut}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px',
                  width: '100%',
                  textAlign: 'left',
                  padding: '8px 10px',
                  fontSize: '13px',
                  color: '#ef4444',
                  background: 'transparent',
                  border: 'none',
                  borderRadius: '4px',
                  cursor: 'pointer'
                }}
              >
                <LogOut size={14} style={{ color: '#ef4444' }} /> Sign out
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}