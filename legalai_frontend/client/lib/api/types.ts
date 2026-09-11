/**
 * Types transcribed from the running backend's OpenAPI document at
 * http://localhost:8000/docs — not inferred, not guessed.
 *
 * If a field is not here, it does not exist. Do not add speculative fields:
 * the whole point of this client is that nothing reaches the screen that the
 * backend did not say.
 */

// --- errors ----------------------------------------------------------------

/** Every error the API returns uses this envelope. */
export interface ApiErrorBody {
  error: {
    code: ApiErrorCode;
    message: string;
    details?: Record<string, unknown>;
    request_id: string;
  };
}

export type ApiErrorCode =
  | "missing_provider_key"
  | "provider_key_invalid"
  | "provider_quota_exceeded"
  | "provider_timeout"
  | "provider_error"
  | "rate_limited"
  | "unauthenticated"
  | "forbidden"
  | "not_found"
  | "invalid_request"
  | "conflict"
  | "database_unavailable"
  | "service_unavailable"
  | "corpus_error"
  | "retrieval_failed"
  | "citation_validation_failed"
  | "configuration_error"
  | "internal_error";

// --- auth ------------------------------------------------------------------

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  /** Access-token lifetime in seconds. */
  expires_in: number;
}

export interface UserResponse {
  id: string;
  email: string;
  is_active: boolean;
  created_at: string;
}

// --- corpus ----------------------------------------------------------------

export interface StatuteSummary {
  slug: string;
  short_title: string;
  long_title: string | null;
  act_number: string | null;
  year: number;
  jurisdiction: string;
  level: string;
  ministry: string | null;
  /** Sections in force, not rows held. */
  section_count: number;
  as_of_date: string;
  is_repealed: boolean;
  source_portal: string;
  source_url: string;
}

export interface SectionIndexEntry {
  id: number;
  section_no: string;
  marginal_note: string | null;
  is_omitted: boolean;
}

export interface PartNode {
  id: number;
  kind: string;
  number: string | null;
  heading: string | null;
  children: PartNode[];
  section_ids: number[];
}

export interface StatuteDetail extends StatuteSummary {
  parts: PartNode[];
  /**
   * False for every Act today: India Code's API carries no per-section
   * chapter field and the headings are not in the section text either, so the
   * tree is genuinely unknown rather than merely unloaded. Hide the navigation
   * entirely when this is false — an empty list reads as "no chapters", which
   * is untrue.
   */
  parts_available: boolean;
  /** Already in legal citation order. Never re-sort. */
  sections: SectionIndexEntry[];
  sections_total: number;
  sections_in_force: number;
}

export interface RelatedSection {
  id: number;
  statute_slug: string;
  statute_short_title: string;
  section_no: string;
  marginal_note: string | null;
  relation: string;
  direction: "outbound" | "inbound";
}

export interface SectionDetail {
  id: number;
  statute_slug: string;
  statute_short_title: string;
  section_no: string;
  marginal_note: string | null;
  /** Verbatim source text. Footnote markers are inline as [N]. */
  text: string;
  footnotes: Record<string, unknown>[];
  amendment_note: string | null;
  commenced_on: string | null;
  as_of_date: string;
  is_omitted: boolean;
  /** Always null for now — the explanations job is deferred. */
  explanation: string | null;
  related: RelatedSection[];
  source_url: string;
}

// --- search ----------------------------------------------------------------

export interface SearchHit {
  section_id: number;
  statute_slug: string;
  statute: string;
  section_no: string;
  marginal_note: string | null;
  snippet: string;
  /** Reciprocal Rank Fusion score. NOT a probability. Never render as a %. */
  score: number;
  dense_rank: number | null;
  sparse_rank: number | null;
}

export interface SearchResponse {
  query: string;
  total: number;
  hits: SearchHit[];
  /** Search deliberately skips the cross-encoder to stay fast. */
  reranked: boolean;
}

// --- ask -------------------------------------------------------------------

export interface Turn {
  role: "user" | "assistant";
  content: string;
}

export interface AskRequest {
  question: string;
  lang?: "en";
  /** Client-held history, max 6. The server stores nothing. */
  turns?: Turn[];
  statute_slug?: string | null;
}

export interface SourceBlock {
  /** The id the answer cites, e.g. "S1046". */
  citation_id: string;
  section_id: number;
  statute: string;
  statute_slug: string;
  section_no: string;
  marginal_note: string | null;
  /** "cross_reference" means it was pulled in because a retrieved section cites it. */
  origin: "retrieved" | "cross_reference";
  rerank_score: number | null;
  /** True when the answer actually cited this block. */
  cited: boolean;
}

export interface AskResponse {
  answered: boolean;
  /** True is a SUCCESSFUL outcome at HTTP 200, not an error. */
  abstained: boolean;
  answer: string;
  sources: SourceBlock[];
  cited_section_ids: number[];
  top_score: number | null;
  score_floor: number;
  abstain_reason: string | null;
  citation_violation: boolean;
  model: string | null;
  prompt_version: string;
  tokens_in: number | null;
  tokens_out: number | null;
  latency_ms: number;
  turns_used: boolean;
  rewritten_question: string | null;
}

// --- credentials -----------------------------------------------------------

export type Provider =
  "anthropic" | "openai" | "google" | "groq" | "openrouter";

export const PROVIDERS: Provider[] = [
  "anthropic",
  "openai",
  "google",
  "groq",
  "openrouter",
];

/** Metadata only. There is deliberately no field that could carry the key. */
export interface CredentialResponse {
  provider: string;
  /** Last four characters, so a person can tell which key is stored. */
  key_hint: string | null;
  key_version: number;
  last_verified_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface VerifyCredentialResponse {
  provider: string;
  valid: boolean;
  checked_at: string;
  error_code: string | null;
  message: string | null;
}

// --- health ----------------------------------------------------------------

export interface HealthResponse {
  status: "ok" | "degraded";
  version: string;
  app_env: string;
  database: {
    connected: boolean;
    schema_ready: boolean;
    latency_ms: number | null;
    error: string | null;
  };
  corpus: {
    statutes: number;
    sections: number;
    chunks: number;
    chunks_embedded: number;
    links: number;
    vector_index_ready: boolean;
    /** False while a bulk embed has the index dropped. */
    retrieval_ready: boolean;
    last_ingest_at: string | null;
  };
}

// --- SSE -------------------------------------------------------------------

export type AskEventName =
  | "sources"
  | "token"
  | "citation"
  | "invalidated"
  | "abstain"
  | "error"
  | "done";

export interface AskDonePayload {
  answered: boolean;
  abstained: boolean;
  cited_section_ids: number[];
  citation_violation: boolean;
  model: string | null;
  prompt_version: string;
  tokens_in: number | null;
  tokens_out: number | null;
  latency_ms: number;
}

export interface RateLimit {
  limit: number;
  remaining: number;
  resetAfter: number;
}
