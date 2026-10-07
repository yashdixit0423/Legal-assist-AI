/**
 * Chat documents — POST/DELETE /v1/chat/documents (docs/adr/0005).
 *
 * The upload uses XMLHttpRequest rather than fetch for one reason: fetch
 * cannot report upload progress, and a 10 MB PDF on a slow connection needs a
 * progress bar. Errors still arrive as the same typed `ApiError`.
 */

import { ApiError } from "./client";
import { API_BASE } from "./config";
import { getAccessToken, refreshTokens } from "./tokens";
import type { ApiErrorBody, DocumentResponse } from "./types";

function send(
  file: File,
  onProgress: (percent: number) => void,
): Promise<{ status: number; body: string }> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE}/v1/chat/documents`);
    const token = getAccessToken();
    if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) {
        // Uploading is most of the wait but not all of it: the server still
        // has to read and index the text, so the bar holds at 90% until then.
        onProgress(Math.round((event.loaded / event.total) * 90));
      }
    };
    xhr.onload = () => resolve({ status: xhr.status, body: xhr.responseText });
    xhr.onerror = () => reject(new TypeError("Network request failed"));
    const form = new FormData();
    form.append("file", file);
    xhr.send(form);
  });
}

function toError(status: number, body: string): ApiError {
  let parsed: ApiErrorBody | null = null;
  try {
    parsed = JSON.parse(body) as ApiErrorBody;
  } catch {
    /* non-JSON body */
  }
  return new ApiError(
    status,
    parsed?.error.code ?? "internal_error",
    parsed?.error.message ?? `Upload failed with status ${status}.`,
    parsed?.error.details ?? {},
    parsed?.error.request_id ?? null,
  );
}

export async function uploadDocument(
  file: File,
  onProgress: (percent: number) => void,
): Promise<DocumentResponse> {
  let result = await send(file, onProgress);
  if (result.status === 401 && (await refreshTokens())) {
    result = await send(file, onProgress);
  }
  if (result.status < 200 || result.status >= 300) {
    throw toError(result.status, result.body);
  }
  onProgress(100);
  return JSON.parse(result.body) as DocumentResponse;
}

/**
 * Forget a document now. Best effort by design: the server forgets it after
 * an hour idle anyway. `keepalive` lets the request outlive a closing tab —
 * `sendBeacon` cannot carry the Authorization header.
 */
export function deleteDocument(documentId: string, keepalive = false): void {
  const token = getAccessToken();
  void fetch(
    `${API_BASE}/v1/chat/documents/${encodeURIComponent(documentId)}`,
    {
      method: "DELETE",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      keepalive,
    },
  ).catch(() => {
    /* expiry is the backstop */
  });
}
