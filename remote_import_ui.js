(function () {
  const BUTTON_ID = "remoteImportBtn";
  const BACKDROP_ID = "remoteImportBackdrop";
  const FORM_ID = "remoteImportForm";
  const STATUS_ID = "remoteImportStatus";
  const LIST_ID = "remoteSourceList";

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function formatTimestamp(value) {
    if (!value) return "—";
    const date = new Date(value);
    if (!Number.isFinite(date.getTime())) return String(value);
    return date.toLocaleString();
  }

  async function callApi(path, options) {
    const response = await fetch(path, options);
    let payload = {};
    try {
      payload = await response.json();
    } catch (_err) {
      payload = {};
    }

    if (!response.ok || payload.ok === false) {
      throw new Error(payload.error || `Request failed (${response.status})`);
    }
    return payload;
  }

  function setStatus(text, kind) {
    const statusEl = document.getElementById(STATUS_ID);
    if (!statusEl) return;
    statusEl.textContent = text || "";
    statusEl.style.color =
      kind === "error"
        ? "var(--red)"
        : kind === "success"
          ? "var(--green)"
          : "var(--muted)";
  }

  function closeModal(event) {
    const backdrop = document.getElementById(BACKDROP_ID);
    if (!backdrop) return;
    if (event && event.target && event.target !== backdrop) return;
    backdrop.classList.remove("open");
    setStatus("", "info");
  }

  async function refreshSourceList() {
    const listEl = document.getElementById(LIST_ID);
    if (!listEl) return;
    listEl.innerHTML = '<div class="note">Loading remote sources…</div>';

    try {
      const payload = await callApi("/api/remote-sources", { method: "GET" });
      const sources = payload.sources || [];
      if (!sources.length) {
        listEl.innerHTML = '<div class="note">No remote sources imported yet.</div>';
        return;
      }

      listEl.innerHTML = sources
        .map((source) => {
          const statusColor =
            source.status === "ok"
              ? "var(--green)"
              : source.status === "error"
                ? "var(--red)"
                : "var(--muted)";
          const summary = `${source.username}@${source.host}:${source.path}`;
          const md5 = source.remoteMd5 || "—";
          const checked = formatTimestamp(source.lastCheckedAt);
          const downloaded = formatTimestamp(source.lastDownloadAt);
          const error = source.lastError
            ? `<div class="note small" style="color:var(--red)">${escapeHtml(source.lastError)}</div>`
            : "";
          return `
            <div class="event-section" style="margin-top:8px">
              <div style="display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap">
                <strong>${escapeHtml(summary)}</strong>
                <span class="badge" style="border-color:${statusColor};color:${statusColor}">${escapeHtml(source.status || "unknown")}</span>
              </div>
              <div class="note small" style="margin-top:6px">MD5: <code>${escapeHtml(md5)}</code></div>
              <div class="note small">Checked: ${escapeHtml(checked)} · Downloaded: ${escapeHtml(downloaded)}</div>
              <div class="note small">Cached files: ${escapeHtml(source.lastFileCount || 0)} · Downloads: ${escapeHtml(source.downloadCount || 0)}</div>
              ${error}
            </div>`;
        })
        .join("");
    } catch (err) {
      listEl.innerHTML = `<div class="note" style="color:var(--red)">${escapeHtml(err.message || err)}</div>`;
    }
  }

  async function submitImport(event) {
    event.preventDefault();
    const form = document.getElementById(FORM_ID);
    if (!form) return;

    const host = String(form.ip.value || "").trim();
    const username = String(form.username.value || "").trim();
    const password = String(form.password.value || "");
    const path = String(form.path.value || "").trim();
    const portRaw = String(form.port.value || "").trim();

    if (!host || !username || !path) {
      setStatus("IP, username and path are required.", "error");
      return;
    }

    const submitBtn = form.querySelector('button[type="submit"]');
    if (submitBtn) submitBtn.disabled = true;
    setStatus("Connecting, validating path, computing remote MD5, downloading if changed…", "info");

    try {
      const payload = {
        ip: host,
        username,
        password,
        path,
      };
      if (portRaw) payload.port = Number(portRaw);

      const result = await callApi("/api/remote-import", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      const sync = result.sync || {};
      setStatus(
        `Connected. MD5=${sync.remoteMd5 || "n/a"}. Changed=${String(!!sync.changed)}. Downloaded=${String(!!sync.downloaded)}.`,
        "success"
      );
      await refreshSourceList();
      setTimeout(() => window.location.reload(), 800);
    } catch (err) {
      setStatus(err.message || String(err), "error");
    } finally {
      if (submitBtn) submitBtn.disabled = false;
    }
  }

  async function syncNow() {
    setStatus("Running remote MD5 checks…", "info");
    try {
      const payload = await callApi("/api/remote-sync-now", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
      const results = payload.results || [];
      const changed = results.filter((item) => item.ok && item.result && item.result.changed).length;
      setStatus(`Sync done. Sources changed: ${changed}.`, "success");
      await refreshSourceList();
      setTimeout(() => window.location.reload(), 800);
    } catch (err) {
      setStatus(err.message || String(err), "error");
    }
  }

  function ensureModal() {
    if (document.getElementById(BACKDROP_ID)) return;

    const backdrop = document.createElement("div");
    backdrop.id = BACKDROP_ID;
    backdrop.className = "modal-backdrop";
    backdrop.innerHTML = `
      <div class="modal" onclick="event.stopPropagation()" style="max-width:760px">
        <div class="modal-header">
          <div>
            <h3>Import remote logs</h3>
            <div class="subtitle">Enter server details. The server verifies access + path, computes remote MD5, and downloads only on change.</div>
          </div>
          <div class="modal-actions" style="display:flex;gap:8px">
            <button type="button" id="remoteSyncNowBtn">Sync now</button>
            <button type="button" id="remoteImportCloseBtn">Close</button>
          </div>
        </div>
        <div class="modal-body">
          <form id="${FORM_ID}" class="event-section" style="display:grid;gap:10px">
            <div class="split-grid">
              <label>IP / host<br><input name="ip" required placeholder="10.10.10.10" style="width:100%"></label>
              <label>Username<br><input name="username" required placeholder="itayb" style="width:100%"></label>
            </div>
            <div class="split-grid">
              <label>Password<br><input name="password" type="password" placeholder="••••••••" style="width:100%"></label>
              <label>Port (optional)<br><input name="port" type="number" min="1" max="65535" placeholder="22" style="width:100%"></label>
            </div>
            <label>Remote debug-logs path<br><input name="path" required placeholder="/home/user/.vscode-server/data/User/workspaceStorage/.../debug-logs" style="width:100%"></label>
            <div style="display:flex;justify-content:flex-end">
              <button type="submit" style="border:1px solid rgba(88,166,255,0.45);background:rgba(88,166,255,0.12);color:var(--blue);font-weight:700">Import + verify</button>
            </div>
          </form>

          <div id="${STATUS_ID}" class="note"></div>

          <div>
            <h4 style="margin:6px 0">Imported remote sources</h4>
            <div id="${LIST_ID}"></div>
          </div>
        </div>
      </div>`;
    document.body.appendChild(backdrop);

    backdrop.addEventListener("click", closeModal);

    const form = document.getElementById(FORM_ID);
    if (form) form.addEventListener("submit", submitImport);

    const closeBtn = document.getElementById("remoteImportCloseBtn");
    if (closeBtn) closeBtn.addEventListener("click", () => closeModal());

    const syncNowBtn = document.getElementById("remoteSyncNowBtn");
    if (syncNowBtn) syncNowBtn.addEventListener("click", syncNow);
  }

  function openModal() {
    ensureModal();
    const backdrop = document.getElementById(BACKDROP_ID);
    if (!backdrop) return;
    backdrop.classList.add("open");
    refreshSourceList();
  }

  function ensureButton() {
    const headerControls = document.querySelector(".header-top > div:last-child");
    if (!headerControls || document.getElementById(BUTTON_ID)) return;

    const button = document.createElement("button");
    button.id = BUTTON_ID;
    button.type = "button";
    button.textContent = "🌐 Import remote logs";
    button.style.border = "1px solid rgba(88,166,255,0.45)";
    button.style.background = "rgba(88,166,255,0.12)";
    button.style.color = "var(--blue)";
    button.style.padding = "8px 14px";
    button.style.borderRadius = "999px";
    button.style.cursor = "pointer";
    button.style.fontWeight = "700";
    button.style.fontSize = "0.85rem";
    button.addEventListener("click", openModal);

    headerControls.appendChild(button);
  }

  function boot() {
    ensureModal();
    ensureButton();

    setInterval(() => {
      ensureButton();
    }, 1200);

    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        closeModal();
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
