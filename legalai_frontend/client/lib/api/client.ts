/**
 * The one place that talks to the backend.
 *
 * Three behaviours here are not incidental:
 *
 *  - Every failure arrives as a typed `ApiError` carrying the server's `code`.
 *    Callers branch on the code, never on the message. A 402
 *    `missing_provider_key` is the whole reason the backend uses that status,
 *    and it must reach the UI intact so Settings can be offered.
 *  - A 401 triggers exactly one refresh and one retry. Never a loop: a refresh
 *    token that is itself expired would otherwise spin forever.
 *  - Rate-limit headers are captured on every response, so the UI can warn
 *    before the limit bites rather than surfacing a 429 mid-thought.
 */

import type { ApiErrorBody, ApiErrorCode, RateLimit } from "./types";
import { API_BASE } from "./config";
import { getAccessToken, onRateLimit, refreshTokens } from "./tokens";

export { API_BASE };

export class ApiError extends Error {
  readonly code: ApiErrorCode;
  readonly status: number;
  readonly details: Record<string, unknown>;
  readonly requestId: string | null;

  constructor(
    status: number,
    code: ApiErrorCode,
    message: string,
    details: Record<string, unknown> = {},
    requestId: string | null = null,
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
    this.requestId = requestId;
  }

  /** Seconds to wait, when the server said so. */
  get retryAfterSeconds(): number | null {
    const value = this.details.retry_after_seconds;
    return typeof value === "number" ? value : null;
  }

  /** The provider a missing/invalid key belongs to, when the server named it. */
  get provider(): string | null {
    const value = this.details.provider;
    return typeof value === "string" ? value : null;
  }
}

/** A network failure is not an API error; it still needs a typed shape. */
export function isOffline(error: unknown): boolean {
  return error instanceof TypeError;
}

function readRateLimit(response: Response): RateLimit | null {
  const limit = response.headers.get("X-RateLimit-Limit");
  if (!limit) return null;
  return {
    limit: Number(limit),
    remaining: Number(response.headers.get("X-RateLimit-Remaining") ?? 0),
    resetAfter: Number(response.headers.get("X-RateLimit-Reset") ?? 0),
  };
}

async function toApiError(response: Response): Promise<ApiError> {
  let body: ApiErrorBody | null = null;
  try {
    body = (await response.json()) as ApiErrorBody;
  } catch {
    // A non-JSON body (a proxy error page, say) still has to become typed.
  }
  const error = body?.error;
  return new ApiError(
    response.status,
    error?.code ?? "internal_error",
    error?.message ?? `Request failed with status ${response.status}.`,
    error?.details ?? {},
    error?.request_id ?? null,
  );
}

export interface RequestOptions extends Omit<RequestInit, "body"> {
  body?: unknown;
  /** Send the bearer token. Corpus reads do not need one. */
  auth?: boolean;
  /** Internal: prevents a refresh loop. */
  _retried?: boolean;
}

export async function request<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const { body, auth = false, headers, _retried = false, ...rest } = options;

  const finalHeaders = new Headers(headers);
  if (body !== undefined) finalHeaders.set("Content-Type", "application/json");
  if (auth) {
    const token = getAccessToken();
    if (token) finalHeaders.set("Authorization", `Bearer ${token}`);
  }

  const response = await fetch(`${API_BASE}${path}`, {
    ...rest,
    headers: finalHeaders,
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  const rateLimit = readRateLimit(response);
  if (rateLimit) onRateLimit(path, rateLimit);

  if (response.status === 401 && auth && !_retried) {
    // One refresh, one retry. If the refresh fails it throws and we stop.
    const refreshed = await refreshTokens();
    if (refreshed) {
      return request<T>(path, { ...options, _retried: true });
    }
  }

  if (!response.ok) throw await toApiError(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  get: <T>(path: string, options: RequestOptions = {}) =>
    request<T>(path, { ...options, method: "GET" }),
  post: <T>(path: string, body?: unknown, options: RequestOptions = {}) =>
    request<T>(path, { ...options, method: "POST", body }),
  put: <T>(path: string, body?: unknown, options: RequestOptions = {}) =>
    request<T>(path, { ...options, method: "PUT", body }),
  delete: <T>(path: string, options: RequestOptions = {}) =>
    request<T>(path, { ...options, method: "DELETE" }),
};
