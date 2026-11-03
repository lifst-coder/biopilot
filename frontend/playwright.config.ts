/**
 * End-to-end suite: the real FastAPI backend (fresh SQLite per run, rules mode) behind the
 * Vite dev server, one stack per seed profile.
 *
 *   reference → backend :8101, UI :5181   (e2e/reference.spec.ts)
 *   lab       → backend :8102, UI :5182   (e2e/lab.spec.ts, BIOPILOT_SEED_PROFILE=lab)
 *
 * Run: `npm run e2e` (backend deps installed; E2E_PYTHON picks the interpreter, default
 * `python`). Uses the pre-installed Chromium; no network calls (ANTHROPIC_API_KEY unset).
 */
import { defineConfig, devices } from "@playwright/test";

const python = process.env.E2E_PYTHON ?? "python";
const backend = (profile: "reference" | "lab", port: number) => ({
  command:
    `rm -rf .e2e/${profile} && mkdir -p .e2e/${profile} && ` +
    `${python} -m uvicorn app.main:app --port ${port}`,
  cwd: "../backend",
  env: {
    BIOPILOT_DATABASE_URL: `sqlite:///./.e2e/${profile}/biopilot.db`,
    BIOPILOT_ELN_STORAGE_DIR: `./.e2e/${profile}/eln_storage`,
    BIOPILOT_SEED_PROFILE: profile,
    BIOPILOT_FORCE_RULES_MODE: "true",
    ANTHROPIC_API_KEY: "",
  },
  url: `http://127.0.0.1:${port}/api/health`,
  timeout: 240_000,
  reuseExistingServer: false,
});
const ui = (port: number, api: number) => ({
  command: `npx vite --port ${port} --strictPort`,
  env: { BIOPILOT_API_PROXY: `http://127.0.0.1:${api}` },
  url: `http://127.0.0.1:${port}/`,
  timeout: 120_000,
  reuseExistingServer: false,
});

export default defineConfig({
  testDir: "e2e",
  timeout: 120_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  use: { ...devices["Desktop Chrome"], trace: "retain-on-failure", screenshot: "only-on-failure" },
  projects: [
    { name: "reference", testMatch: /reference\.spec\.ts/, use: { baseURL: "http://127.0.0.1:5181" } },
    { name: "lab", testMatch: /lab\.spec\.ts/, use: { baseURL: "http://127.0.0.1:5182" } },
  ],
  webServer: [backend("reference", 8101), ui(5181, 8101), backend("lab", 8102), ui(5182, 8102)],
});
