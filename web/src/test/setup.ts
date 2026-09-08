import "@testing-library/jest-dom/vitest";
import { vi } from "vitest";

// Route tests run without Next's incremental-cache request context. Production
// still uses the real Data Cache; tests exercise the wrapped loader directly.
vi.mock("next/cache", () => ({
  unstable_cache: (loader: unknown) => loader,
}));
