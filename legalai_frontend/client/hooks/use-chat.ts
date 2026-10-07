import { useCallback, useEffect, useRef, useState } from "react";
import { askStream } from "@/lib/api/ask";
import { ApiError } from "@/lib/api/client";
import type { AskDonePayload, SourceBlock, Turn } from "@/lib/api/types";
import { MAX_FILES, checkFile, type DocumentKind } from "@/lib/chat/files";

/**
 * The Chat conversation, held in memory only.
 *
 * Nothing here is persisted — not to sessionStorage, not to the server. A
 * reload starts a new chat, and the UI says so. Each question goes through the
 * unchanged `/v1/ask` pipeline, so the gate, the citation validator and the
 * abstention behave exactly as they do on Ask; the only thing Chat adds is
 * that earlier answered exchanges travel along as `turns`.
 */

/** The same rule Ask applies: six turns, built only from answered exchanges. */
const MAX_TURNS = 6;

export type ChatStatus = "streaming" | "done" | "stopped" | "error";

/** What the stream has actually reached — the loading copy reads from this. */
export type ChatPhase = "searching" | "preparing" | "writing";

export interface ChatAbstention {
  reason: string | null;
  topScore: number | null;
  scoreFloor: number;
}

/** A document attached to the conversation. The bytes stay in the browser's memory. */
export interface ChatAttachment {
  id: string;
  name: string;
  kind: DocumentKind;
  size: number;
  /** Kept so the user can reopen their own file; never persisted. */
  file?: File;
  status: "uploading" | "ready" | "error";
  /** 0-100 while uploading. */
  progress: number;
  /** The server's id once the document has been read (Phase 6). */
  documentId?: string;
  pages?: number | null;
  error?: string;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  sources: SourceBlock[];
  citedIds: number[];
  abstain?: ChatAbstention;
  error?: ApiError;
  status: ChatStatus;
  phase?: ChatPhase;
  /** A drafted answer cited outside the retrieved set and is being rewritten. */
  invalidating?: boolean;
  done?: AskDonePayload;
  /** On a user message: the documents in play when it was sent. */
  attachments?: ChatAttachment[];
}

let counter = 0;
const nextId = () => `m${Date.now().toString(36)}${(counter++).toString(36)}`;

/** `fetch` rejects with a TypeError when the server cannot be reached at all. */
function toApiError(caught: unknown): ApiError {
  if (caught instanceof ApiError) return caught;
  if (caught instanceof TypeError) {
    return new ApiError(
      0,
      "service_unavailable",
      "Couldn't reach the LegalAssist server. Check your connection and try again.",
    );
  }
  return new ApiError(
    500,
    "internal_error",
    "The request failed unexpectedly.",
  );
}

const isAbort = (caught: unknown) =>
  caught instanceof DOMException && caught.name === "AbortError";

/** Answered exchanges before `uptoIndex`, as `/v1/ask` expects them. */
function buildTurns(messages: ChatMessage[], uptoIndex: number): Turn[] {
  const turns: Turn[] = [];
  for (let i = 1; i < uptoIndex; i++) {
    const answer = messages[i];
    const question = messages[i - 1];
    if (
      answer.role === "assistant" &&
      question.role === "user" &&
      answer.status === "done" &&
      answer.done?.answered
    ) {
      turns.push({ role: "user", content: question.text });
      turns.push({ role: "assistant", content: answer.text });
    }
  }
  return turns.slice(-MAX_TURNS);
}

function placeholder(): ChatMessage {
  return {
    id: nextId(),
    role: "assistant",
    text: "",
    sources: [],
    citedIds: [],
    status: "streaming",
    phase: "searching",
  };
}

