/**
 * Token storage and refresh.
 *
 * Deliberately free of any dependency on the request helper, so the
 * dependency graph runs one way: auth endpoints -> request helper -> this.
 * The refresh call issues its own fetch for that reason; routing it through
 * the helper would create a cycle, and a cycle here is what forces the lazy
 * imports that bundlers then warn about.
 *
 * Access and refresh tokens are kept under separate keys because the backend
 * checks a `typ` claim: a refresh token is rejected as a bearer credential and
 * an access token is rejected at /auth/refresh. Separate keys make swapping
 * them by accident impossible.
 */

import { API_BASE } from "./config";
import type { RateLimit, TokenResponse } from "./types";

const ACCESS_KEY = "legaledge.access_token";
const REFRESH_KEY = "legaledge.refresh_token";
const EXPIRY_KEY = "legaledge.access_expires_at";

type Listener = () => void;
const authListeners = new Set<Listener>();
const rateLimitListeners = new Set<Listener>();
const rateLimits = new Map<string, RateLimit>();

export function subscribe(listener: Listener): () => void {
  authListeners.add(listener);
  return () => authListeners.delete(listener);
}

export function subscribeRateLimit(listener: Listener): () => void {
  rateLimitListeners.add(listener);
  return () => rateLimitListeners.delete(listener);
}

export function onRateLimit(path: string, limit: RateLimit) {
  rateLimits.set(path.split("?")[0], limit);
  rateLimitListeners.forEach((fn) => fn());
}

export const getRateLimit = (path: string): RateLimit | null =>
  rateLimits.get(path) ?? null;

export const getAccessToken = (): string | null =>
  localStorage.getItem(ACCESS_KEY);
export const getRefreshToken = (): string | null =>
  localStorage.getItem(REFRESH_KEY);
export const isSignedIn = (): boolean => getAccessToken() !== null;

export function storeTokens(tokens: TokenResponse) {
  localStorage.setItem(ACCESS_KEY, tokens.access_token);
  localStorage.setItem(REFRESH_KEY, tokens.refresh_token);
  localStorage.setItem(
    EXPIRY_KEY,
    String(Date.now() + tokens.expires_in * 1000),
  );
  authListeners.forEach((fn) => fn());
}

export function clearTokens() {
  [ACCESS_KEY, REFRESH_KEY, EXPIRY_KEY].forEach((key) =>
    localStorage.removeItem(key),
  );
  authListeners.forEach((fn) => fn());
}

/** Client-side discard. The backend has no revocation endpoint. */
export const signOut = clearTokens;

let inFlight: Promise<boolean> | null = null;

/**
 * Exchange the refresh token for a new pair. Concurrent callers share one
 * request: five parallel queries hitting a stale token must not fire five
 * refreshes, which would race and orphan four of them.
 */
export async function refreshTokens(): Promise<boolean> {
  if (inFlight) return inFlight;
  const refresh = getRefreshToken();
  if (!refresh) return false;

  inFlight = (async () => {
    try {
      const response = await fetch(`${API_BASE}/v1/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refresh }),
      });
      if (!response.ok) {
        clearTokens();
        return false;
      }
      storeTokens((await response.json()) as TokenResponse);
      return true;
    } catch {
      return false;
    } finally {
      inFlight = null;
    }
  })();

  return inFlight;
}
