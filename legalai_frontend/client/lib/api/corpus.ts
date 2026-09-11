/** Corpus reads and search. All public — no token, by design (spec §06). */

import { api } from "./client";
import type {
  CredentialResponse,
  HealthResponse,
  Provider,
  SearchResponse,
  SectionDetail,
  StatuteDetail,
  StatuteSummary,
  VerifyCredentialResponse,
} from "./types";

export const listStatutes = () => api.get<StatuteSummary[]>("/v1/statutes");

export const getStatute = (slug: string) =>
  api.get<StatuteDetail>(`/v1/statutes/${encodeURIComponent(slug)}`);

export const getSection = (id: number) =>
  api.get<SectionDetail>(`/v1/sections/${id}`);

export const getSectionByNumber = (slug: string, sectionNo: string) =>
  api.get<SectionDetail>(
    `/v1/statutes/${encodeURIComponent(slug)}/sections/${encodeURIComponent(sectionNo)}`,
  );

export const search = (params: {
  q: string;
  statute_slug?: string | null;
  limit?: number;
  include_omitted?: boolean;
}) => api.post<SearchResponse>("/v1/search", { limit: 20, ...params });

export const health = () => api.get<HealthResponse>("/v1/health");

// --- the write-only vault --------------------------------------------------

export const listCredentials = () =>
  api.get<CredentialResponse[]>("/v1/credentials", { auth: true });

export const putCredential = (provider: Provider, apiKey: string) =>
  api.put<CredentialResponse>(
    "/v1/credentials",
    { provider, api_key: apiKey },
    { auth: true },
  );

export const deleteCredential = (provider: string) =>
  api.delete<void>(`/v1/credentials/${encodeURIComponent(provider)}`, {
    auth: true,
  });

/** Returns 200 with valid:false for a bad key — it is an answer, not a failure. */
export const verifyCredential = (provider: Provider, apiKey?: string) =>
  api.post<VerifyCredentialResponse>(
    "/v1/credentials/verify",
    apiKey ? { provider, api_key: apiKey } : { provider },
    { auth: true },
  );
