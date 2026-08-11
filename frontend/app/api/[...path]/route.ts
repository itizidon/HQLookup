import type { NextRequest } from "next/server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const SESSION_AUTH_ENDPOINTS = new Set(["login", "signup", "logout"]);
const REQUEST_HOP_BY_HOP_HEADERS = [
  "connection",
  "content-length",
  "host",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
];
const RESPONSE_HOP_BY_HOP_HEADERS = [
  ...REQUEST_HOP_BY_HOP_HEADERS,
  "content-encoding",
];

type GatewayContext = {
  params: Promise<{ path: string[] }>;
};

type StreamingRequestInit = RequestInit & {
  duplex?: "half";
};

function getApiOrigin(): URL {
  const configured = process.env.API_ORIGIN?.trim();
  if (!configured) {
    throw new Error("API_ORIGIN is not configured");
  }

  const origin = new URL(configured);
  if (!(["http:", "https:"] as string[]).includes(origin.protocol)) {
    throw new Error("API_ORIGIN must use HTTP or HTTPS");
  }
  if (
    origin.username ||
    origin.password ||
    origin.search ||
    origin.hash ||
    !["", "/"].includes(origin.pathname)
  ) {
    throw new Error("API_ORIGIN must be an origin without credentials or a path");
  }

  return origin;
}

function getTimeoutMs(): number {
  const configured = Number(process.env.API_PROXY_TIMEOUT_MS ?? "300000");
  if (!Number.isFinite(configured)) return 300_000;
  return Math.min(Math.max(Math.round(configured), 1_000), 1_800_000);
}

function getBackendPath(path: string[]): string {
  const encodedPath = path.map((segment) => encodeURIComponent(segment));
  const isSessionAuthRoute =
    encodedPath[0] === "auth" &&
    encodedPath.length === 2 &&
    SESSION_AUTH_ENDPOINTS.has(encodedPath[1]);

  return `${isSessionAuthRoute ? "/api" : ""}/${encodedPath.join("/")}`;
}

function isSameOriginMutation(request: NextRequest): boolean {
  if (["GET", "HEAD", "OPTIONS"].includes(request.method)) return true;

  const requestOrigin = request.headers.get("origin");
  if (!requestOrigin) return true;

  try {
    return new URL(requestOrigin).origin === request.nextUrl.origin;
  } catch {
    return false;
  }
}

function createUpstreamHeaders(request: NextRequest): Headers {
  const headers = new Headers(request.headers);
  REQUEST_HOP_BY_HOP_HEADERS.forEach((header) => headers.delete(header));
  headers.delete("accept-encoding");
  headers.set("x-forwarded-host", request.headers.get("host") ?? "");
  headers.set("x-forwarded-proto", request.nextUrl.protocol.replace(":", ""));
  return headers;
}

function copyResponseHeaders(upstreamHeaders: Headers): Headers {
  const responseHeaders = new Headers(upstreamHeaders);
  RESPONSE_HOP_BY_HOP_HEADERS.forEach((header) => responseHeaders.delete(header));
  responseHeaders.delete("set-cookie");
  responseHeaders.set("Cache-Control", "no-store");

  const headersWithCookies = upstreamHeaders as Headers & {
    getSetCookie?: () => string[];
  };
  const cookies = headersWithCookies.getSetCookie?.() ?? [];
  for (const cookie of cookies) {
    // Cookies returned through this same-origin gateway should be scoped to the
    // frontend host, regardless of the internal API hostname.
    responseHeaders.append(
      "Set-Cookie",
      cookie.replace(/;\s*Domain=[^;]*/i, ""),
    );
  }

  return responseHeaders;
}

async function proxyRequest(
  request: NextRequest,
  context: GatewayContext,
): Promise<Response> {
  if (!isSameOriginMutation(request)) {
    return Response.json(
      { detail: "Cross-origin state-changing requests are not allowed." },
      { status: 403 },
    );
  }

  let apiOrigin: URL;
  try {
    apiOrigin = getApiOrigin();
  } catch {
    return Response.json(
      { detail: "The API gateway is not configured." },
      { status: 503 },
    );
  }

  const { path } = await context.params;
  const upstreamUrl = new URL(getBackendPath(path), apiOrigin);
  upstreamUrl.search = request.nextUrl.search;

  const hasBody = !["GET", "HEAD"].includes(request.method);
  const requestInit: StreamingRequestInit = {
    method: request.method,
    headers: createUpstreamHeaders(request),
    body: hasBody ? request.body : undefined,
    cache: "no-store",
    redirect: "manual",
    signal: AbortSignal.any([
      request.signal,
      AbortSignal.timeout(getTimeoutMs()),
    ]),
  };
  if (hasBody) requestInit.duplex = "half";

  try {
    const upstreamResponse = await fetch(upstreamUrl, requestInit);
    return new Response(request.method === "HEAD" ? null : upstreamResponse.body, {
      status: upstreamResponse.status,
      statusText: upstreamResponse.statusText,
      headers: copyResponseHeaders(upstreamResponse.headers),
    });
  } catch (error) {
    const isTimeout =
      error instanceof DOMException && error.name === "TimeoutError";
    return Response.json(
      {
        detail: isTimeout
          ? "The API request timed out."
          : "The API service is unavailable.",
      },
      { status: isTimeout ? 504 : 502 },
    );
  }
}

export const GET = proxyRequest;
export const HEAD = proxyRequest;
export const POST = proxyRequest;
export const PUT = proxyRequest;
export const PATCH = proxyRequest;
export const DELETE = proxyRequest;
export const OPTIONS = proxyRequest;
