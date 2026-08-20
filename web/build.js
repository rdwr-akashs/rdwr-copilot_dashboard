// Build script for the Copilot Token Dashboard front-end.
//
// Bundles web/js/app.js (the entry point, which transitively imports every
// other web/js/*.js module) into a single IIFE at web/dist/bundle.js, and
// concatenates web/styles/*.css into web/dist/bundle.css. Both outputs are
// committed to source control (see the ".gitignore" negation for web/dist/)
// so that `python dashboard_core.py` never requires Node/npm to run --
// html_generation.py just reads these prebuilt files and inlines them.
//
// Usage:
//   node web/build.js            (single build)
//   node web/build.js --watch    (rebuild on change)

const esbuild = require('esbuild');
const fs = require('fs');
const path = require('path');

const ROOT = __dirname;
const DIST = path.join(ROOT, 'dist');
const STYLES_DIR = path.join(ROOT, 'styles');

const CSS_ORDER = [
  'tokens.css',
  'base.css',
  'layout.css',
  'components.css',
  'tabs.css',
  'charts.css',
  'modals.css',
  'responsive.css',
];

function buildCss() {
  const combined = CSS_ORDER.map((name) =>
    fs.readFileSync(path.join(STYLES_DIR, name), 'utf8')
  ).join('');
  fs.mkdirSync(DIST, { recursive: true });
  fs.writeFileSync(path.join(DIST, 'bundle.css'), combined, 'utf8');
  console.log(`[build] wrote dist/bundle.css (${combined.length} bytes)`);
}

const jsBuildOptions = {
  entryPoints: [path.join(ROOT, 'js', 'app.js')],
  bundle: true,
  format: 'iife',
  // No global name: app.js explicitly attaches the curated set of
  // onclick/onchange/oninput-referenced functions to `window` itself, so
  // the IIFE wrapper only exists to keep every other binding out of the
  // global scope (matching normal module hygiene).
  outfile: path.join(DIST, 'bundle.js'),
  minify: false,
  legalComments: 'none',
  target: ['es2019'],
  logLevel: 'info',
};

async function main() {
  const watch = process.argv.includes('--watch');
  buildCss();
  if (watch) {
    const ctx = await esbuild.context(jsBuildOptions);
    await ctx.watch();
    console.log('[build] watching web/js and web/styles for changes...');
    fs.watch(STYLES_DIR, { recursive: false }, () => {
      try {
        buildCss();
      } catch (err) {
        console.error('[build] css rebuild failed:', err);
      }
    });
  } else {
    await esbuild.build(jsBuildOptions);
    console.log('[build] wrote dist/bundle.js');
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
