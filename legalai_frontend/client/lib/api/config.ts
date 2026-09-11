/** Where the backend lives. Never hardcode a host at a call site. */
export const API_BASE: string =
  (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(
    /\/$/,
    "",
  ) ?? "http://localhost:8000";
