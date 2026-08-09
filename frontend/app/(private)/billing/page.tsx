'use client';

import { useState, useEffect } from 'react';
import Navbar from '@/components/Navbar';
import MetricCard from '@/components/MetricCard';
import { Loader2, CreditCard } from 'lucide-react';

interface BillingStatusData {
  plan: string;
  monthly_searches: number;
  max_businesses: number;
  max_organizations: number;
  stripe_status: string | null;
  cancels_at: string | null;
  has_billing_account: boolean;
}

// Helper function to extract initials from a full name (e.g., "Don Ng" -> "DN")
const getInitials = (name: string) => {
  if (!name) return 'DN';
  const parts = name.trim().split(/\s+/);
  
  if (parts.length >= 2) {
    return `${parts[0][0]}${parts[parts.length - 1][0]}`.toUpperCase();
  }
  
  return parts[0][0].toUpperCase();
};

export default function BillingPlan() {
  const [billingInfo, setBillingInfo] = useState<BillingStatusData | null>(null);
  const [userName, setUserName] = useState<string>('');
  const [isLoading, setIsLoading] = useState(true);
  const [isActionLoading, setIsActionLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Fetch live server constraints, plan definitions, and user profile concurrently
  useEffect(() => {
    async function fetchData() {
      try {
        const [billingRes, userRes] = await Promise.all([
          fetch('http://localhost:8000/billing/status', { credentials: 'include' }),
          fetch('http://localhost:8000/auth/me', { credentials: 'include' })
        ]);

        if (!billingRes.ok) throw new Error('Could not retrieve operational billing logs.');
        
        const billingData = await billingRes.json();
        setBillingInfo(billingData);

        if (userRes.ok) {
          const userData = await userRes.json();
          setUserName(userData.name || '');
        }
      } catch (err: any) {
        setError(err.message || 'An error occurred fetching account context.');
      } finally {
        setIsLoading(false);
      }
    }
    fetchData();
  }, []);

  // Routes the user out to Stripe Checkout or Billing Portal automatically
  const handleManageSubscription = async () => {
    if (!billingInfo) return;
    setIsActionLoading(true);
    setError(null);

    try {
      if (billingInfo.plan === 'free' || !billingInfo.has_billing_account) {
        const res = await fetch('http://localhost:8000/billing/checkout', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ plan: 'starter' }),
          credentials: 'include',
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Failed to instantiate checkout process.');
        if (data.checkout_url) window.location.href = data.checkout_url;
      } else {
        const res = await fetch('http://localhost:8000/billing/portal', {
          method: 'POST',
          credentials: 'include',
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Failed to initialize portal pipeline.');
        if (data.portal_url) window.location.href = data.portal_url;
      }
    } catch (err: any) {
      setError(err.message || 'An unexpected action failure occurred.');
      setIsActionLoading(false);
    }
  };

  const userInitials = getInitials(userName);

  if (isLoading) {
    return (
      <div className="screen" style={{ display: 'flex', flexDirection: 'column', height: '100vh' }}>
        <Navbar avatarInitials={userInitials} />
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <Loader2 className="animate-spin" style={{ color: 'var(--color-text-secondary)' }} />
        </div>
      </div>
    );
  }

  const activePlan = billingInfo?.plan || 'free';
  const displayPlanName = activePlan.charAt(0).toUpperCase() + activePlan.slice(1);

  return (
    <div className="screen">
      <Navbar avatarInitials={userInitials} />
      <div style={{ padding: '24px', maxWidth: '800px', margin: '0 auto' }}>
        <div style={{ fontSize: '18px', fontWeight: 500, marginBottom: '4px' }}>Billing</div>
        <div style={{ fontSize: '13px', color: 'var(--color-text-secondary)', marginBottom: '20px' }}>
          Current plan and usage footprint context
        </div>

        {error && (
          <div style={{ padding: '12px', background: 'rgba(239, 68, 68, 0.1)', border: '1px solid rgb(239, 68, 68)', color: 'rgb(239, 68, 68)', borderRadius: 'var(--border-radius-md)', marginBottom: '16px', fontSize: '13px' }}>
            {error}
          </div>
        )}

        <div style={{ display: 'flex', alignItems: 'center', padding: '16px', background: 'var(--color-background-secondary)', borderRadius: 'var(--border-radius-lg)', marginBottom: '20px', justifyContent: 'space-between' }}>
          <div>
            <div style={{ fontSize: '13px', color: 'var(--color-text-secondary)' }}>Current active account tier</div>
            <div style={{ fontSize: '16px', fontWeight: 500, marginTop: '2px' }}>
              {displayPlanName} {activePlan !== 'free' ? '· Subscribed' : ''}
            </div>
            {billingInfo?.cancels_at && (
              <div style={{ fontSize: '12px', color: 'rgb(239, 68, 68)', marginTop: '4px' }}>
                Access expires: {new Date(billingInfo.cancels_at).toLocaleDateString()}
              </div>
            )}
          </div>

          <button 
            onClick={handleManageSubscription} 
            disabled={isActionLoading}
            className="btn btn-primary"
            style={{ display: 'flex', alignItems: 'center', gap: '8px' }}
          >
            {isActionLoading && <Loader2 className="animate-spin" size={14} />}
            <CreditCard size={14} />
            {activePlan === 'free' ? 'Upgrade Plan' : 'Manage Subscription'}
          </button>
        </div>
        
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '12px', marginBottom: '20px' }}>
          <MetricCard 
            label="Searches Allowed" 
            value={billingInfo?.monthly_searches.toString() || '50'} 
            subtext={`Cap limit pool per billing window`} 
            progressPercentage={100} 
          />
          <MetricCard 
            label="Max Businesses" 
            value={billingInfo?.max_businesses.toString() || '1'} 
            subtext={`Active allowance threshold`} 
            progressPercentage={100} 
          />
          <MetricCard 
            label="Allowed Teams" 
            value={billingInfo?.max_organizations.toString() || '1'} 
            subtext={`Workspace organizations`} 
            progressPercentage={100} 
          />
        </div>
      </div>
    </div>
  );
}