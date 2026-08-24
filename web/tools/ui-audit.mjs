// Renders the generated dashboard in jsdom, walks every tab/subtab, and audits
// the resulting DOM for the classes of breakage that a static grep cannot see:
//   1. align-mismatch  -- a column whose <th> and <td> resolve to different
//                         text-align, so the label floats away from its values
//   2. column-count    -- thead/tbody cell counts disagree
//   3. undefined-var   -- var(--x) referenced with no --x defined anywhere
//   4. dead-class      -- a class on a rendered element with no CSS rule at all
//   5. dead-handler    -- an inline onclick/onchange target missing from window
//   6. render-throw    -- a tab/subtab that throws while rendering
//
// Usage:  node web/tools/ui-audit.mjs path/to/dashboard.html   (npm run audit:ui)
// Exits non-zero when anything is found, so it works as a pre-commit gate.
//
// What it cannot see: jsdom has no layout engine, so nothing here catches
// overflow, wrapping, or actual pixel positions - only cascade-resolved styles
// and DOM structure. Those still need a real browser.
import fs from 'fs';
import { JSDOM } from 'jsdom';

// Classes that carry their styling inline and use the class purely as a
// semantic/query hook. Having no CSS rule is correct for these, so they are
// not dead - listing them keeps the dead-class report free of known noise.
const INLINE_STYLED_HOOKS = new Set(['collapse-icon', 'summary-group', 'table-export-bar']);

const htmlPath = process.argv[2];
const html = fs.readFileSync(htmlPath, 'utf8');

const dom = new JSDOM(html, {
  runScripts: 'dangerously',
  pretendToBeVisual: true,
  url: 'http://localhost/dashboard.html',
});
const { window } = dom;
const { document } = window;

await new Promise((resolve) => {
  if (document.readyState === 'complete') resolve();
  else window.addEventListener('load', resolve);
});

const jsErrors = [];
window.addEventListener('error', (e) => jsErrors.push(String(e.message || e.error)));

const findings = [];
const stats = { views: 0, tables: 0, columns: 0, elements: 0 };
const seenClasses = new Set();
const seenHandlers = new Map();

function align(el) {
  const v = window.getComputedStyle(el).textAlign;
  return v && v !== '' ? v : 'start';
}

