/**
 * The auth endpoints. Storage and refresh live in ./tokens, which this builds
 * on rather than the other way round -- that ordering is what keeps the module
 * graph acyclic.
 */

import { api } from "./client";
import { storeTokens } from "./tokens";
import type { TokenResponse, UserResponse } from "./types";

export async function register(
  email: string,
  password: string,
): Promise<TokenResponse> {
  const tokens = await api.post<TokenResponse>("/v1/auth/register", {
    email,
    password,
  });
  storeTokens(tokens);
  return tokens;
}

export async function login(
  email: string,
  password: string,
): Promise<TokenResponse> {
  const tokens = await api.post<TokenResponse>("/v1/auth/login", {
    email,
    password,
  });
  storeTokens(tokens);
  return tokens;
}

export const me = () => api.get<UserResponse>("/v1/auth/me", { auth: true });

export {
  getRateLimit,
  isSignedIn,
  signOut,
  subscribe,
  subscribeRateLimit,
} from "./tokens";
