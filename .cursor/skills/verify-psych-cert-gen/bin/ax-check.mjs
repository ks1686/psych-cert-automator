import { execFileSync, spawn } from "node:child_process";
import fs from "node:fs";
import http from "node:http";
import path from "node:path";

const work = process.argv[2];
if (!work) {
  process.stderr.write("usage: ax-check.mjs WORKDIR\n");
  process.exit(2);
}
fs.mkdirSync(work, { recursive: true, mode: 0o700 });

function findChrome() {
  const named = [
    process.env.CHROME_PATH,
    "/usr/bin/google-chrome",
    "/usr/local/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  ];
  for (const candidate of named) {
    if (candidate && fs.existsSync(candidate)) {
      return candidate;
    }
  }
  for (const command of ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser"]) {
    try {
      const found = execFileSync("/usr/bin/env", ["bash", "-c", `command -v ${command}`], {
        encoding: "utf8",
      }).trim();
      if (found) {
        return found;
      }
    } catch {
      // try the next name
    }
  }
  return "";
}

const chromePath = findChrome();
if (!chromePath) {
  process.stderr.write("no Chrome or Chromium binary found\n");
  process.exit(1);
}

const htmlPath = path.join(work, "page.html");
fs.writeFileSync(
  htmlPath,
  "<!doctype html><html><body><button aria-label=\"Generate All Certificates\">Go</button></body></html>\n",
  { mode: 0o600 },
);

const profile = path.join(work, "profile");
fs.mkdirSync(profile, { mode: 0o700 });
const chrome = spawn(
  chromePath,
  [
    "--headless=new",
    "--no-sandbox",
    "--disable-gpu",
    "--disable-dev-shm-usage",
    `--user-data-dir=${profile}`,
    "--remote-debugging-port=0",
    `file://${htmlPath}`,
  ],
  {
    stdio: "ignore",
    env: { ...process.env, HOME: work, TMPDIR: work },
  },
);

function stopChrome() {
  if (!chrome.killed) {
    chrome.kill("SIGTERM");
  }
}
process.on("exit", stopChrome);

function get(url) {
  return new Promise((resolve, reject) => {
    const request = http.get(url, (response) => {
      let body = "";
      response.on("data", (chunk) => {
        body += chunk;
      });
      response.on("end", () => resolve(body));
    });
    request.on("error", reject);
  });
}

async function debuggingPort() {
  const marker = path.join(profile, "DevToolsActivePort");
  for (let attempt = 0; attempt < 50; attempt += 1) {
    if (fs.existsSync(marker)) {
      const port = fs.readFileSync(marker, "utf8").split("\n")[0].trim();
      if (port) {
        return port;
      }
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error("Chrome did not open a debugging port");
}

const port = await debuggingPort();
let page = null;
for (let attempt = 0; attempt < 50; attempt += 1) {
  const list = JSON.parse(await get(`http://127.0.0.1:${port}/json/list`));
  page = list.find((item) => item.type === "page" && item.webSocketDebuggerUrl);
  if (page) {
    break;
  }
  await new Promise((resolve) => setTimeout(resolve, 100));
}
if (!page) {
  throw new Error("Chrome did not expose a page target");
}

const pageUrl = new URL(page.url);
if (pageUrl.pathname === "/") {
  throw new Error("file page path was treated as /");
}

const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((resolve, reject) => {
  ws.addEventListener("open", resolve);
  ws.addEventListener("error", () => reject(new Error("websocket failed")));
});

let nextId = 1;
function send(method, params) {
  const id = nextId;
  nextId += 1;
  return new Promise((resolve, reject) => {
    function onMessage(event) {
      const message = JSON.parse(event.data);
      if (message.id !== id) {
        return;
      }
      ws.removeEventListener("message", onMessage);
      if (message.error) {
        reject(new Error(JSON.stringify(message.error)));
        return;
      }
      resolve(message.result);
    }
    ws.addEventListener("message", onMessage);
    ws.send(JSON.stringify({ id, method, params }));
  });
}

await send("Accessibility.enable");
const tree = await send("Accessibility.getFullAXTree");
const button = (tree.nodes || []).find((node) => {
  const role = node.role && (node.role.value || node.role);
  return role === "button";
});
const name = button && button.name && (button.name.value || button.name);
if (name !== "Generate All Certificates") {
  throw new Error(`accessible name ${JSON.stringify(name)} is not the rendered aria-label`);
}
if (name === "Go") {
  throw new Error("matched the text content instead of the accessible name");
}
process.stdout.write("button=Generate All Certificates\n");
process.stdout.write(`path=${pageUrl.pathname}\n`);
ws.close();
stopChrome();
process.exit(0);
