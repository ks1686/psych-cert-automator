import path from "node:path";
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  test: {
    environment: "jsdom",
    setupFiles: ["./ui/src/test/setup.ts"],
    include: ["ui/src/**/*.{test,spec}.{ts,tsx}"],
    css: true,
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./ui/src"),
      "@tauri-apps/plugin-dialog": path.resolve(
        __dirname,
        "./ui/src/test/e2e-dialog-stub.ts",
      ),
    },
  },
});
