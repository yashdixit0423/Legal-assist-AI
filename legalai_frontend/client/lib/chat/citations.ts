/**
 * Document citation markers in a Chat answer — `[D1-p4]`, `[D2-para12]`.
 *
 * Statute markers (`[S<id>]`) are still parsed by the shared `parseAnswer`;
 * this only runs over the text it leaves behind, so the two schemes can never
 * claim the same characters.
 */

export type DocumentPart =
  | { kind: "text"; value: string }
  | { kind: "document"; raw: string; citationIds: string[] };

const BRACKETED = /\[([^[\]]*)\]/g;
const DOCUMENT_REF = /\bD(\d{1,2})-(p|para)(\d{1,6})\b/g;

export function parseDocumentRefs(text: string): DocumentPart[] {
  const parts: DocumentPart[] = [];
  let cursor = 0;
  for (const match of text.matchAll(BRACKETED)) {
    const ids = [...match[1].matchAll(DOCUMENT_REF)].map(
      (m) => `D${Number(m[1])}-${m[2]}${Number(m[3])}`,
    );
    if (ids.length === 0) continue;
    const start = match.index ?? 0;
    if (start > cursor)
      parts.push({ kind: "text", value: text.slice(cursor, start) });
    parts.push({ kind: "document", raw: match[0], citationIds: ids });
    cursor = start + match[0].length;
  }
  if (cursor < text.length)
    parts.push({ kind: "text", value: text.slice(cursor) });
  return parts;
}

/** "p. 4" or "¶ 12": how a passage's position reads inline. */
export const locatorLabel = (kind: "page" | "para", locator: number) =>
  kind === "page" ? `p. ${locator}` : `¶ ${locator}`;
