import type { NextConfig } from "next";

const requestedDistDir = process.env.NEXT_DIST_DIR?.trim();
if (requestedDistDir && !/^\.next-[a-z0-9-]+$/iu.test(requestedDistDir)) {
  throw new Error("NEXT_DIST_DIR must be a relative .next-<name> directory");
}

const nextConfig: NextConfig = {
  distDir: requestedDistDir || ".next",
};

export default nextConfig;
