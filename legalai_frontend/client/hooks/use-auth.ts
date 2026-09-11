import { useCallback, useEffect, useState } from "react";
import {
  getRateLimit,
  isSignedIn,
  signOut as doSignOut,
  subscribe,
  subscribeRateLimit,
} from "@/lib/api/tokens";
import type { RateLimit } from "@/lib/api/types";

/** Reactive sign-in state, driven by the token store rather than by React. */
export function useAuth() {
  const [signedIn, setSignedIn] = useState(isSignedIn);
  useEffect(() => subscribe(() => setSignedIn(isSignedIn())), []);
  const signOut = useCallback(() => doSignOut(), []);
  return { signedIn, signOut };
}

/**
 * The server's rate-limit headers for a path.
 *
 * /v1/ask allows 20 questions an hour, which a real user will hit. Showing
 * what remains is kinder than surfacing a 429 mid-thought.
 */
export function useRateLimit(path: string): RateLimit | null {
  const [limit, setLimit] = useState<RateLimit | null>(() =>
    getRateLimit(path),
  );
  useEffect(
    () => subscribeRateLimit(() => setLimit(getRateLimit(path))),
    [path],
  );
  return limit;
}
