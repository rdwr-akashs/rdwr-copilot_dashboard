"""Guard rails for the `web/` thin-assembler contract (see `web/README.md`).

`html_generation.generate_html()` is now a thin assembler: it reads the
prebuilt `web/index.html` skeleton plus `web/dist/bundle.css` /
`web/dist/bundle.js`, inlines them, and substitutes `__APP_JSON__` /
`__PRICING_JSON__`. Three UI agents are actively adding markup/behavior under
`web/js/**` and `web/styles/**`, and `web/README.md` calls out one silent
failure mode explicitly: an inline `onclick="newHandler(...)"` added to the
markup without also adding `newHandler` to the `Object.assign(window, {...})`
exposure block in `web/js/app.js` compiles fine, builds fine, and then throws
`ReferenceError: newHandler is not defined` at click time in the browser --
no build error, no other test failure. `test_window_binding_invariant_*`
below is written to catch exactly that class of bug and is the single
highest-value test in this module. (There is more than one
`Object.assign(window, {...})` block in the current bundle -- one per
tab-scoped module plus app.js's main one -- so the extraction collects
every occurrence rather than assuming a single top-level block.)
"""
from __future__ import annotations

import re
import shutil
import subprocess

import pytest

from html_generation import _BUNDLE_CSS_PATH, _BUNDLE_JS_PATH, _INDEX_HTML_PATH, generate_html

# Inline handler attribute values may legitimately call more than one thing,
# separated by `;` (e.g. `onclick="event.stopPropagation();openFoo(...)"`).
# These are native/DOM/global constructs, not app-defined functions, so they
# are never expected to appear in the `Object.assign(window, {...})` block.
_NATIVE_OR_DOM_CALLS = {
    "encodeURIComponent",
    "decodeURIComponent",
    "stopPropagation",
    "preventDefault",
    "alert",
    "confirm",
}


