import Link from "next/link";
import { ArrowRight, Building2 } from "lucide-react";

export type MarketingPage = "about" | "contact" | "features" | "pricing" | "roadmap" | "solutions";

type MarketingNavigationProps = {
  activePage?: MarketingPage;
};

type NavigationLink = {
  href: string;
  label: string;
  page?: MarketingPage;
};

const navigationLinks: NavigationLink[] = [
  { href: "/features", label: "Features", page: "features" },
  { href: "/pricing", label: "Pricing", page: "pricing" },
  { href: "/solutions", label: "Solutions", page: "solutions" },
  { href: "/demo", label: "Demo" },
  { href: "/about", label: "About", page: "about" },
  { href: "/contact", label: "Contact", page: "contact" },
];

const footerGroups: { label: string; links: NavigationLink[] }[] = [
  {
    label: "Product",
    links: [
      { href: "/features", label: "Features", page: "features" },
      { href: "/pricing", label: "Pricing", page: "pricing" },
      { href: "/demo", label: "Demo" },
      { href: "/roadmap", label: "Roadmap", page: "roadmap" },
    ],
  },
  {
    label: "Company",
    links: [
      { href: "/about", label: "About", page: "about" },
      { href: "/contact", label: "Contact", page: "contact" },
    ],
  },
];

export function MarketingHeader({ activePage }: MarketingNavigationProps) {
  return (
    <>
      <style>{`
        @media (max-width: 768px) {
          .marketing-nav-links {
            display: none !important;
          }
        }
      `}</style>

      <header style={{ borderBottom: "1px solid var(--color-border-tertiary, #e4e4e7)", background: "var(--color-background-primary, #ffffff)", padding: "16px 24px", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "24px" }}>
          <Link href="/" style={{ display: "flex", alignItems: "center", gap: "8px", textDecoration: "none" }}>
            <div style={{ padding: "6px", borderRadius: "6px", background: "var(--color-background-secondary, #f4f4f5)", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--color-text-primary, #18181b)" }}>
              <Building2 size={18} />
            </div>
            <span style={{ fontSize: "16px", fontWeight: 600, color: "var(--color-text-primary, #18181b)" }}>HQLookup</span>
          </Link>

          <nav aria-label="Primary navigation" className="marketing-nav-links" style={{ display: "flex", alignItems: "center", gap: "20px" }}>
            {navigationLinks.map((link) => {
              const isActive = activePage !== undefined && link.page === activePage;

              return (
                <Link
                  key={link.href}
                  href={link.href}
                  aria-current={isActive ? "page" : undefined}
                  style={{
                    fontSize: "13px",
                    color: isActive
                      ? "var(--color-text-primary, #18181b)"
                      : "var(--color-text-secondary, #71717a)",
                    textDecoration: "none",
                    fontWeight: isActive ? 600 : 500,
                  }}
                >
                  {link.label}
                </Link>
              );
            })}
          </nav>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
          <Link href="/auth" className="btn btn-secondary" style={{ fontSize: "13px", textDecoration: "none" }}>
            Sign in
          </Link>
          <Link href="/demo" className="btn btn-primary" style={{ fontSize: "13px", textDecoration: "none" }}>
            Get a Demo <ArrowRight size={14} style={{ marginLeft: "4px" }} />
          </Link>
        </div>
      </header>
    </>
  );
}

export function MarketingFooter({ activePage }: MarketingNavigationProps) {
  return (
    <footer style={{ borderTop: "1px solid var(--color-border-tertiary, #e4e4e7)", padding: "32px 24px 24px", display: "flex", flexDirection: "column", gap: "32px", alignItems: "center", background: "var(--color-background-primary, #ffffff)" }}>
      <nav aria-label="Footer navigation" style={{ width: "100%", maxWidth: "840px", display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: "32px 64px" }}>
        {footerGroups.map((group) => (
          <div key={group.label}>
            <h2 style={{ fontSize: "13px", fontWeight: 600, color: "var(--color-text-primary, #18181b)", marginBottom: "12px" }}>
              {group.label}
            </h2>
            <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", gap: "8px" }}>
              {group.links.map((link) => {
                const isActive = activePage !== undefined && link.page === activePage;

                return (
                  <Link
                    key={link.href}
                    href={link.href}
                    aria-current={isActive ? "page" : undefined}
                    style={{
                      color: "var(--color-text-secondary, #71717a)",
                      fontSize: "13px",
                      fontWeight: isActive ? 500 : 400,
                      textDecoration: "none",
                    }}
                  >
                    {link.label}
                  </Link>
                );
              })}
            </div>
          </div>
        ))}
      </nav>
      <div style={{ width: "100%", maxWidth: "840px", borderTop: "1px solid var(--color-border-tertiary, #e4e4e7)", paddingTop: "16px", fontSize: "12px", color: "var(--color-text-secondary, #71717a)" }}>
        © 2026 HQLookup
      </div>
    </footer>
  );
}
