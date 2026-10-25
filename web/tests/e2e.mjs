// End-to-end check of the built demo in headless Chromium.
//   QUERYLENS_PYODIDE_DIR=node_modules/pyodide python3 web/build.py
//   node web/tests/e2e.mjs            (needs `playwright`; Pyodide is served from dist/pyodide)
// The static server sends the Content-Security-Policy from netlify.toml, so CSP violations fail.
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_PATH || "playwright");
const root = path.resolve(import.meta.dirname, "..");
const dist = path.join(root, "dist");
const toml = fs.readFileSync(path.join(root, "..", "netlify.toml"), "utf8");
const csp = toml.match(/Content-Security-Policy = "([^"]+)"/)[1];
const types = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".wasm": "application/wasm", ".zip": "application/zip", ".py": "text/plain", ".log": "text/plain" };

const server = http.createServer((req, res) => {
  const file = path.join(dist, decodeURIComponent(req.url.split("?")[0]).replace(/\/$/, "/index.html"));
  if (!file.startsWith(dist) || !fs.existsSync(file)) { res.writeHead(404).end(); return; }
  res.writeHead(200, { "content-type": types[path.extname(file)] || "application/octet-stream", "content-security-policy": csp });
  fs.createReadStream(file).pipe(res);
}).listen(0);
const base = `http://localhost:${server.address().port}/`;

const browser = await chromium.launch();
const page = await browser.newPage();
const problems = [];
page.on("console", (m) => { if (m.type() === "error") problems.push(m.text()); });
page.on("pageerror", (e) => problems.push(String(e)));
const analyzeWith = async (text) => { await page.fill("#log", text); await page.click("#run"); };
const ready = () => page.waitForFunction(() => !document.querySelector("#run").disabled, null, { timeout: 120000 });

try {
  await page.goto(base);
  await ready();

  // 1. Samples agree with the CLI's golden JSON.
  for (const [button, golden] of [["postgres-sample.log", "postgres-sample.json"], ["mysql-slow-sample.log", "mysql-slow-sample.json"]]) {
    await page.click(`[data-sample="${button}"]`);
    await page.waitForSelector("#results:not([hidden])");
    const expected = JSON.parse(fs.readFileSync(path.join(root, "..", "tests", "golden", golden), "utf8"));
    const got = JSON.parse(await page.textContent("#panel-json pre"));
    const key = (f) => [f.id, f.count, f.total_ms];
    const n = Math.min(got.fingerprints.length, expected.fingerprints.length);
    assert.deepEqual(got.fingerprints.slice(0, n).map(key), expected.fingerprints.slice(0, n).map(key));
    assert.equal(await page.locator(".pattern").count(), got.fingerprints.length);
  }

  // 2. Search, hint filter, detail view.
  await page.fill("#q", "zzz-no-such-query");
  await page.waitForSelector("#empty:not([hidden])");
  await page.fill("#q", "");
  await page.selectOption("#hint-filter", "*");
  assert.ok((await page.locator(".pattern").count()) > 0);
  await page.locator(".pattern summary").first().click();
  assert.ok(await page.locator(".pattern[open] .sql").first().isVisible());

  // 3. Hostile content is rendered as text, never as markup.
  await analyzeWith("2026-10-25 06:30:00.000 UTC [1] app@db LOG:  duration: 5.000 ms  statement: SELECT \"<img src=x onerror=alert(1)>\" FROM t WHERE id = 1");
  await page.waitForSelector("#results:not([hidden])");
  assert.equal(await page.locator("#list img").count(), 0);

  // 4. Invalid, empty, oversized and compressed inputs give clear errors.
  await analyzeWith("this is not a database log\nat all");
  await page.waitForSelector("#error:not([hidden])");
  assert.match(await page.textContent("#error"), /log entries|detect|format/i);
  await page.fill("#log", "   ");
  await page.click("#run");
  assert.match(await page.textContent("#error"), /Nothing to analyze/);
  await page.setInputFiles("#file", { name: "big.log", mimeType: "text/plain", buffer: Buffer.alloc(5 * 1024 * 1024 + 1, "a") });
  await page.waitForFunction(() => /5 MB/.test(document.querySelector("#error").textContent));
  await page.setInputFiles("#file", { name: "x.log.gz", mimeType: "application/gzip", buffer: Buffer.from([0x1f, 0x8b, 8, 0, 0, 0, 0, 0]) });
  await page.waitForFunction(() => /gzip/.test(document.querySelector("#error").textContent));

  // 5. CI gate options are passed through to the CLI.
  await page.click('[data-sample="postgres-sample.log"]');
  await page.waitForSelector("#results:not([hidden])");
  await page.click("details.options summary");
  await page.fill("#opt-over", "1");
  await page.click("#run");
  await page.waitForSelector("#gate:not([hidden])");
  assert.match(await page.textContent("#gate"), /exit with code 1/);

  // 6. Keyboard: tabs move with arrow keys.
  await page.focus("#tab-patterns");
  await page.keyboard.press("ArrowRight");
  assert.equal(await page.getAttribute("#tab-text", "aria-selected"), "true");

  // 7. Mobile layout has no horizontal scroll.
  await page.setViewportSize({ width: 375, height: 800 });
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));

  assert.deepEqual(problems, [], "console errors: " + problems.join("\n"));
  console.log("e2e: all checks passed");
} finally {
  await browser.close();
  server.close();
}
