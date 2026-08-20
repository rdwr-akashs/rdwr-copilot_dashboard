# web/ — Copilot Token Dashboard front-end

This directory is the source tree for the dashboard's HTML/CSS/JS. It is
bundled by esbuild into `web/dist/`, and `html_generation.py` inlines that
prebuilt output into the single self-contained HTML file the dashboard ships
as. **`html_generation.py` must stay a thin assembler** — it only reads
`web/index.html` + `web/dist/bundle.css` + `web/dist/bundle.js`, substitutes
`__APP_JSON__` / `__PRICING_JSON__`, and returns the string. All actual
markup/style/behavior changes belong in `web/`, not in Python string literals.

## Layout

```
web/
  index.html          # <head>/<body> skeleton with injection markers:
                       #   <!-- STYLES -->  -> replaced with bundle.css content
                       #   <!-- SCRIPT -->  -> replaced with bundle.js content
                       # __APP_JSON__ / __PRICING_JSON__ placeholders live
                       # inside the bundled JS (state.js) and are substituted
                       # by html_generation.py after inlining.
  styles/
    tokens.css         # :root CSS custom properties
    base.css           # resets, body, .app
    layout.css          # header, tabs nav, panel, filter-bar
    components.css     # session/event cards, badges, message list, genai button
    tabs.css            # analysis subtabs, pagination, tables, tool catalog controls
    charts.css           # chart-card/svg/legend
    modals.css          # modal backdrop/header/body/tabs
    responsive.css      # trailing @media rules (kept last: same cascade order
                         # as the original inline <style>)
  js/
    state.js            # APP_DATA/PRICING_TABLE/STATE, localStorage hidden-id
                         # sets, token-mode helpers
    format.js            # escapeHtml, formatInteger/Compact/Cost/Duration/...,
                          # token-block math, calcModelCost
    aggregate.js         # analysisForMode, activeSummary, monthly trend
                          # builders, chat-deletion target computation
    charts.js             # SVG chart builders (monthly trend, token pie)
    tables.js              # renderTable, sorting, pagination helpers
    tab-chats.js           # Chats tab + session/event rendering
    tab-analysis.js        # Analysis tab and its subtabs
    tab-cli.js              # CLI tab
    tab-reference.js       # Info/reference tab (prices, tool catalog, tips)
    modals.js               # GenAI/full-chat/file/model-compare/delete modals
    actions.js               # setX/switchX/export/delete click handlers
    app.js                   # entry point: renderHeader/renderSummaryCards/
                              # renderApp, plus the window-binding block below
  dist/
    bundle.css           # esbuild-concatenated CSS (committed)
    bundle.js             # esbuild IIFE bundle of js/app.js (committed)
  build.js                # esbuild build script (see package.json scripts)
```

## Build

From the repo root (Node.js + npm required only for *building*, never for
generating the dashboard):

```powershell
npm install       # once, installs esbuild as a devDependency
npm run build     # bundles web/js/app.js -> web/dist/bundle.js
                  # and concatenates web/styles/*.css -> web/dist/bundle.css
npm run watch     # rebuild on change while developing
```

**`web/dist/bundle.js` and `web/dist/bundle.css` are committed to source
control.** The repo `.gitignore` ignores `dist/` in general (Node/Maven build
output), but negates that specifically for `web/dist/` (see the end of
`.gitignore`). This is intentional: `html_generation.py` reads the prebuilt
files directly and must work for any contributor or CI job that has Python
but not Node — `python dashboard_core.py` never invokes esbuild or Node.
Always re-run `npm run build` and commit the result after changing anything
under `web/js/` or `web/styles/`.

## The `window`-binding constraint for inline `onclick` handlers

The rendered markup (both the static skeleton in `index.html` and the HTML
strings the JS builds at runtime) uses old-school inline handlers everywhere,
e.g. `onclick="switchTab('analysis')"`, `oninput="setSearch(this.value)"`.
Those attributes look up the function by name **on `window`** at click time.

`web/js/*.js` are real ES modules (`import`/`export`), and esbuild bundles
them into a single IIFE (`format: 'iife'` in `web/build.js`) precisely so that
none of those module-scoped bindings leak into the global scope by accident.
That means an inline `onclick="foo(...)"` would silently fail
(`ReferenceError: foo is not defined`) unless `foo` is explicitly exposed.

`web/js/app.js` (the bundle entry point) solves this deliberately: it
imports every function referenced from an `onclick`/`onchange`/`oninput`/
`onsubmit="..."` attribute anywhere in the markup, and does

```js
Object.assign(window, { switchTab, setSearch, /* ...48 total... */ });
```

right before the trailing `renderApp();` call, so every handler resolves
before the first render. **If you add a new inline handler referencing a new
function, add that function to this list in `app.js` too** — a missing entry
is a silent runtime failure (not a build error), so double-check by grepping
the built `bundle.js`/rendered HTML for `on(click|change|input|submit)="...`
and confirming every referenced name is either a native/DOM method
(`event.stopPropagation()`, `encodeURIComponent(...)`) or present in that
`Object.assign(window, {...})` block.

## Adding a new tab or section

1. Add the new render function(s) to the most relevant `web/js/*.js` file (or
   create a new `tab-*.js` file for a whole new tab), using named
   `export function ...` declarations.
2. Import what you need from other modules at the top of the file
   (`import { formatCost } from './format.js';` etc.) — there is no implicit
   global scope between modules.
3. If the new markup has any inline `onclick`/`onchange`/`oninput` handler,
   add the function to the curated list in `web/js/app.js`'s
   `Object.assign(window, {...})` block (see above).
4. Add any new CSS rules to the most relevant `web/styles/*.css` file.
5. Run `npm run build`, then `python dashboard_core.py -o out.html` to
   regenerate and manually sanity-check the tab in a browser.
6. Commit the updated `web/js/`, `web/styles/`, and the rebuilt `web/dist/`.

## Why the JS is split the way it is

This split was produced mechanically from the original single 3700+ line
inline `<script>` in `html_generation.py`: every top-level function was
grouped by concern into the files above, in original source order, with
zero logic changes — purely a restructuring pass. Do not "improve" the logic
while touching these files unless that is the explicit goal of your change;
keep restructuring and behavior changes in separate commits.