// ---- CSS inventory (from the inlined <style>, i.e. exactly what ships) ----
const cssText = [...document.querySelectorAll('style')].map((s) => s.textContent).join('\n');
const definedClasses = new Set([...cssText.matchAll(/\.(-?[_a-zA-Z][\w-]*)/g)].map((m) => m[1]));
const definedVars = new Set([...cssText.matchAll(/(--[\w-]+)\s*:/g)].map((m) => m[1]));
const usedVars = new Set([...cssText.matchAll(/var\(\s*(--[\w-]+)/g)].map((m) => m[1]));
// Inline style="...var(--x)..." in the JS-generated markup counts too.
const bundleText = [...document.querySelectorAll('script')].map((s) => s.textContent).join('\n');
for (const m of bundleText.matchAll(/var\(\s*(--[\w-]+)/g)) usedVars.add(m[1]);

for (const name of usedVars) {
  if (!definedVars.has(name)) {
    findings.push({ type: 'undefined-var', view: 'stylesheet', detail: `var(${name}) is referenced but never defined` });
  }
}

function auditCurrentView(label) {
  stats.views += 1;

  document.querySelectorAll('[class]').forEach((el) => {
    stats.elements += 1;
    for (const cls of el.classList) seenClasses.add(cls);
  });

  for (const attr of ['onclick', 'onchange', 'oninput']) {
    document.querySelectorAll(`[${attr}]`).forEach((el) => {
      const code = el.getAttribute(attr) || '';
      // Only bare `fn(` calls resolve against window. A `.method(` call is on
      // some other object (`event.stopPropagation()`, `this.value`), so the
      // preceding-dot guard keeps those out of the dead-handler report.
      for (const m of code.matchAll(/(^|[^.\w$])([A-Za-z_$][\w$]*)\s*\(/g)) {
        const name = m[2];
        if (['if', 'return', 'function', 'typeof', 'Number', 'String', 'Boolean'].includes(name)) continue;
        if (!seenHandlers.has(name)) seenHandlers.set(name, label);
      }
    });
  }

  [...document.querySelectorAll('table')].forEach((table, ti) => {
    stats.tables += 1;
    const headRow = table.querySelector('thead tr:last-of-type');
    if (!headRow) return;
    const ths = [...headRow.children];
    const bodyRows = [...table.querySelectorAll('tbody tr')];
    const dataRow = bodyRows.find((tr) => tr.children.length === ths.length);
    if (!dataRow) {
      if (bodyRows.length && !bodyRows.some((tr) => [...tr.children].some((c) => c.hasAttribute('colspan')))) {
        findings.push({
          type: 'column-count',
          view: label,
          table: ti,
          detail: `thead has ${ths.length} cells, first tbody row has ${bodyRows[0].children.length}`,
        });
      }
      return;
    }
    const tds = [...dataRow.children];
    ths.forEach((th, ci) => {
      stats.columns += 1;
      const td = tds[ci];
      if (!td) return;
      const a = align(th);
      const b = align(td);
      if (a !== b) {
        findings.push({
          type: 'align-mismatch',
          view: label,
          table: ti,
          column: ci,
          header: (th.textContent || '').trim().slice(0, 40),
          thAlign: a,
          tdAlign: b,
          thClass: th.className || '(none)',
          tdClass: td.className || '(none)',
          tableClass: table.className || '(none)',
        });
      }
    });
  });
}

function call(name, ...args) {
  if (typeof window[name] !== 'function') {
    findings.push({ type: 'dead-handler', view: name, detail: `window.${name} is not a function` });
    return false;
  }
  try {
    window[name](...args);
    return true;
  } catch (err) {
    findings.push({ type: 'render-throw', view: `${name}(${args.join(',')})`, detail: String((err && err.message) || err) });
    return false;
  }
}

const VIEWS = [
  ['overview', []],
  ['chats', []],
  ['analysis', [
    ['switchAnalysisTab', 'models'],
    ['switchAnalysisTab', 'tools'],
    ['switchAnalysisTab', 'files'],
    ['switchAnalysisTab', 'monthlyTrends'],
    ['switchAnalysisTab', 'insights'],
  ]],
  ['cli', []],
  ['reference', [
    ['switchDataTab', 'prices'],
    ['switchDataTab', 'toolCatalog'],
    ['switchDataTab', 'tips'],
    ['switchDataTab', 'telemetry'],
  ]],
];

for (const [tab, subs] of VIEWS) {
  if (!call('switchTab', tab)) continue;
  if (!subs.length) {
    auditCurrentView(tab);
    continue;
  }
  for (const [fn, arg] of subs) {
    if (!call(fn, arg)) continue;
    auditCurrentView(`${tab}/${arg}`);
    if (tab === 'analysis' && arg === 'tools') {
      for (const sub of ['usage', 'waste']) {
        if (call('switchToolImpactTab', sub)) auditCurrentView(`${tab}/tools/${sub}`);
      }
    }
  }
}

if (typeof window.switchTokenMode === 'function') {
  for (const mode of ['attributed', 'billed']) {
    try {
      window.switchTokenMode(mode);
      call('switchTab', 'chats');
      auditCurrentView(`chats[tokenMode=${mode}]`);
      call('switchTab', 'analysis');
      auditCurrentView(`analysis[tokenMode=${mode}]`);
    } catch { /* mode may be rejected; not a styling concern */ }
  }
}

for (const cls of [...seenClasses].sort()) {
  if (!definedClasses.has(cls) && !INLINE_STYLED_HOOKS.has(cls)) {
    findings.push({ type: 'dead-class', view: 'rendered DOM', detail: `.${cls} is on a rendered element but has no CSS rule` });
  }
}
for (const [name, view] of seenHandlers) {
  if (typeof window[name] !== 'function') {
    findings.push({ type: 'dead-handler', view, detail: `inline handler ${name}() is not bound on window` });
  }
}

const grouped = new Map();
for (const f of findings) {
  const key = f.type === 'align-mismatch'
    ? `${f.type}|${f.tableClass}|${f.thClass}|${f.tdClass}|${f.thAlign}->${f.tdAlign}`
    : `${f.type}|${f.detail || ''}`;
  if (!grouped.has(key)) grouped.set(key, { ...f, count: 0, views: new Set(), headers: new Set() });
  const g = grouped.get(key);
  g.count += 1;
  g.views.add(f.view);
  if (f.header) g.headers.add(f.header);
}

console.log(`views=${stats.views} tables=${stats.tables} columns=${stats.columns} elements=${stats.elements}`);
console.log(`css: ${definedClasses.size} classes / ${definedVars.size} vars defined; ${seenClasses.size} classes seen in DOM; ${seenHandlers.size} inline handlers`);
console.log(`js errors during render: ${jsErrors.length}`);
jsErrors.slice(0, 10).forEach((e) => console.log('  ERR', e));
console.log(`\n${grouped.size} distinct finding group(s), ${findings.length} instance(s):\n`);
for (const g of [...grouped.values()].sort((a, b) => b.count - a.count)) {
  if (g.type === 'align-mismatch') {
    console.log(`[${g.type}] x${g.count}  table.${g.tableClass}`);
    console.log(`   th.${g.thClass} => ${g.thAlign}   |   td.${g.tdClass} => ${g.tdAlign}`);
    console.log(`   headers: ${[...g.headers].slice(0, 8).join(', ')}`);
    console.log(`   views:   ${[...g.views].slice(0, 8).join(', ')}`);
  } else {
    console.log(`[${g.type}] x${g.count}  ${g.detail || ''}   (${[...g.views].slice(0, 4).join(', ')})`);
  }
}
if (!findings.length && !jsErrors.length) console.log('clean - no findings');

window.close();
process.exit(findings.length || jsErrors.length ? 1 : 0);
