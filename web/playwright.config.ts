import { existsSync, mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { defineConfig, devices } from "@playwright/test";

// End-to-end smoke tests. They start their own API (port 8100, throwaway SQLite, mock AI)
// and their own production web build (port 3100, built into .next-e2e.nosync), so a dev setup
// running on 3300/8300 is never touched.
const API_PORT = 8100;
const WEB_PORT = 3100;
const dataDir = join(tmpdir(), `mindmesh-e2e-${process.pid}`);
mkdirSync(dataDir, { recursive: true });
const python = process.env.E2E_PYTHON ?? (existsSync("../backend/.venv/bin/python") ? ".venv/bin/python" : "python");

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: `http://localhost:${WEB_PORT}`,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: `${python} -m uvicorn app.main:app --port ${API_PORT}`,
      cwd: "../backend",
      url: `http://localhost:${API_PORT}/docs`,
      reuseExistingServer: false,
      timeout: 60_000,
      env: {
        APP_ENV: "test",
        AI_PROVIDER: "mock",
        DATABASE_URL: `sqlite:///${dataDir}/e2e.db`,
        STORAGE_DIR: `${dataDir}/uploads`,
        CORS_ORIGINS: `http://localhost:${WEB_PORT}`,
        JOB_BACKEND: "inline",
        // The suite makes several signed-out reports from one IP; retries would hit the real limit of 5.
        PUBLIC_REPORT_PER_IP_PER_HOUR: "1000",
      },
    },
    {
      command: `npx next build && npx next start --port ${WEB_PORT}`,
      url: `http://localhost:${WEB_PORT}/welcome`,
      reuseExistingServer: false,
      timeout: 240_000,
      env: {
        NEXT_DIST_DIR: ".next-e2e.nosync",
        NEXT_PUBLIC_API_URL: `http://localhost:${API_PORT}`,
      },
    },
  ],
});
