const API_BASE_PATH = "/backend";

/**
 * Send browser requests through Next.js so authentication cookies always stay
 * on the application's origin. BACKEND_URL is intentionally only read by
 * next.config.ts and is never bundled into client JavaScript.
 */
export function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  if (!path.startsWith("/") || path.startsWith("//")) {
    throw new Error("API paths must be same-origin absolute paths.");
  }

  return fetch(`${API_BASE_PATH}${path}`, {
    credentials: "include",
    ...init,
  });
}

export function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

export async function responseErrorMessage(
  response: Response,
  fallback: string,
): Promise<string> {
  const payload: unknown = await response.json().catch(() => null);

  if (payload && typeof payload === "object" && "detail" in payload) {
    const detail = (payload as { detail?: unknown }).detail;
    if (typeof detail === "string" && detail.trim()) {
      return detail;
    }

    if (Array.isArray(detail)) {
      const messages = detail.flatMap((item) => {
        if (item && typeof item === "object" && "msg" in item) {
          const message = (item as { msg?: unknown }).msg;
          return typeof message === "string" ? [message] : [];
        }
        return [];
      });

      if (messages.length > 0) {
        return messages.join(", ");
      }
    }
  }

  return fallback;
}
