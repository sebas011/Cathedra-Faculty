import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { existsSync, readFileSync } from "node:fs";

const releaseVersion = readFileSync(new URL("../VERSION", import.meta.url), "utf-8").trim();
const buildFile = new URL("../BUILD_ID", import.meta.url);
const buildIdentity = existsSync(buildFile) ? readFileSync(buildFile, "utf-8").trim() : "development";
const product = readFileSync(new URL("../APP_PRODUCT", import.meta.url), "utf-8").trim();
if (product !== "faculty") throw new Error("Invalid Cathedra product");

export default defineConfig({
  plugins: [react(), {
    name: "cathedra-release-version",
    generateBundle() {
      this.emitFile({ type: "asset", fileName: "release-version.txt", source: releaseVersion });
      this.emitFile({ type: "asset", fileName: "build-id.txt", source: buildIdentity });
    },
  }],
  define: {
    "import.meta.env.VITE_CATHEDRA_VERSION": JSON.stringify(releaseVersion),
  },
  server: {
    host: "127.0.0.1",
    port: 5175,
    strictPort: true,
  },
});
