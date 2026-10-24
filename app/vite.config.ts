import { cpSync, existsSync, mkdirSync } from "node:fs";
import { resolve } from "node:path";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";

// The UI uses the same bundled Noto fonts as the PDF/DOCX exporter (repo /fonts): copied, never fetched.
function bundledFonts(): Plugin {
  return {
    name: "sabhalekh-bundled-fonts",
    buildStart() {
      const src = resolve(__dirname, "../fonts");
      const dst = resolve(__dirname, "public/fonts");
      if (existsSync(src)) {
        mkdirSync(dst, { recursive: true });
        cpSync(src, dst, { recursive: true, filter: (p) => !p.endsWith(".txt") || p.endsWith("OFL.txt") });
      }
    },
  };
}

export default defineConfig({
  plugins: [bundledFonts(), react(), tailwindcss()],
  clearScreen: false,
  server: { port: 1420, strictPort: true, host: "localhost" },
  build: { target: "es2022", sourcemap: false, chunkSizeWarningLimit: 1200 },
  test: { environment: "node" },
});
