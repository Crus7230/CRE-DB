import type { LookupCard, LookupSource, ResolvedLookupKind } from "@/lib/smart-lookup-contract";

export interface LookupCredentials {
  vworldKey?: string;
  publicDataKey?: string;
  dartKey?: string;
  krxKey?: string;
}

export interface LookupContext {
  credentials: LookupCredentials;
  requestJson: (url: string, init?: RequestInit) => Promise<unknown>;
  requestBytes: (url: string, init?: RequestInit) => Promise<Uint8Array>;
  now: () => Date;
}

export interface ProviderCandidate {
  kind: ResolvedLookupKind;
  title: string;
  subtitle: string;
  sourceLabel: string;
  identity: Record<string, string>;
}

export interface ProviderResult {
  candidates: ProviderCandidate[];
  cards: LookupCard[];
  sources: LookupSource[];
  message?: string;
}

export class LookupProviderError extends Error {
  constructor(readonly code: "timeout" | "http" | "invalid_response" | "too_large" | "configuration") {
    super(code);
    this.name = "LookupProviderError";
  }
}