export function useChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [attachments, setAttachments] = useState<ChatAttachment[]>([]);
  const attachmentsRef = useRef<ChatAttachment[]>([]);
  attachmentsRef.current = attachments;
  const messagesRef = useRef<ChatMessage[]>([]);
  messagesRef.current = messages;
  const abort = useRef<AbortController | null>(null);

  // Leaving the page must not leave a provider streaming on the user's key.
  useEffect(() => () => abort.current?.abort(), []);

  const patch = useCallback(
    (id: string, change: (message: ChatMessage) => Partial<ChatMessage>) =>
      setMessages((list) =>
        list.map((m) => (m.id === id ? { ...m, ...change(m) } : m)),
      ),
    [],
  );

  /** Stream an answer into the assistant message `id`. */
  const run = useCallback(
    async (id: string, question: string, turns: Turn[]) => {
      abort.current?.abort();
      const controller = new AbortController();
      abort.current = controller;

      let accumulated = "";
      let finished = false;
      try {
        await askStream(
          { question, turns },
          {
            onSources: (sources) =>
              patch(id, () => ({ sources, phase: "preparing" })),
            onToken: (chunk, replacesAll) => {
              accumulated = replacesAll ? chunk : accumulated + chunk;
              patch(id, () => ({
                text: accumulated,
                invalidating: false,
                // The server sends an empty token to keep a rewritten
                // question's connection warm; that is not writing yet.
                ...(accumulated ? { phase: "writing" as const } : {}),
              }));
            },
            onInvalidated: () => {
              // Everything rendered so far is void; a corrected answer follows.
              accumulated = "";
              patch(id, () => ({ text: "", invalidating: true }));
            },
            onAbstain: (payload) => {
              accumulated = payload.message;
              patch(id, () => ({
                text: payload.message,
                invalidating: false,
                abstain: {
                  reason: payload.reason,
                  topScore: payload.top_score,
                  scoreFloor: payload.score_floor,
                },
              }));
            },
            onDone: (done) => {
              finished = true;
              patch(id, () => ({
                citedIds: done.cited_section_ids,
                done,
                status: "done",
                phase: undefined,
              }));
            },
            onError: (error) => {
              finished = true;
              patch(id, () => ({
                error,
                status: "error",
                phase: undefined,
                invalidating: false,
              }));
            },
          },
          controller.signal,
        );
        if (!finished && !controller.signal.aborted) {
          patch(id, () => ({
            status: "error",
            phase: undefined,
            error: new ApiError(
              500,
              "internal_error",
              "The answer stream ended before it finished.",
            ),
          }));
        }
      } catch (caught) {
        if (isAbort(caught) || controller.signal.aborted) {
          patch(id, (m) =>
            m.status === "streaming"
              ? { status: "stopped", phase: undefined, invalidating: false }
              : {},
          );
        } else if (!finished) {
          // askStream reports a non-2xx through onError and then throws; that
          // case is already handled above.
          patch(id, () => ({
            status: "error",
            phase: undefined,
            invalidating: false,
            error: toApiError(caught),
          }));
        }
      } finally {
        if (abort.current === controller) abort.current = null;
      }
    },
    [patch],
  );

  const send = useCallback(
    (text: string) => {
      const question = text.trim();
      if (question.length < 3) return;
      const current = messagesRef.current;
      if (current.some((m) => m.status === "streaming")) return;
      const user: ChatMessage = {
        id: nextId(),
        role: "user",
        text: question,
        sources: [],
        citedIds: [],
        status: "done",
      };
      const ready = attachmentsRef.current.filter((a) => a.status === "ready");
      if (ready.length) user.attachments = ready;
      const answer = placeholder();
      const turns = buildTurns(current, current.length);
      setMessages([...current, user, answer]);
      void run(answer.id, question, turns);
    },
    [run],
  );

  /** Re-ask the question behind assistant message `id`, replacing its answer. */
  const regenerate = useCallback(
    (id: string) => {
      const current = messagesRef.current;
      const index = current.findIndex((m) => m.id === id);
      const question = current[index - 1];
      if (index < 1 || question?.role !== "user") return;
      if (current.some((m) => m.status === "streaming")) return;
      const answer = { ...placeholder(), id };
      setMessages(current.map((m) => (m.id === id ? answer : m)));
      void run(id, question.text, buildTurns(current, index - 1));
    },
    [run],
  );

  const stop = useCallback(() => abort.current?.abort(), []);

  /**
   * Validate and add files. A rejected file still shows as a chip with the
   * reason, so the user sees why rather than nothing happening.
   */
  const attach = useCallback(async (files: File[]) => {
    const room =
      MAX_FILES -
      attachmentsRef.current.filter((a) => a.status !== "error").length;
    for (const [index, file] of files.entries()) {
      const id = nextId();
      const base = { id, name: file.name, size: file.size, file, progress: 0 };
      if (index >= room) {
        setAttachments((list) => [
          ...list,
          {
            ...base,
            kind: "txt",
            status: "error",
            error: `Up to ${MAX_FILES} documents per conversation.`,
          },
        ]);
        continue;
      }
      const check = await checkFile(file);
      if ("reason" in check) {
        setAttachments((list) => [
          ...list,
          { ...base, kind: "txt", status: "error", error: check.reason },
        ]);
        continue;
      }
      setAttachments((list) => [
        ...list,
        { ...base, kind: check.kind, status: "ready", progress: 100 },
      ]);
    }
  }, []);

  const detach = useCallback((id: string) => {
    setAttachments((list) => list.filter((a) => a.id !== id));
  }, []);

  const reset = useCallback(() => {
    abort.current?.abort();
    abort.current = null;
    setMessages([]);
    setAttachments([]);
  }, []);

  return {
    messages,
    streaming: messages.some((m) => m.status === "streaming"),
    send,
    regenerate,
    stop,
    reset,
    attachments,
    attach,
    detach,
  };
}