def _strip_script_and_style(html: str) -> str:
    html = re.sub(r"<script\b[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<style\b[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
    return html


def _strip_template_interpolations(text: str) -> str:
    """Remove every `${...}` template-literal interpolation from `text`.

    The JS template-literal source that builds markup at runtime often
    interpolates *data* (already-escaped values, formatted numbers, etc.)
    into the middle of an `onclick="..."` attribute string, e.g.
    `onclick="doThing('${escapeHtml(String(x))}')"`. Those `${...}`
    expressions are evaluated by JS *before* the attribute string is ever
    assigned -- `escapeHtml`/`String` never appear as literal attribute text
    at runtime and are not event-handler invocations, so they must be
    stripped out before scanning for handler-call names, else they show up
    as false-positive "missing window binding" reports. Depth-aware (not a
    naive regex) so nested braces inside an interpolation don't truncate it.
    """
    result = []
    i, n = 0, len(text)
    while i < n:
        if text[i] == "$" and i + 1 < n and text[i + 1] == "{":
            depth = 1
            j = i + 2
            while j < n and depth > 0:
                if text[j] == "{":
                    depth += 1
                elif text[j] == "}":
                    depth -= 1
                j += 1
            i = j
            continue
        result.append(text[i])
        i += 1
    return "".join(result)


def _extract_handler_calls(html: str) -> set[str]:
    """Every distinct function-call-like identifier used inside an inline
    on(click|change|input|submit)="..." attribute anywhere in `html`.

    This intentionally scans the *whole* generated document, not just the
    static `web/index.html` skeleton: the bundled JS itself builds large
    chunks of markup via string templates containing the same
    `onclick="..."` attributes, and those string literals appear verbatim in
    the inlined `<script>` text once `generate_html()` has run.
    """
    calls: set[str] = set()
    for attr_value in re.findall(r'on(?:click|change|input|submit)="([^"]*)"', html):
        cleaned = _strip_template_interpolations(attr_value)
        calls.update(re.findall(r"([A-Za-z_$][\w$]*)\s*\(", cleaned))
    return calls


def _extract_window_exposed_names(js_text: str) -> set[str]:
    # There may be more than one `Object.assign(window, {...})` block (e.g.
    # one per tab module, plus app.js's main one), so collect every one
    # rather than assuming a single top-level occurrence.
    blocks = re.findall(r"Object\.assign\(window,\s*\{(.*?)\}\s*\)", js_text, re.DOTALL)
    assert blocks, (
        "Could not find any `Object.assign(window, {...})` exposure block in "
        "web/dist/bundle.js. See web/README.md's 'window-binding constraint "
        "for inline onclick handlers' -- app.js must expose every "
        "inline-handler function on `window` this way."
    )
    exposed: set[str] = set()
    for block in blocks:
        exposed.update(re.findall(r"([A-Za-z_$][\w$]*)", block))
    return exposed


def test_web_artifacts_exist_and_are_nonempty():
    for path in (_INDEX_HTML_PATH, _BUNDLE_CSS_PATH, _BUNDLE_JS_PATH):
        assert path.is_file(), f"missing required web/ build artifact: {path}"
        assert path.stat().st_size > 0, f"web/ build artifact is empty: {path}"


def test_generate_html_inlines_both_bundles_with_no_leftover_markers(minimal_app_data):
    html = generate_html(minimal_app_data)

    assert "<!-- STYLES -->" not in html, "STYLES injection marker was not replaced"
    assert "<!-- SCRIPT -->" not in html, "SCRIPT injection marker was not replaced"

    raw_css = _BUNDLE_CSS_PATH.read_text(encoding="utf-8")
    assert raw_css in html, "web/dist/bundle.css content was not inlined verbatim"

    # The JS bundle is inlined verbatim except where __APP_JSON__ /
    # __PRICING_JSON__ placeholders get substituted with real data, so check
    # that every chunk *between* those placeholders survives untouched.
    raw_js = _BUNDLE_JS_PATH.read_text(encoding="utf-8")
    for chunk in re.split(r"__APP_JSON__|__PRICING_JSON__", raw_js):
        if chunk.strip():
            assert chunk in html, "a piece of web/dist/bundle.js was not inlined verbatim"


def test_no_placeholder_or_error_literals_leak_into_static_markup(minimal_app_data):
    # We cannot execute the JS bundle in this test (no Node dependency
    # allowed for the Python test path), so this only checks the *static*
    # skeleton markup -- i.e. everything outside <script>/<style> -- for
    # leaked "undefined"/"NaN"/"[object Object]" literals. The JS bundle
    # text itself legitimately contains the word "undefined" (e.g.
    # `typeof x === "undefined"`), so it is excluded here by design.
    html = generate_html(minimal_app_data)
    static_markup = _strip_script_and_style(html)
    assert "undefined" not in static_markup
    assert "NaN" not in static_markup
    assert "[object Object]" not in static_markup


def test_window_binding_invariant_all_inline_handlers_are_exposed(minimal_app_data):
    """The single highest-value test in this module.

    Every `onclick`/`onchange`/`oninput`/`onsubmit="fn(...)"` referenced
    anywhere in the generated document must resolve to either a native/DOM
    construct or a name exposed via `Object.assign(window, {...})` in
    `web/js/app.js`'s bundled output -- otherwise it is a dead button at
    runtime with no build-time signal (see web/README.md).
    """
    html = generate_html(minimal_app_data)
    used = _extract_handler_calls(html)
    exposed = _extract_window_exposed_names(_BUNDLE_JS_PATH.read_text(encoding="utf-8"))

    missing = sorted(used - exposed - _NATIVE_OR_DOM_CALLS)
    assert not missing, (
        "The following inline event-handler function name(s) are referenced "
        "in an onclick/onchange/oninput/onsubmit attribute somewhere in the "
        "rendered dashboard but are NOT exposed on `window` via the "
        "`Object.assign(window, {...})` block in web/js/app.js, and are not "
        f"recognized native/DOM calls: {missing}. "
        "Fix: add the missing function(s) to that exposure list in "
        "web/js/app.js, then `npm run build` and commit web/dist/. "
        "See web/README.md's 'window-binding constraint for inline onclick "
        "handlers'."
    )


def test_bundle_js_is_syntactically_valid_javascript():
    # The Python dashboard-generation path must never require Node -- this
    # check is purely an extra guard when Node happens to be available, and
    # is skipped gracefully otherwise. subprocess.run(['node', ...]) is used
    # rather than invoking `node` through PowerShell, which can spuriously
    # report "Permission denied" in this environment.
    node_path = shutil.which("node")
    if not node_path:
        pytest.skip("Node.js is not available in this environment; skipping bundle.js syntax check.")

    result = subprocess.run(
        [node_path, "--check", str(_BUNDLE_JS_PATH)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"node --check failed for web/dist/bundle.js:\n{result.stderr}"
