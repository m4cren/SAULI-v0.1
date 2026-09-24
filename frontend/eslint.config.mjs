import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTypescript from "eslint-config-next/typescript";

export default defineConfig([
  ...nextVitals,
  ...nextTypescript,
  // Local previews and signed, short-lived URLs must not pass through an image cache.
  { rules: { "@next/next/no-img-element": "off" } },
  globalIgnores([".next/**", "node_modules/**", "next-env.d.ts"]),
]);
