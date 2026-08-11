const DEFAULT_API_BASE = "/api";
const SESSION_AUTH_ENDPOINTS = new Set([
  "/auth/login",
  "/auth/signup",
  "/auth/logout",
]);

type ErrorPayload = {
  detail?: unknown;
  message?: unknown;
};

export type ApiRequestOptions = RequestInit & {
  redirectOnUnauthorized?: boolean;
};

export class ApiError extends Error {
  readonly status: number;
  readonly payload: unknown;

  constructor(message: string, status: number, payload: unknown = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.payload = payload;
  }
}

function trimTrailingSlashes(value: string): string {
  return value.replace(/\/+$/, "");
}

export function getApiBaseUrl(): string {
  const configured = process.env.NEXT_PUBLIC_API_URL?.trim();
  return trimTrailingSlashes(configured || DEFAULT_API_BASE);
}

function normalizeEndpoint(endpoint: string): string {
  if (!endpoint.startsWith("/")) {
    throw new Error(`API endpoints must start with "/": ${endpoint}`);
  }

  return endpoint;
}

export function getApiUrl(endpoint: string): string {
  const base = getApiBaseUrl();
  const path = normalizeEndpoint(endpoint);

  // The built-in same-origin gateway exposes auth at /api/auth/* and maps it
  // to FastAPI's /api/auth/*. An explicit absolute override points directly at
  // FastAPI, so it needs that backend prefix added here.
  const directBackendPath =
    /^https?:\/\//i.test(base) && SESSION_AUTH_ENDPOINTS.has(path)
      ? `/api${path}`
      : path;

  return `${base}${directBackendPath}`;
}

function messageFromPayload(payload: unknown, fallback: string): string {
  if (!payload || typeof payload !== "object") return fallback;

  const { detail, message } = payload as ErrorPayload;
  if (typeof detail === "string") return detail;
  if (typeof message === "string") return message;

  if (detail && typeof detail === "object" && !Array.isArray(detail)) {
    const nestedMessage = (detail as { message?: unknown }).message;
    if (typeof nestedMessage === "string") return nestedMessage;
  }

  if (Array.isArray(detail)) {
    const messages = detail
      .map((entry) => {
        if (!entry || typeof entry !== "object") return String(entry);
        const validationMessage = (entry as { msg?: unknown }).msg;
        return typeof validationMessage === "string"
          ? validationMessage
          : null;
      })
      .filter((entry): entry is string => Boolean(entry));

    if (messages.length > 0) return messages.join(", ");
  }

  return fallback;
}

async function readResponsePayload(response: Response): Promise<unknown> {
  if (response.status === 204) return null;

  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    return response.json().catch(() => null);
  }

  const text = await response.text().catch(() => "");
  return text || null;
}

export async function apiRequest<T>(
  endpoint: string,
  options: ApiRequestOptions = {},
): Promise<T> {
  const {
    redirectOnUnauthorized = true,
    headers: providedHeaders,
    ...requestOptions
  } = options;
  const headers = new Headers(providedHeaders);

  if (!headers.has("Accept")) {
    headers.set("Accept", "application/json");
  }

  const response = await fetch(getApiUrl(endpoint), {
    ...requestOptions,
    credentials: requestOptions.credentials ?? "include",
    cache: requestOptions.cache ?? "no-store",
    headers,
  });

  const payload = await readResponsePayload(response);

  if (!response.ok) {
    if (
      response.status === 401 &&
      redirectOnUnauthorized &&
      typeof window !== "undefined" &&
      window.location.pathname !== "/auth"
    ) {
      const returnTo = `${window.location.pathname}${window.location.search}`;
      window.location.assign(`/auth?returnTo=${encodeURIComponent(returnTo)}`);
    }

    throw new ApiError(
      messageFromPayload(payload, `Request failed (${response.status})`),
      response.status,
      payload,
    );
  }

  return payload as T;
}

export function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

export function getErrorMessage(
  error: unknown,
  fallback = "Something went wrong. Please try again.",
): string {
  return error instanceof Error && error.message ? error.message : fallback;
}
