import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  timeout: 90000,
  outputDir: "../work/playwright-results",
  reporter: [
    ["list"],
    ["html", { outputFolder: "../work/playwright-report", open: "never" }],
  ],
  use: {
    actionTimeout: 10000,
    baseURL: "http://127.0.0.1:8081",
    browserName: "chromium",
    screenshot: "only-on-failure",
    trace: "off",
  },
});
