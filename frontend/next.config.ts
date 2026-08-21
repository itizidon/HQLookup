import type { NextConfig } from "next";

const isDevelopment = process.env.NODE_ENV === "development";

function resolveBackendUrl(): string {
  const configuredUrl = process.env.BACKEND_URL;

  if (!configuredUrl && !isDevelopment) {
    throw new Error(
      "BACKEND_URL is required outside development (for example, http://backend:8000).",
    );
  }

  const candidate = configuredUrl ?? "http://127.0.0.1:8000";
  let parsed: URL;

  try {
    parsed = new URL(candidate);
  } catch {
    throw new Error("BACKEND_URL must be a valid absolute HTTP(S) URL.");
  }

  if (!["http:", "https:"].includes(parsed.protocol)) {
    throw new Error("BACKEND_URL must use the http: or https: protocol.");
  }

  if (parsed.username || parsed.password || parsed.search || parsed.hash) {
    throw new Error("BACKEND_URL must not contain credentials, a query, or a fragment.");
  }

  const isLoopback = ["localhost", "127.0.0.1", "::1"].includes(parsed.hostname);
  if (!isDevelopment && isLoopback) {
    throw new Error("BACKEND_URL must not point to localhost in production.");
  }

  return parsed.toString().replace(/\/$/, "");
}

const backendUrl = resolveBackendUrl();

const securityHeaders = [
  { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
  { key: "Cross-Origin-Resource-Policy", value: "same-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=(), usb=()" },
  { key: "Referrer-Policy", value: "no-referrer" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-DNS-Prefetch-Control", value: "off" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-Permitted-Cross-Domain-Policies", value: "none" },
  ...(isDevelopment
    ? []
    : [
        {
          key: "Strict-Transport-Security",
          value: "max-age=31536000",
        },
      ]),
];

const nextConfig: NextConfig = {
  poweredByHeader: false,
  async headers() {
    return [
      {
        source: "/:path*",
        headers: securityHeaders,
      },
      {
        source: "/backend/:path*",
        headers: [{ key: "Cache-Control", value: "no-store" }],
      },
    ];
  },
  async rewrites() {
    return [
      {
        source: "/backend/:path*",
        destination: `${backendUrl}/:path*`,
      },
    ];
  },
};

export default nextConfig;
