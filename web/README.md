# QueryLens web playground

A static site that runs the real `slowlens` package in the browser, so people can try it without installing anything.

## Architecture

- **Engine.** [Pyodide](https://pyodide.org) (CPython on WebAssembly) runs inside a Web Worker. `build.py` zips `src/slowlens` unchanged, the worker unpacks it, and `bridge.py` calls `slowlens.cli.main` three times (`--output json`, `text`, `markdown`) with the options the user picked. The playground shows the CLI's own output; nothing is re-implemented in JavaScript, and the CLI package is not modified.
- **Interface.** Plain HTML, CSS and JavaScript with no framework and no npm dependencies in the shipped site. The pattern list, search, sorting and hint filter are rendered from the JSON report. All text is inserted with `textContent`, never `innerHTML`.
- **Privacy.** The log stays in the browser. The only network requests are for the site's own files and for Pyodide from the jsDelivr CDN (pinned to `0.27.7`). A Content-Security-Policy in `netlify.toml` limits scripts to the site and that CDN.
- **Safeguards.** 5 MB input limit, gzip rejected (avoids decompression bombs), at most 500 patterns requested, a 60 second timeout that terminates the worker, and uploaded text is only ever parsed as a log, never executed.

## Not available in the browser

`.gz` input, stdin and multiple files (the CLI supports them), and logs over 5 MB. The first visit downloads about 10 MB of Pyodide.

## Local development

```bash
python3 web/build.py                 # builds web/dist, Pyodide from the CDN
python3 -m http.server -d web/dist   # open http://localhost:8000
```

Tests:

```bash
make check                           # includes tests/unit/test_web_demo.py (bridge and build)
cd web && npm install && npx playwright install chromium
npm run test:e2e                     # bundles Pyodide locally, drives the page in Chromium
```

The end-to-end test compares the page's results with `tests/golden/*.json`, checks error states (invalid, empty, oversized, gzip), escaping, the CI gate options, keyboard tab navigation, mobile width and console errors.

## Deploying on Netlify

1. In Netlify choose **Add new site → Import an existing project**, pick GitHub and select `yagnang-vyas/query-lens`.
2. Set the production branch (for example `main`). Netlify reads `netlify.toml`, so the settings are already filled in: **build command** `python3 web/build.py`, **publish directory** `web/dist`. No environment variables or secrets are needed.
3. Deploy. Every push to the production branch redeploys, and pull requests get deploy previews.
4. Put the site URL in the README's "Live demo" section and the release notes.
