/**
 * POST /v1/ask, streaming and buffered.
 *
 * `EventSource` is not usable here and that is not a style preference: it can
 * only issue a GET and cannot set an Authorization header. So the stream is
 * read off `fetch` with a `ReadableStream` and the SSE framing is parsed by
 * hand — events are separated by a blank line, fields by "event:" and "data:".
 *
 * The event contract is the backend's, and two of the seven exist for reasons
 * worth restating at the call site:
 *
 *   `invalidated` — the server validates citations *mid-stream* and abandons
 *   the response the moment the model cites a section it was not given. Every
 *   character rendered so far must be thrown away. A client that ignores this
 *   leaves a retracted answer on a lawyer's screen, which defeats the entire
 *   product.
 *
 *   `abstain` — a refusal. It arrives at HTTP 200 because it is a correct
 *   outcome, not a failure.
 */

import { ApiError, api } from "./client";
import { API_BASE } from "./config";
import { getAccessToken, onRateLimit, refreshTokens } from "./tokens";
import type {
  ApiErrorBody,
  AskDonePayload,
  AskRequest,
  AskResponse,
  SourceBlock,
} from "./types";

export interface AskHandlers {
  /** Arrives first, before any text. Render the chips immediately. */
  onSources?: (sources: SourceBlock[]) => void;
  /** Append, unless `replacesAll` — then discard everything and use this. */
  onToken?: (text: string, replacesAll: boolean) => void;
  onCitation?: (citationId: string, sectionId: number) => void;
  /** Discard all rendered text. A correction is coming. */
  onInvalidated?: (reason: string, message: string) => void;
  onAbstain?: (payload: {
    reason: string | null;
    message: string;
    top_score: number | null;
    score_floor: number;
  }) => void;
  onDone?: (payload: AskDonePayload) => void;
  onError?: (error: ApiError) => void;
}

/** Buffered form. Same pipeline, same guarantees, one JSON response. */
export async function ask(payload: AskRequest): Promise<AskResponse> {
  return api.post<AskResponse>(
    "/v1/ask",
    { lang: "en", ...payload },
    { auth: true },
  );
}

export async function askStream(
  payload: AskRequest,
  handlers: AskHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const send = async (retried: boolean): Promise<Response> => {
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    };
    const token = getAccessToken();
    if (token) headers.Authorization = `Bearer ${token}`;
    const response = await fetch(`${API_BASE}/v1/ask`, {
      method: "POST",
      headers,
      body: JSON.stringify({ lang: "en", ...payload }),
      signal,
    });
    if (response.status === 401 && !retried && (await refreshTokens())) {
      return send(true);
    }
    return response;
  };

  const response = await send(false);

  const limit = response.headers.get("X-RateLimit-Limit");
  if (limit) {
    onRateLimit("/v1/ask", {
      limit: Number(limit),
      remaining: Number(response.headers.get("X-RateLimit-Remaining") ?? 0),
      resetAfter: Number(response.headers.get("X-RateLimit-Reset") ?? 0),
    });
  }

  if (!response.ok) {
    let body: ApiErrorBody | null = null;
    try {
      body = (await response.json()) as ApiErrorBody;
    } catch {
      /* non-JSON error body */
    }
    const error = new ApiError(
      response.status,
      body?.error.code ?? "internal_error",
      body?.error.message ?? `Request failed with status ${response.status}.`,
      body?.error.details ?? {},
      body?.error.request_id ?? null,
    );
    handlers.onError?.(error);
    throw error;
  }

  if (!response.body) {
    throw new ApiError(500, "internal_error", "The server sent no stream.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // SSE frames are separated by a blank line, and sse-starlette writes CRLF,
    // so the separator on the wire is "\r\n\r\n" rather than "\n\n".
    // Normalising first means the parser does not care which the server used.
    buffer = buffer.replace(/\r\n/g, "\n");
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";
    for (const frame of frames) dispatch(frame, handlers);
  }
  if (buffer.trim()) dispatch(buffer, handlers);
}

function dispatch(frame: string, handlers: AskHandlers) {
  let name = "";
  const dataLines: string[] = [];
  for (const line of frame.replace(/\r/g, "").split("\n")) {
    // A line beginning ":" is a comment — the server sends these as pings.
    if (line.startsWith(":")) continue;
    if (line.startsWith("event:")) name = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
  }
  if (!name || dataLines.length === 0) return;

  let data: Record<string, unknown>;
  try {
    data = JSON.parse(dataLines.join("\n")) as Record<string, unknown>;
  } catch {
    return;
  }

  switch (name) {
    case "sources":
      handlers.onSources?.((data.sources ?? []) as SourceBlock[]);
      break;
    case "token":
      handlers.onToken?.(String(data.text ?? ""), data.replaces_all === true);
      break;
    case "citation":
      handlers.onCitation?.(String(data.citation_id), Number(data.section_id));
      break;
    case "invalidated":
      handlers.onInvalidated?.(
        String(data.reason ?? "citation_out_of_context"),
        String(data.message ?? "Correcting the answer."),
      );
      break;
    case "abstain":
      handlers.onAbstain?.({
        reason: (data.reason as string | null) ?? null,
        message: String(data.message ?? ""),
        top_score: (data.top_score as number | null) ?? null,
        score_floor: Number(data.score_floor ?? 0),
      });
      break;
    case "error":
      handlers.onError?.(
        new ApiError(
          500,
          (data.code as never) ?? "internal_error",
          String(data.message ?? "The stream failed."),
        ),
      );
      break;
    case "done":
      handlers.onDone?.(data as unknown as AskDonePayload);
      break;
  }
}

// --- citation parsing ------------------------------------------------------

/**
 * Split an answer into text and citation markers.
 *
 * Mirrors the server's own parser exactly: any bracketed group is scanned for
 * `S<digits>`, so `[S1107]`, `[S19(c)]` and `[S18(1)(d), S1107]` all resolve.
 * Statute text carries footnote markers like `[1]` and `[2][State Government]`
 * — those contain no `S<digits>` and must stay as literal text, which is why
 * the citation scheme uses a letter prefix in the first place.
 */
export type AnswerPart =
  | { kind: "text"; value: string }
  | { kind: "citation"; raw: string; sectionIds: number[] };

const BRACKETED = /\[([^[\]]*)\]/g;
const SECTION_REF = /\bS(\d{1,12})\b/g;

export function parseAnswer(answer: string): AnswerPart[] {
  const parts: AnswerPart[] = [];
  let cursor = 0;
  for (const match of answer.matchAll(BRACKETED)) {
    const ids = [...match[1].matchAll(SECTION_REF)].map((m) => Number(m[1]));
    if (ids.length === 0) continue; // a footnote marker, not a citation
    const start = match.index ?? 0;
    if (start > cursor) {
      parts.push({ kind: "text", value: answer.slice(cursor, start) });
    }
    parts.push({ kind: "citation", raw: match[0], sectionIds: ids });
    cursor = start + match[0].length;
  }
  if (cursor < answer.length) {
    parts.push({ kind: "text", value: answer.slice(cursor) });
  }
  return parts;
}
