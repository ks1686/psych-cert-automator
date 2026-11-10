import { createRequire } from "node:module";
import fs from "node:fs";
import net from "node:net";
import path from "node:path";

const state = process.env.PSYCH_CERT_STATE;
const repo = process.env.PSYCH_CERT_REPO;
if (!state || !repo) {
  process.stderr.write("PSYCH_CERT_STATE and PSYCH_CERT_REPO are required\n");
  process.exit(1);
}

const require = createRequire(path.join(repo, "package.json"));
const { chromium } = require("@playwright/test");

const sockPath = path.join(state, "browser.sock");
if (fs.existsSync(sockPath)) {
  fs.unlinkSync(sockPath);
}

const browser = await chromium.launch({
  channel: "chrome",
  headless: true,
  args: ["--no-sandbox", "--disable-dev-shm-usage"],
});
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });

function assertUrl() {
  const url = new URL(page.url());
  if (url.protocol !== "http:") {
    throw new Error(`refusing protocol ${url.protocol}`);
  }
  if (url.hostname !== "127.0.0.1") {
    throw new Error(`refusing host ${url.hostname}`);
  }
  if (url.port !== "1420") {
    throw new Error(`refusing port ${url.port}`);
  }
  if (url.pathname !== "/") {
    throw new Error(`path ${url.pathname} !== /`);
  }
}

async function handle(message) {
  const op = message.op;
  const args = Array.isArray(message.args) ? message.args : [];
  if (op === "goto") {
    if (args[0] !== "/") {
      throw new Error("only / is allowed");
    }
    await page.goto("http://127.0.0.1:1420/");
    assertUrl();
    return { ok: true };
  }
  if (op === "expect-url") {
    assertUrl();
    if (args[0] !== "/") {
      throw new Error("only exact path / is accepted");
    }
    return { ok: true };
  }
  if (op === "wait-heading") {
    await page.getByRole("heading", { name: args[0], exact: true }).waitFor({
      timeout: 70000,
    });
    return { ok: true };
  }
  if (op === "click-role") {
    await page.getByRole(args[0], { name: args[1], exact: true }).click({
      timeout: 30000,
    });
    return { ok: true };
  }
  if (op === "fill-label") {
    await page.getByLabel(args[0], { exact: true }).fill(args[1]);
    return { ok: true };
  }
  if (op === "check-role") {
    await page.getByRole(args[0], { name: args[1], exact: true }).check();
    return { ok: true };
  }
  if (op === "expect-enabled") {
    const locator = page.getByRole(args[0], { name: args[1], exact: true });
    if (!(await locator.isEnabled())) {
      throw new Error(`${args[0]} ${args[1]} is disabled`);
    }
    return { ok: true };
  }
  if (op === "expect-output") {
    const text = await page.getByTestId("output-folder-path").innerText();
    if (!text.includes(args[0])) {
      throw new Error(`output folder shows ${text}`);
    }
    return { ok: true };
  }
  if (op === "expect-text") {
    const timeout = Number(args[1] || 30) * 1000;
    await page.getByText(args[0], { exact: true }).first().waitFor({ timeout });
    return { ok: true };
  }
  if (op === "expect-host") {
    const row = page.getByRole("row").filter({ hasText: args[0] });
    const box = row.getByRole("checkbox");
    if (!(await box.isChecked())) {
      throw new Error(`${args[0]} host checkbox is not checked`);
    }
    await row.getByText("Host", { exact: true }).waitFor();
    return { ok: true };
  }
  if (op === "seed-paths") {
    const payload = { zoom: args[0], qualtrics: args[1], output: args[2] };
    await page.evaluate((paths) => {
      window.__E2E_PATHS__ = paths;
    }, payload);
    return { ok: true };
  }
  if (op === "wait-canvas") {
    await page.locator("canvas").first().waitFor({ timeout: 60000 });
    return { ok: true };
  }
  if (op === "screenshot") {
    const width = Number(args[0]);
    const height = Number(args[1]);
    const dest = args[2];
    const full = args[3] === "full";
    if (!dest.startsWith(`${state}${path.sep}`)) {
      throw new Error("screenshot path escapes the state dir");
    }
    await page.setViewportSize({ width, height });
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: dest, fullPage: full });
    await fs.promises.chmod(dest, 0o600);
    return { ok: true };
  }
  if (op === "aria") {
    const dest = args[0];
    if (!dest.startsWith(`${state}${path.sep}`)) {
      throw new Error("aria path escapes the state dir");
    }
    const text = await page.locator("main").ariaSnapshot();
    await fs.promises.writeFile(dest, text, { mode: 0o600 });
    return { ok: true };
  }
  if (op === "scan-side-effects") {
    const hrefs = await page.locator("a[href]").evaluateAll((els) =>
      els.map((el) => el.getAttribute("href") || ""),
    );
    const hits = hrefs.filter((href) => /^(tel|sms|mailto|payment):/i.test(href));
    return { ok: true, data: hits.join("\n") };
  }
  if (op === "download-zip") {
    const dest = args[0];
    if (!dest.startsWith(`${state}${path.sep}`)) {
      throw new Error("download path escapes the state dir");
    }
    const downloadPromise = page.waitForEvent("download");
    await page.getByRole("button", { name: "Download All as ZIP", exact: true }).click();
    const download = await downloadPromise;
    await download.saveAs(dest);
    await fs.promises.chmod(dest, 0o600);
    return { ok: true };
  }
  throw new Error(`unknown op ${op}`);
}

const server = net.createServer((connection) => {
  let buf = "";
  connection.on("data", (chunk) => {
    buf += chunk.toString("utf8");
    const nl = buf.indexOf("\n");
    if (nl < 0) {
      return;
    }
    const line = buf.slice(0, nl);
    buf = "";
    let response;
    try {
      response = handle(JSON.parse(line));
    } catch (error) {
      response = Promise.resolve({
        ok: false,
        error: error instanceof Error ? error.message : String(error),
      });
    }
    Promise.resolve(response)
      .then((value) => {
        connection.end(`${JSON.stringify(value)}\n`);
      })
      .catch((error) => {
        const message = error instanceof Error ? error.message : String(error);
        connection.end(`${JSON.stringify({ ok: false, error: message })}\n`);
      });
  });
});

server.listen(sockPath, () => {
  fs.chmodSync(sockPath, 0o600);
  fs.writeFileSync(path.join(state, "browser.ready"), "ready\n", { mode: 0o600 });
});

process.on("SIGTERM", async () => {
  await browser.close();
  server.close();
  process.exit(0);
});
