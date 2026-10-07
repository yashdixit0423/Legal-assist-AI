/**
 * Client-side checks for documents attached to Chat.
 *
 * These are a courtesy, not the boundary: the server re-checks size and type
 * from the bytes themselves and ignores what the browser claims. Checking here
 * just means a wrong file is refused before it is uploaded at all.
 */

export type DocumentKind = "pdf" | "txt" | "docx";

/** Documents are off until the backend that reads them ships (Phase 6). */
export const DOCUMENTS_ENABLED =
  (import.meta.env.VITE_CHAT_DOCUMENTS as string | undefined) === "true";

export const MAX_FILE_BYTES = 10 * 1024 * 1024;
export const MAX_FILES = 3;
export const ACCEPT = ".pdf,.txt,.docx";
export const FORMATS_LABEL = "PDF, TXT, DOCX";

const BY_EXTENSION: Record<string, DocumentKind> = {
  pdf: "pdf",
  txt: "txt",
  docx: "docx",
};

const MIME: Record<DocumentKind, string[]> = {
  pdf: ["application/pdf"],
  txt: ["text/plain"],
  docx: [
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  ],
};

export type FileCheck =
  { ok: true; kind: DocumentKind } | { ok: false; reason: string };

const startsWith = (bytes: Uint8Array, signature: number[]) =>
  signature.every((value, index) => bytes[index] === value);

/** Extension, then the browser's MIME type, then the file's own first bytes. */
export async function checkFile(file: File): Promise<FileCheck> {
  const extension = file.name.split(".").pop()?.toLowerCase() ?? "";
  const kind = BY_EXTENSION[extension];
  if (!kind) {
    return { ok: false, reason: `Only ${FORMATS_LABEL} files are supported.` };
  }
  // An empty type is common for .docx and .txt on some systems; a *different*
  // non-empty type means the file is not what its name says.
  if (file.type && !MIME[kind].includes(file.type)) {
    return { ok: false, reason: "That file's type doesn't match its name." };
  }
  if (file.size === 0) return { ok: false, reason: "That file is empty." };
  if (file.size > MAX_FILE_BYTES) {
    return { ok: false, reason: "Files can be up to 10 MB." };
  }

  const head = new Uint8Array(await file.slice(0, 4096).arrayBuffer());
  if (kind === "pdf" && !startsWith(head, [0x25, 0x50, 0x44, 0x46])) {
    return { ok: false, reason: "That file is not a valid PDF." };
  }
  if (kind === "docx" && !startsWith(head, [0x50, 0x4b, 0x03, 0x04])) {
    return { ok: false, reason: "That file is not a valid DOCX document." };
  }
  if (kind === "txt" && head.includes(0)) {
    return { ok: false, reason: "That file is not plain text." };
  }
  return { ok: true, kind };
}

/** For display only: control characters stripped, long names shortened in the middle. */
export function displayName(name: string, max = 36): string {
  // eslint-disable-next-line no-control-regex
  const clean = name
    .replace(/[\u0000-\u001f\u007f]/g, "")
    .replace(/\s+/g, " ")
    .trim();
  if (clean.length <= max) return clean || "Untitled";
  const keep = max - 1;
  return `${clean.slice(0, Math.ceil(keep * 0.6))}…${clean.slice(-Math.floor(keep * 0.4))}`;
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
