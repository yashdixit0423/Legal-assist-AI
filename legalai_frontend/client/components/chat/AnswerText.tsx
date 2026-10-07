import { Children, useMemo, type ReactNode } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { CitationChip } from "@/components/CitationChip";
import { parseAnswer } from "@/lib/api/ask";
import type { SourceBlock } from "@/lib/api/types";
import { useOpenSource } from "./SourcePanel";

type Cite = (children: ReactNode) => ReactNode;

/**
 * Answer prose, rendered as Markdown, with every `[S<id>]` marker turned into
 * the shared citation chip — inside paragraphs, list items, table cells and
 * emphasis alike.
 *
 * Raw HTML in the answer is dropped (`skipHtml`), images are not rendered, and
 * links open in a new tab without a referrer.
 */
export function AnswerText({
  text,
  sources,
}: {
  text: string;
  sources: SourceBlock[];
}) {
  const openSource = useOpenSource();

  // Rebuilt only when the sources change, not on every streamed token, so
  // the rendered tree is updated in place rather than remounted.
  const rendered = useMemo(() => {
    const byId = new Map(sources.map((source) => [source.section_id, source]));
    const chips = (value: string, key: string | number): ReactNode[] =>
      parseAnswer(value).map((part, index) =>
        part.kind === "text" ? (
          part.value
        ) : (
          <span key={`${key}-${index}`} className="mx-0.5 inline-flex gap-1">
            {part.sectionIds.map((id) => (
              <CitationChip
                key={id}
                sectionId={id}
                source={byId.get(id)}
                onOpen={openSource}
              />
            ))}
          </span>
        ),
      );
    const cite: Cite = (children) =>
      Children.map(children, (child, index) =>
        typeof child === "string" ? chips(child, index) : child,
      );
    return components(cite);
  }, [sources, openSource]);

  return (
    <div className="chat-answer">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        skipHtml
        disallowedElements={["img"]}
        components={rendered}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}

function components(cite: Cite): Components {
  type Tag =
    | "p"
    | "li"
    | "td"
    | "th"
    | "strong"
    | "em"
    | "blockquote"
    | "del"
    | "h1"
    | "h2"
    | "h3"
    | "h4"
    | "h5"
    | "h6";
  const wrap =
    (Tag: Tag) =>
    ({ children }: { children?: ReactNode }) => <Tag>{cite(children)}</Tag>;

  return {
    p: wrap("p"),
    li: wrap("li"),
    td: wrap("td"),
    th: wrap("th"),
    strong: wrap("strong"),
    em: wrap("em"),
    blockquote: wrap("blockquote"),
    del: wrap("del"),
    h1: wrap("h1"),
    h2: wrap("h2"),
    h3: wrap("h3"),
    h4: wrap("h4"),
    h5: wrap("h5"),
    h6: wrap("h6"),
    table: ({ children }) => (
      <div className="chat-table-wrap">
        <table>{children}</table>
      </div>
    ),
    a: ({ href, children }) => (
      <a href={href} target="_blank" rel="noreferrer">
        {children}
      </a>
    ),
    // Code spans are left exactly as written: a citation inside backticks is
    // being quoted, not made.
    code: ({ children }) => <code>{children}</code>,
  };
}
