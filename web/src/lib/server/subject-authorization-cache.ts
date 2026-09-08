export const SUBJECT_AUTHORIZATION_CACHE_TTL_MS = 30_000;

type AuthorizeSubject = (subjectId: string) => Promise<boolean>;

type CacheEntry = {
  expiresAt: number;
};

export type SubjectAuthorizationResult = {
  allowed: boolean;
  cacheHit: boolean;
};

export function createSubjectAuthorizationCache(
  authorize: AuthorizeSubject,
  options: {
    ttlMs?: number;
    now?: () => number;
  } = {},
) {
  const ttlMs = options.ttlMs ?? SUBJECT_AUTHORIZATION_CACHE_TTL_MS;
  const now = options.now ?? (() => Date.now());
  const approved = new Map<string, CacheEntry>();
  const pending = new Map<string, Promise<boolean>>();

  return async function authorizeWithCache(subjectId: string): Promise<SubjectAuthorizationResult> {
    const currentTime = now();
    const cached = approved.get(subjectId);
    if (cached && cached.expiresAt > currentTime) return { allowed: true, cacheHit: true };
    if (cached) approved.delete(subjectId);

    const existing = pending.get(subjectId);
    if (existing) return { allowed: await existing, cacheHit: true };

    const lookup = authorize(subjectId);
    pending.set(subjectId, lookup);
    try {
      const allowed = await lookup;
      // Only successful approvals are cached. Revoked, missing, and failed lookups
      // continue to fail closed without a negative-cache delay.
      if (allowed) approved.set(subjectId, { expiresAt: now() + ttlMs });
      return { allowed, cacheHit: false };
    } finally {
      pending.delete(subjectId);
    }
  };
}
