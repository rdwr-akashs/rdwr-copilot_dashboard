from __future__ import annotations

import argparse
import collections
import concurrent.futures
import glob
import hashlib
import json
import math
import os
import re
import socket
import struct
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import fcntl  # type: ignore
except Exception:  # pragma: no cover - non-Linux platforms
    fcntl = None

from dashboard_utils import *
from compact_files import compact_app_data_for_html
from model_pricing import PRICING

def generate_html(app_data: dict[str, Any]) -> str:
    app_json = json.dumps(compact_app_data_for_html(app_data), ensure_ascii=False).replace("</", "<\\/")
    pricing_json = json.dumps(PRICING, ensure_ascii=False).replace("</", "<\\/")
    html = '''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Copilot Token Usage Dashboard</title>
  <style>
    :root {{
      --bg: #111318;
      --panel: #181c23;
      --panel-2: #1f2530;
      --panel-3: #252d3a;
      --border: #303a4a;
      --text: #e6edf3;
      --muted: #98a7bd;
      --faint: #6f8098;
      --blue: #58a6ff;
      --green: #3fb950;
      --yellow: #d29922;
      --orange: #ff9b50;
      --purple: #bc8cff;
      --red: #f85149;
      --teal: #39c5cf;
      --shadow: rgba(0, 0, 0, 0.32);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      padding: 24px;
      background: var(--bg);
      color: var(--text);
      font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.45;
    }}
    button, input, select, textarea {{ font: inherit; }}
    .app {{ display: flex; flex-direction: column; gap: 18px; }}
    .header {{
      background: linear-gradient(180deg, rgba(88, 166, 255, 0.08), rgba(24, 28, 35, 0.98));
      border: 1px solid var(--border);
      border-radius: 18px;
      padding: 22px;
      box-shadow: 0 12px 36px var(--shadow);
    }}
    .header-top {{ display: flex; justify-content: space-between; gap: 24px; flex-wrap: wrap; }}
    .header h1 {{ margin: 0; font-size: 1.6rem; }}
    .subtitle {{ color: var(--muted); margin-top: 6px; }}
    .summary-grid {{
      margin-top: 18px;
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
      gap: 12px;
    }}
    .summary-card {{
      background: rgba(255, 255, 255, 0.03);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 14px;
    }}
    .summary-card .label {{ color: var(--muted); font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.04em; }}
    .summary-card .value {{ margin-top: 6px; font-size: 1.3rem; font-weight: 700; }}
    .value.input {{ color: var(--blue); }}
    .value.output {{ color: var(--orange); }}
    .value.cached {{ color: var(--green); }}
    .value.cost {{ color: var(--teal); }}
    .value.credits {{ color: var(--yellow); }}
    .tabs {{ display: flex; gap: 8px; margin-top: 18px; flex-wrap: wrap; }}
    .tab-button {{
      border: 1px solid var(--border);
      background: var(--panel-2);
      color: var(--text);
      padding: 10px 16px;
      border-radius: 999px;
      cursor: pointer;
      transition: 0.2s ease;
    }}
    .tab-button.active {{ background: var(--blue); color: #08111c; border-color: var(--blue); font-weight: 700; }}
    .tab-panel {{ display: none; }}
    .tab-panel.active {{ display: block; }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 18px;
      padding: 18px;
      box-shadow: 0 10px 28px var(--shadow);
    }}
    .filter-bar {{ display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 18px; }}
    .filter-bar input, .filter-bar select {{
      background: var(--panel-2);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 10px 12px;
      color: var(--text);
    }}
    .filter-bar input {{ flex: 1 1 260px; min-width: 220px; }}
    .legend {{ color: var(--muted); font-size: 0.9rem; }}
    .session-list {{ display: flex; flex-direction: column; gap: 10px; }}
    details.session-card, details.event-card {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 16px;
      overflow: hidden;
    }}
    details.session-card[open] {{ border-color: rgba(88, 166, 255, 0.45); }}
    details.event-card[open] {{ border-color: rgba(188, 140, 255, 0.38); }}
    .session-summary-row, .event-summary-row {{
      list-style: none;
      cursor: pointer;
      display: grid;
      gap: 12px;
      align-items: center;
      padding: 14px 16px;
      grid-template-columns: minmax(260px, 2.4fr) minmax(120px, 1fr) minmax(90px, .8fr) repeat(4, minmax(88px, .7fr));
    }}
    .session-summary-row:hover, .event-summary-row:hover {{ background: rgba(255, 255, 255, 0.025); }}
    summary::-webkit-details-marker {{ display: none; }}
    .title-col {{ display: flex; flex-direction: column; gap: 6px; min-width: 0; }}
    .title-line {{ display: flex; align-items: center; gap: 10px; min-width: 0; flex-wrap: wrap; }}
    .title-text {{ font-weight: 650; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .subtext {{ color: var(--muted); font-size: 0.85rem; }}
    .badge {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      border-radius: 999px;
      padding: 4px 10px;
      font-size: 0.75rem;
      font-weight: 700;
      border: 1px solid transparent;
      white-space: nowrap;
    }}
    .badge.model {{ background: rgba(188, 140, 255, 0.14); color: var(--purple); border-color: rgba(188, 140, 255, 0.28); }}
    .badge.user {{ background: rgba(88, 166, 255, 0.14); color: var(--blue); border-color: rgba(88, 166, 255, 0.28); }}
    .badge.tool {{ background: rgba(210, 153, 34, 0.16); color: var(--yellow); border-color: rgba(210, 153, 34, 0.28); }}
    .badge.source {{ background: rgba(255,255,255,0.06); color: var(--muted); border-color: rgba(255,255,255,0.08); }}
    .badge.chat {{ background: rgba(57, 197, 207, 0.14); color: var(--teal); border-color: rgba(57, 197, 207, 0.28); }}
    .badge.boundary {{ background: rgba(248, 81, 73, 0.14); color: var(--red); border-color: rgba(248, 81, 73, 0.28); }}
    .badge.mode-read {{ background: rgba(63, 185, 80, 0.14); color: var(--green); border-color: rgba(63, 185, 80, 0.28); }}
    .badge.mode-edit {{ background: rgba(248, 81, 73, 0.14); color: var(--red); border-color: rgba(248, 81, 73, 0.28); }}
    .stat-col {{ text-align: right; font-variant-numeric: tabular-nums; }}
    .stat-col .label {{ color: var(--faint); font-size: 0.72rem; text-transform: uppercase; }}
    .stat-col .value {{ font-size: 0.96rem; font-weight: 650; }}
    .stat-col .value.input {{ color: var(--blue); }}
    .stat-col .value.output {{ color: var(--orange); }}
    .stat-col .value.cached {{ color: var(--green); }}
    .stat-col .value.cost {{ color: var(--teal); }}
    .value.uncached {{ color: var(--yellow); }}
    .session-body, .event-body {{
      border-top: 1px solid rgba(255,255,255,0.06);
      background: rgba(255,255,255,0.015);
      padding: 16px;
    }}
    .session-meta {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; margin-bottom: 14px; }}
    .meta-card {{ background: var(--panel-2); border: 1px solid var(--border); border-radius: 12px; padding: 12px; }}
    .meta-card .label {{ color: var(--muted); font-size: 0.75rem; text-transform: uppercase; }}
    .meta-card .value {{ margin-top: 4px; font-weight: 700; }}
    .timeline {{ display: flex; flex-direction: column; gap: 10px; }}
    .event-body-grid {{ display: grid; gap: 12px; }}
    .event-section {{ background: var(--panel-2); border: 1px solid var(--border); border-radius: 12px; padding: 12px; }}
    .event-section h4 {{ margin: 0 0 8px 0; font-size: 0.95rem; }}
    pre {{
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 0.82rem;
      color: #d6e2f1;
      max-height: 460px;
      overflow: auto;
      line-height: 1.45;
    }}
    .message-list {{ display: flex; flex-direction: column; gap: 10px; }}
    .message-card {{ background: var(--panel-2); border: 1px solid var(--border); border-radius: 12px; padding: 12px; }}
    .message-header {{ display: flex; justify-content: space-between; align-items: center; gap: 10px; margin-bottom: 8px; flex-wrap: wrap; }}
    .message-parts {{ display: flex; flex-direction: column; gap: 8px; }}
    .part-card {{ background: rgba(255,255,255,0.025); border: 1px solid rgba(255,255,255,0.05); border-radius: 10px; padding: 10px; }}
    .part-label {{ color: var(--muted); font-size: 0.75rem; text-transform: uppercase; margin-bottom: 6px; }}
    .genai-button {{
      border: 1px solid rgba(88, 166, 255, 0.45);
      background: rgba(88, 166, 255, 0.12);
      color: var(--blue);
      padding: 6px 10px;
      border-radius: 999px;
      cursor: pointer;
      font-weight: 700;
    }}
    .genai-button:hover {{ background: rgba(88, 166, 255, 0.18); }}
    .analysis-grid {{ display: grid; gap: 18px; }}
    .analysis-subtabs {{ display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 14px; }}
    .subtab-button {{ border: 1px solid var(--border); background: var(--panel-2); color: var(--text); border-radius: 999px; padding: 8px 12px; cursor: pointer; }}
    .subtab-button.active {{ background: var(--purple); color: #12071e; border-color: var(--purple); font-weight: 700; }}
    .section-title {{ margin: 0 0 10px 0; font-size: 1.1rem; }}
    .section-subtitle {{ color: var(--muted); margin-bottom: 12px; }}
    .pagination {{ display: flex; justify-content: space-between; gap: 12px; align-items: center; flex-wrap: wrap; margin-top: 14px; }}
    .pagination-controls {{ display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }}
    .pagination button, .sort-button {{ border: 1px solid var(--border); background: var(--panel-2); color: var(--text); padding: 8px 12px; border-radius: 10px; cursor: pointer; }}
    .pagination button:disabled {{ opacity: 0.45; cursor: default; }}
    .sort-button.active {{ border-color: var(--blue); color: var(--blue); }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.9rem; }}
    th, td {{ border-bottom: 1px solid rgba(255,255,255,0.06); padding: 10px 8px; text-align: left; vertical-align: top; }}
    th {{ color: var(--muted); font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.04em; }}
    th button {{ all: unset; cursor: pointer; color: inherit; }}
    td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
    .compact-prices-wrap {{ overflow-x: auto; }}
    .compact-prices-table {{ width: auto; min-width: 540px; font-size: 0.84rem; }}
    .compact-prices-table th, .compact-prices-table td {{ padding: 6px 8px; text-align: left; white-space: nowrap; }}
    .compact-prices-table td strong {{ font-weight: 650; }}
    .tool-catalog-controls {{ display:flex; gap:8px; flex-wrap:wrap; margin-bottom:12px; align-items:center; }}
    .tool-catalog-controls input, .tool-catalog-controls select {{
      background: var(--panel-2);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 8px 10px;
      color: var(--text);
    }}
    .tool-catalog-controls input {{ min-width: 220px; flex: 1 1 240px; }}
    tr.clickable-row {{ cursor: pointer; }}
    tr.clickable-row:hover {{ background: rgba(255,255,255,0.03); }}
    .pill-list {{ display: flex; gap: 6px; flex-wrap: wrap; }}
    .pill {{ background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.08); border-radius: 999px; padding: 3px 8px; font-size: 0.75rem; color: var(--muted); }}
    .note {{ color: var(--muted); font-size: 0.88rem; }}
    .insights-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 12px; }}
    details.collapsible-section > summary {{ list-style: none; }}
    details.collapsible-section > summary::-webkit-details-marker {{ display: none; }}
    details.collapsible-section {{ border-radius: 18px; }}
    .insight-card h4 {{ overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 100%; }}
    .insight-card {{ background: var(--panel-2); border: 1px solid var(--border); border-radius: 14px; padding: 14px; }}
    .insight-card h4 {{ margin: 0 0 10px 0; }}
    .chart-card {{ background: var(--panel-2); border: 1px solid var(--border); border-radius: 12px; padding: 12px; }}
    .chart-svg {{ width: 100%; height: 260px; display: block; }}
    .chart-legend {{ display: flex; gap: 12px; flex-wrap: wrap; margin-top: 10px; color: var(--muted); font-size: 0.82rem; }}
    .legend-item {{ display: inline-flex; align-items: center; gap: 6px; }}
    .legend-swatch {{ width: 14px; height: 4px; border-radius: 999px; display: inline-block; }}
    .modal-backdrop {{
      position: fixed;
      inset: 0;
      background: rgba(0, 0, 0, 0.62);
      display: none;
      align-items: center;
      justify-content: center;
      padding: 20px;
      z-index: 1000;
    }}
    .modal-backdrop.open {{ display: flex; }}
    .modal {{
      width: min(1180px, 96vw);
      max-height: 92vh;
      overflow: hidden;
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 18px;
      box-shadow: 0 18px 46px rgba(0,0,0,0.48);
      display: flex;
      flex-direction: column;
    }}
    .modal-header {{ padding: 16px 18px; border-bottom: 1px solid rgba(255,255,255,0.06); display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; }}
    .modal-header h3 {{ margin: 0 0 6px 0; }}
    .modal-actions button {{
      border: 1px solid var(--border);
      background: var(--panel-2);
      color: var(--text);
      padding: 8px 12px;
      border-radius: 10px;
      cursor: pointer;
    }}
    .modal-body {{ overflow: auto; padding: 16px 18px 18px; display: flex; flex-direction: column; gap: 14px; }}
    .modal-tabs {{ display: flex; gap: 8px; flex-wrap: wrap; }}
    .modal-tab {{ border: 1px solid var(--border); background: var(--panel-2); color: var(--text); border-radius: 999px; padding: 8px 12px; cursor: pointer; }}
    .modal-tab.active {{ background: var(--teal); color: #041114; border-color: var(--teal); font-weight: 700; }}
    .modal-panel {{ display: none; }}
    .modal-panel.active {{ display: block; }}
    .split-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
    .help-list {{ margin: 0; padding-left: 18px; }}
    .help-list li {{ margin: 6px 0; }}
    .small {{ font-size: 0.82rem; }}
    @media (max-width: 1100px) {{
      .session-summary-row, .event-summary-row {{
        grid-template-columns: minmax(220px, 1.8fr) minmax(110px, .9fr) minmax(90px, .7fr) repeat(2, minmax(90px, .8fr));
      }}
      .stat-col.hide-mobile {{ display: none; }}
      .split-grid {{ grid-template-columns: 1fr; }}
    }}
    @media (max-width: 760px) {{
      body {{ padding: 14px; }}
      .session-summary-row, .event-summary-row {{ display: flex; flex-direction: column; align-items: stretch; gap: 10px; }}
      .stat-col {{ text-align: left; }}
      .title-line {{ gap: 8px; }}
    }}
  </style>
</head>
<body>
  <div id="app" class="app"></div>
  <div id="fullChatModalBackdrop" class="modal-backdrop" onclick="closeFullChatModal(event)">
    <div class="modal" onclick="event.stopPropagation()" style="max-width:1180px">
      <div class="modal-header">
        <div>
          <h3 id="fullChatModalTitle">Full chat</h3>
          <div id="fullChatModalSubtitle" class="subtitle"></div>
        </div>
        <div class="modal-actions" style="display:flex;gap:8px">
          <button type="button" id="fullChatExportBtn" onclick="" style="border:1px solid rgba(57,197,207,0.45);background:rgba(57,197,207,0.12);color:var(--teal);padding:8px 12px;border-radius:10px;cursor:pointer;font-weight:700;font-size:0.85rem">⬇ Export chat JSON</button>
          <button type="button" onclick="closeFullChatModal()">Close</button>
        </div>
      </div>
      <div class="modal-body">
        <div id="fullChatModalContent"></div>
      </div>
    </div>
  </div>
  <div id="genaiModalBackdrop" class="modal-backdrop" onclick="closeGenAiModal(event)">
    <div class="modal" onclick="event.stopPropagation()">
      <div class="modal-header">
        <div>
          <h3 id="genaiModalTitle">GenAI details</h3>
          <div id="genaiModalSubtitle" class="subtitle"></div>
        </div>
        <div class="modal-actions">
          <button type="button" onclick="closeGenAiModal()">Close</button>
        </div>
      </div>
      <div class="modal-body">
        <div id="genaiModalStats" class="session-meta"></div>
        <div id="genaiModalTabs" class="modal-tabs"></div>
        <div id="genaiModalContent"></div>
      </div>
    </div>
  </div>
  <div id="fileModalBackdrop" class="modal-backdrop" onclick="closeFileModal(event)">
    <div class="modal" onclick="event.stopPropagation()">
      <div class="modal-header">
        <div>
          <h3 id="fileModalTitle">File timeline</h3>
          <div id="fileModalSubtitle" class="subtitle"></div>
        </div>
        <div class="modal-actions" style="display:flex;gap:8px">
          <button type="button" id="fileExportBtn" onclick="" style="border:1px solid rgba(57,197,207,0.45);background:rgba(57,197,207,0.12);color:var(--teal);padding:8px 12px;border-radius:10px;cursor:pointer;font-weight:700;font-size:0.85rem">⬇ Export JSON</button>
          <button type="button" onclick="closeFileModal()">Close</button>
        </div>
      </div>
      <div class="modal-body">
        <div id="fileModalStats" class="session-meta"></div>
        <div id="fileModalContent"></div>
      </div>
    </div>
  </div>
  <div id="modelCompareModalBackdrop" class="modal-backdrop" onclick="closeModelCompareModal(event)">
    <div class="modal" onclick="event.stopPropagation()" style="max-width:700px">
      <div class="modal-header">
        <div>
          <h3 id="modelCompareModalTitle">Model cost comparison</h3>
          <div id="modelCompareModalSubtitle" class="subtitle"></div>
        </div>
        <div class="modal-actions">
          <button type="button" onclick="closeModelCompareModal()">Close</button>
        </div>
      </div>
      <div class="modal-body">
        <div id="modelCompareModalContent"></div>
      </div>
    </div>
  </div>
  <div id="chatDeleteModalBackdrop" class="modal-backdrop" onclick="closeChatDeleteModal(event)">
    <div class="modal" onclick="event.stopPropagation()" style="max-width:760px">
      <div class="modal-header">
        <div>
          <h3>Delete chats from view</h3>
          <div class="subtitle">This hides chats locally in your browser (from the Chats tab). It does not delete raw debug logs.</div>
        </div>
        <div class="modal-actions">
          <button type="button" onclick="closeChatDeleteModal()">Close</button>
        </div>
      </div>
      <div class="modal-body">
        <div class="event-section">
          <div style="display:flex;flex-direction:column;gap:10px">
            <label><input type="radio" name="chatDeleteMode" value="all" onchange="setDeleteMode(this.value)" checked> Delete all visible chats</label>
            <label style="display:flex;flex-wrap:wrap;align-items:center;gap:8px"><input type="radio" name="chatDeleteMode" value="before_date" onchange="setDeleteMode(this.value)"> Delete chats before
              <select id="deleteAgePreset" onchange="setDeleteAgePreset(this.value)">
                <option value="day">last day cutoff</option>
                <option value="week" selected>last week cutoff</option>
                <option value="month">last month cutoff</option>
                <option value="custom">specific date</option>
              </select>
              <input type="date" id="deleteSpecificDate" onchange="setDeleteSpecificDate(this.value)">
            </label>
            <label style="display:flex;flex-wrap:wrap;align-items:center;gap:8px"><input type="radio" name="chatDeleteMode" value="keep_last" onchange="setDeleteMode(this.value)"> Delete all but the last
              <input type="number" id="deleteKeepCount" min="1" step="1" value="10" style="width:90px" onchange="setDeleteKeepCount(this.value)"> chats
            </label>
          </div>
        </div>
        <div id="chatDeletePreview" class="note"></div>
        <div style="display:flex;justify-content:flex-end;gap:8px">
          <button type="button" onclick="closeChatDeleteModal()">Cancel</button>
          <button type="button" id="chatDeleteApplyBtn" onclick="applyChatDeletion()" style="border:1px solid rgba(248,81,73,0.45);background:rgba(248,81,73,0.12);color:var(--red);font-weight:700">Delete selected chats</button>
        </div>
      </div>
    </div>
  </div>

  <script>
    const APP_DATA = __APP_JSON__;
    const STATE = {
      activeTab: 'chats',
      usagePeriod: (APP_DATA.periods && APP_DATA.periods.default) || 'monthly',
      tokenMode: 'attributed',
      analysisTab: 'models',
      toolImpactTab: 'usage',
      dataTab: 'prices',
      monthlyTrendMetric: 'cost',
      toolCatalogSearch: '',
      toolCatalogSortKey: 'descriptionTokens',
      toolCatalogSortDir: 'desc',
      toolWasteSortKey: 'wastedInputTokens',
      toolWasteSortDir: 'desc',
      toolImpactSearch: '',
      search: '',
      model: '',
      page: 1,
      pageSize: 10,
      fileSearch: '',
      fileSortKey: 'cost',
      fileSortDir: 'desc',
      toolSortKey: 'cost',
      toolSortDir: 'desc',
      autoRefresh: false,
      refreshInterval: 60000,
      refreshTimer: null,
      deleteMode: 'all',
      deleteAgePreset: 'week',
      deleteCustomDate: '',
      deleteKeepCount: 10,
    };

    const STORAGE_KEYS = {
      hiddenSessions: 'copilot-dashboard-hidden-sessions-v1',
      tokenMode: 'copilot-dashboard-token-mode-v1',
    };

    function loadHiddenSessionIds() {
      try {
        const raw = localStorage.getItem(STORAGE_KEYS.hiddenSessions);
        const parsed = raw ? JSON.parse(raw) : [];
        if (!Array.isArray(parsed)) return new Set();
        return new Set(parsed.filter((value) => typeof value === 'string' && value));
      } catch (_err) {
        return new Set();
      }
    }

    const HIDDEN_SESSION_IDS = loadHiddenSessionIds();

    function normalizeTokenMode(mode) {
      return mode === 'billed' ? 'billed' : 'attributed';
    }

    function loadTokenMode() {
      try {
        return normalizeTokenMode(localStorage.getItem(STORAGE_KEYS.tokenMode));
      } catch (_err) {
        return 'attributed';
      }
    }

    STATE.tokenMode = loadTokenMode();

    function persistHiddenSessionIds() {
      try {
        localStorage.setItem(STORAGE_KEYS.hiddenSessions, JSON.stringify(Array.from(HIDDEN_SESSION_IDS)));
      } catch (_err) {
        // Ignore storage failures (private mode / disabled storage).
      }
    }

    function persistTokenMode() {
      try {
        localStorage.setItem(STORAGE_KEYS.tokenMode, normalizeTokenMode(STATE.tokenMode));
      } catch (_err) {
        // Ignore storage failures (private mode / disabled storage).
      }
    }

    function isSessionHidden(sessionId) {
      return HIDDEN_SESSION_IDS.has(sessionId);
    }

    function currentMonthKey() {
      const now = new Date();
      const year = now.getFullYear();
      const month = String(now.getMonth() + 1).padStart(2, '0');
      return `${year}-${month}`;
    }

    function formatMonthLabelFromKey(monthKey) {
      if (!monthKey || !/^\\d{4}-\\d{2}$/.test(String(monthKey))) {
        return 'Current month';
      }
      const date = new Date(`${monthKey}-01T12:00:00`);
      if (!Number.isFinite(date.getTime())) {
        return String(monthKey);
      }
      return date.toLocaleString(undefined, { month: 'long', year: 'numeric' });
    }

    function zeroTokenBlock() {
      return { input: 0, uncached: 0, output: 0, cached: 0, cost: 0 };
    }

    function addTokenBlock(target, block, factor = 1) {
      if (!target || !block) return target;
      target.input += Number(block.input || 0) * factor;
      target.uncached += Number(block.uncached || 0) * factor;
      target.output += Number(block.output || 0) * factor;
      target.cached += Number(block.cached || 0) * factor;
      target.cost += Number(block.cost || 0) * factor;
      return target;
    }

    function cloneTokenBlock(block) {
      const src = block || {};
      return {
        input: Number(src.input || 0),
        uncached: Number(src.uncached || 0),
        output: Number(src.output || 0),
        cached: Number(src.cached || 0),
        cost: Number(src.cost || 0),
      };
    }

    function isBilledMode() {
      return normalizeTokenMode(STATE.tokenMode) === 'billed';
    }

    function tokenModeLabel() {
      return isBilledMode() ? 'billed' : 'attributed';
    }

    function pickTokenBlock(attributedBlock, billedBlock) {
      if (isBilledMode()) {
        return cloneTokenBlock(billedBlock || attributedBlock || zeroTokenBlock());
      }
      return cloneTokenBlock(attributedBlock || billedBlock || zeroTokenBlock());
    }

    function summaryDisplayTotals(summary) {
      return pickTokenBlock(summary?.totals, summary?.billedTotals);
    }

    function sessionDisplayTotals(session) {
      return pickTokenBlock(session?.totals, session?.billed_totals);
    }

    function eventDisplayChatTokens(event) {
      return pickTokenBlock(event?.attribution_tokens, event?.billed_tokens);
    }

    function cacheHitRateForBlock(block) {
      const input = Number(block?.input || 0);
      if (!input) return 0;
      return (Number(block?.cached || 0) / input) * 100;
    }

    function tokenScale(base, target) {
      const from = Number(base || 0);
      const to = Number(target || 0);
      if (from > 0) return to / from;
      if (to > 0) return 1;
      return 0;
    }

    function tokenScaleFactors(attributedBlock, billedBlock) {
      const source = attributedBlock || zeroTokenBlock();
      const target = billedBlock || source;
      return {
        input: tokenScale(source.input, target.input),
        uncached: tokenScale(source.uncached, target.uncached),
        output: tokenScale(source.output, target.output),
        cached: tokenScale(source.cached, target.cached),
        cost: tokenScale(source.cost, target.cost),
      };
    }

    function scaleTokenBlock(block, factors, factor = 1) {
      const src = block || zeroTokenBlock();
      const scale = factors || { input: 1, uncached: 1, output: 1, cached: 1, cost: 1 };
      return {
        input: Number(src.input || 0) * Number(scale.input || 0) * factor,
        uncached: Number(src.uncached || 0) * Number(scale.uncached || 0) * factor,
        output: Number(src.output || 0) * Number(scale.output || 0) * factor,
        cached: Number(src.cached || 0) * Number(scale.cached || 0) * factor,
        cost: Number(src.cost || 0) * Number(scale.cost || 0) * factor,
      };
    }

    function sessionScaleFactors(session) {
      return tokenScaleFactors(session?.totals, session?.billed_totals || session?.totals);
    }

    function eventDisplayEstimatedTokens(event, session) {
      const estimated = cloneTokenBlock(event?.estimated_tokens || zeroTokenBlock());
      if (!isBilledMode()) return estimated;
      return scaleTokenBlock(estimated, sessionScaleFactors(session));
    }

    function sessionOverheadForMode(session) {
      const overhead = session?.overhead || {};
      if (!isBilledMode()) return overhead;
      const adjusted = zeroOverheadBuckets();
      const factors = sessionScaleFactors(session);
      Object.keys(adjusted).forEach((key) => {
        if (overhead[key]) {
          addTokenBlock(adjusted[key], scaleTokenBlock(overhead[key], factors));
        }
      });
      return adjusted;
    }

    function monthKeyFromTimestamp(ts) {
      if (!ts && ts !== 0) return null;
      const parsed = new Date(Number(ts));
      if (!Number.isFinite(parsed.getTime())) return null;
      const month = String(parsed.getMonth() + 1).padStart(2, '0');
      return `${parsed.getFullYear()}-${month}`;
    }

    function buildMonthlyBilledTrends(sessions) {
      const byMonth = new Map();
      (sessions || []).forEach((session) => {
        const key = monthKeyFromTimestamp(session?.timestamp);
        if (!key) return;
        if (!byMonth.has(key)) {
          byMonth.set(key, {
            monthKey: key,
            label: formatMonthLabelFromKey(key),
            sessionCount: 0,
            chatCallCount: 0,
            toolCallCount: 0,
            messageCount: 0,
            modelCount: 0,
            segmentCount: 0,
            modelSwitchCount: 0,
            contextResetCount: 0,
            totals: zeroTokenBlock(),
            peakPromptTokens: 0,
            modelNames: new Set(),
          });
        }
        const row = byMonth.get(key);
        const sessionTotals = cloneTokenBlock(session?.billed_totals || session?.totals || zeroTokenBlock());
        row.sessionCount += 1;
        row.chatCallCount += Number(session?.chat_count || 0);
        row.toolCallCount += Number(session?.tool_count || 0);
        row.messageCount += Number(session?.message_count || 0);
        row.segmentCount += Number(session?.segment_count || 0);
        row.modelSwitchCount += Number(session?.boundary_counts?.model_switch || 0);
        row.contextResetCount += Number(session?.boundary_counts?.context_reset || 0);
        row.peakPromptTokens = Math.max(row.peakPromptTokens, Number(session?.peak_prompt_tokens || 0));
        addTokenBlock(row.totals, sessionTotals);
        const names = Array.isArray(session?.model_names) && session.model_names.length
          ? session.model_names
          : [session?.model];
        names.filter(Boolean).forEach((name) => row.modelNames.add(String(name)));
      });

      return Array.from(byMonth.values())
        .sort((a, b) => String(a.monthKey).localeCompare(String(b.monthKey)))
        .map((row) => {
          const cacheHitRate = cacheHitRateForBlock(row.totals);
          return {
            monthKey: row.monthKey,
            label: row.label,
            sessionCount: row.sessionCount,
            chatCallCount: row.chatCallCount,
            toolCallCount: row.toolCallCount,
            messageCount: row.messageCount,
            modelCount: row.modelNames.size,
            segmentCount: row.segmentCount,
            modelSwitchCount: row.modelSwitchCount,
            contextResetCount: row.contextResetCount,
            totals: row.totals,
            cacheHitRate,
            aiCredits: Number(row.totals.cost || 0) / 0.01,
            peakPromptTokens: row.peakPromptTokens,
          };
        });
    }

    const BILLED_ANALYSIS_CACHE = {
      key: null,
      value: null,
    };

    function buildTopChatsForMode(sessions, useBilledTokens) {
      const rows = [];
      (sessions || []).forEach((session) => {
        const sessionId = String(session?.id || '');
        const sessionTitle = String(session?.title || 'Untitled chat');
        (session?.events || []).forEach((event) => {
          if (event?.kind !== 'chat') return;
          const block = cloneTokenBlock(
            useBilledTokens
              ? (event?.billed_tokens || event?.attribution_tokens || zeroTokenBlock())
              : (event?.attribution_tokens || event?.billed_tokens || zeroTokenBlock())
          );
          rows.push({
            sessionId,
            sessionTitle,
            model: String(event?.model || 'unknown'),
            title: event?.title || 'chat',
            durationMs: Number(event?.duration_ms || 0),
            cost: Number(block.cost || 0),
            input: Number(block.input || 0),
            uncached: Number(block.uncached || 0),
            output: Number(block.output || 0),
            cached: Number(block.cached || 0),
            promptTokens: Number(event?.prompt_tokens || 0),
            timestamp: event?.ts,
          });
        });
      });
      return rows.sort((a, b) => Number(b.cost || 0) - Number(a.cost || 0)).slice(0, 6);
    }

    function buildBilledAnalysis(baseAnalysis, sessions) {
      const analysis = baseAnalysis || {};
      const modelMap = new Map();
      const toolMap = new Map();
      const fileMap = new Map();
      const overhead = zeroOverheadBuckets();
      const topChats = [];
      const slowestTools = [];

      (sessions || []).forEach((session) => {
        const sessionId = String(session?.id || '');
        const sessionTitle = String(session?.title || 'Untitled chat');
        const factors = sessionScaleFactors(session);

        Object.entries(sessionOverheadForMode(session) || {}).forEach(([key, block]) => {
          if (overhead[key]) addTokenBlock(overhead[key], block);
        });

        (session?.events || []).forEach((event) => {
          const kind = event?.kind;
          if (kind === 'chat') {
            const modelName = String(event?.model || 'unknown');
            if (!modelMap.has(modelName)) {
              modelMap.set(modelName, {
                name: modelName,
                count: 0,
                durationMs: 0,
                ttftMs: 0,
                totals: zeroTokenBlock(),
                sessionIds: new Set(),
              });
            }
            const bucket = modelMap.get(modelName);
            const billed = cloneTokenBlock(event?.billed_tokens || event?.attribution_tokens || zeroTokenBlock());
            bucket.count += 1;
            bucket.durationMs += Number(event?.duration_ms || 0);
            bucket.ttftMs += Number(event?.ttft_ms || 0);
            addTokenBlock(bucket.totals, billed);
            bucket.sessionIds.add(sessionId);

            topChats.push({
              sessionId,
              sessionTitle,
              model: modelName,
              title: event?.title || `chat ${modelName}`,
              durationMs: Number(event?.duration_ms || 0),
              cost: Number(billed.cost || 0),
              input: Number(billed.input || 0),
              uncached: Number(billed.uncached || 0),
              output: Number(billed.output || 0),
              cached: Number(billed.cached || 0),
              promptTokens: Number(event?.prompt_tokens || 0),
              timestamp: event?.ts,
            });
            return;
          }

          if (kind !== 'tool') return;

          const toolName = String(event?.name || 'unknown');
          const mode = String(event?.mode || 'other');
          const toolKey = `${toolName}::${mode}`;
          const billedEstimated = scaleTokenBlock(event?.estimated_tokens || zeroTokenBlock(), factors);
          const payloadTokens = Number(event?.payload_tokens_estimate || 0);

          if (!toolMap.has(toolKey)) {
            toolMap.set(toolKey, {
              name: toolName,
              mode,
              count: 0,
              errors: 0,
              durationMs: 0,
              payloadTokens: 0,
              totals: zeroTokenBlock(),
              sessionIds: new Set(),
            });
          }
          const toolBucket = toolMap.get(toolKey);
          toolBucket.count += 1;
          toolBucket.errors += event?.status === 'ok' ? 0 : 1;
          toolBucket.durationMs += Number(event?.duration_ms || 0);
          toolBucket.payloadTokens += payloadTokens;
          addTokenBlock(toolBucket.totals, billedEstimated);
          toolBucket.sessionIds.add(sessionId);

          slowestTools.push({
            sessionId,
            sessionTitle,
            name: toolName,
            title: event?.title || toolName,
            durationMs: Number(event?.duration_ms || 0),
            status: event?.status || 'unknown',
            estimated: billedEstimated,
            timestamp: event?.ts,
          });

          const filePaths = (event?.files || []).filter((path) => typeof path === 'string' && path);
          if (!filePaths.length) return;
          const fileShare = 1 / filePaths.length;

          filePaths.forEach((filePath) => {
            if (!fileMap.has(filePath)) {
              const parts = String(filePath).split('/').filter(Boolean);
              const name = parts[parts.length - 1] || String(filePath);
              fileMap.set(filePath, {
                path: filePath,
                shortPath: filePath,
                name,
                readCount: 0,
                editCount: 0,
                payloadTokens: 0,
                totals: zeroTokenBlock(),
                tools: new Set(),
                sessionIds: new Set(),
                  toolUsage: new Map(),
                  toolReferenceCount: 0,
              });
            }
            const fileBucket = fileMap.get(filePath);
            const eventShare = scaleTokenBlock(billedEstimated, { input: 1, uncached: 1, output: 1, cached: 1, cost: 1 }, fileShare);
            fileBucket.payloadTokens += payloadTokens * fileShare;
            fileBucket.tools.add(toolName);
            fileBucket.sessionIds.add(sessionId);
              fileBucket.toolReferenceCount += 1;
            if (mode === 'read') fileBucket.readCount += 1;
            if (mode === 'edit') fileBucket.editCount += 1;
            addTokenBlock(fileBucket.totals, eventShare);

              const usageKey = `${toolName}::${mode}`;
              if (!fileBucket.toolUsage.has(usageKey)) {
                fileBucket.toolUsage.set(usageKey, {
                  name: toolName,
                  mode,
                  count: 0,
                  durationMs: 0,
                  payloadTokens: 0,
                  totals: zeroTokenBlock(),
                  sessionIds: new Set(),
                });
              }
              const usageBucket = fileBucket.toolUsage.get(usageKey);
              usageBucket.count += 1;
              usageBucket.durationMs += Number(event?.duration_ms || 0);
              usageBucket.payloadTokens += payloadTokens * fileShare;
              addTokenBlock(usageBucket.totals, eventShare);
              usageBucket.sessionIds.add(sessionId);
          });
        });
      });

      const models = Array.from(modelMap.values()).map((bucket) => ({
        name: bucket.name,
        count: bucket.count,
        sessionCount: bucket.sessionIds.size,
        durationMs: bucket.durationMs,
        avgDurationMs: bucket.count ? bucket.durationMs / bucket.count : 0,
        avgTtftMs: bucket.count ? bucket.ttftMs / bucket.count : 0,
        input: bucket.totals.input,
        uncached: bucket.totals.uncached,
        output: bucket.totals.output,
        cached: bucket.totals.cached,
        cost: bucket.totals.cost,
        cacheHitRate: cacheHitRateForBlock(bucket.totals),
      })).sort((a, b) => Number(b.cost || 0) - Number(a.cost || 0));

      const tools = Array.from(toolMap.values()).map((bucket) => ({
        name: bucket.name,
        mode: bucket.mode,
        count: bucket.count,
        sessionCount: bucket.sessionIds.size,
        errors: bucket.errors,
        durationMs: bucket.durationMs,
        avgDurationMs: bucket.count ? bucket.durationMs / bucket.count : 0,
        payloadTokens: bucket.payloadTokens,
        avgPayloadTokens: bucket.count ? bucket.payloadTokens / bucket.count : 0,
        input: bucket.totals.input,
        uncached: bucket.totals.uncached,
        output: bucket.totals.output,
        cached: bucket.totals.cached,
        cost: bucket.totals.cost,
        avgInput: bucket.count ? bucket.totals.input / bucket.count : 0,
        avgOutput: bucket.count ? bucket.totals.output / bucket.count : 0,
        avgCached: bucket.count ? bucket.totals.cached / bucket.count : 0,
        avgCost: bucket.count ? bucket.totals.cost / bucket.count : 0,
      }));

      const files = Array.from(fileMap.values()).map((bucket) => {
        const ops = bucket.readCount + bucket.editCount;
        const toolUsage = Array.from(bucket.toolUsage.values()).map((usage) => ({
          name: usage.name,
          mode: usage.mode,
          count: usage.count,
          sessionCount: usage.sessionIds.size,
          durationMs: usage.durationMs,
          avgDurationMs: usage.count ? usage.durationMs / usage.count : 0,
          payloadTokens: usage.payloadTokens,
          avgPayloadTokens: usage.count ? usage.payloadTokens / usage.count : 0,
          input: usage.totals.input,
          uncached: usage.totals.uncached,
          output: usage.totals.output,
          cached: usage.totals.cached,
          cost: usage.totals.cost,
          avgInput: usage.count ? usage.totals.input / usage.count : 0,
          avgOutput: usage.count ? usage.totals.output / usage.count : 0,
          avgCached: usage.count ? usage.totals.cached / usage.count : 0,
          avgCost: usage.count ? usage.totals.cost / usage.count : 0,
        })).sort((a, b) => Number(b.cost || 0) - Number(a.cost || 0) || Number(b.count || 0) - Number(a.count || 0));
        return {
          path: bucket.path,
          shortPath: bucket.shortPath,
          name: bucket.name,
          readCount: bucket.readCount,
          editCount: bucket.editCount,
          sessionCount: bucket.sessionIds.size,
          payloadTokens: bucket.payloadTokens,
          avgInput: ops ? bucket.totals.input / ops : 0,
          avgOutput: ops ? bucket.totals.output / ops : 0,
          avgCached: ops ? bucket.totals.cached / ops : 0,
          avgCost: ops ? bucket.totals.cost / ops : 0,
          input: bucket.totals.input,
          uncached: bucket.totals.uncached,
          output: bucket.totals.output,
          cached: bucket.totals.cached,
          cost: bucket.totals.cost,
          tools: Array.from(bucket.tools).sort(),
          toolUsage,
          toolReferenceCount: bucket.toolReferenceCount,
        };
      });

      const baseSummary = activeSummary();
      const wasteFactors = tokenScaleFactors(baseSummary?.totals, baseSummary?.billedTotals || baseSummary?.totals);
      const toolCatalog = (analysis.toolCatalog || []).map((row) => ({
        ...row,
        wastedInputTokens: Number(row.wastedInputTokens || 0) * Number(wasteFactors.input || 0),
        wastedUncachedTokens: Number(row.wastedUncachedTokens || 0) * Number(wasteFactors.uncached || 0),
        wastedCachedTokens: Number(row.wastedCachedTokens || 0) * Number(wasteFactors.cached || 0),
      }));

      const monthlyTrends = buildMonthlyBilledTrends(sessions);

      return {
        ...analysis,
        models,
        tools,
        files,
        overhead,
        topChats: topChats.sort((a, b) => Number(b.cost || 0) - Number(a.cost || 0)).slice(0, 6),
        slowestTools: slowestTools.sort((a, b) => Number(b.durationMs || 0) - Number(a.durationMs || 0)).slice(0, 6),
        toolCatalog,
        monthlyTrends,
      };
    }

    function analysisForMode() {
      // Attributed and billed analyses are both pre-computed server-side, so the
      // mode toggle is a pure selection — no client-side recomputation needed.
      const bundle = activePeriodBundle();
      if (isBilledMode()) {
        return bundle.analysisBilled || bundle.analysis || APP_DATA.analysis || {};
      }
      return bundle.analysis || APP_DATA.analysis || {};
    }

    function zeroOverheadBuckets() {
      return {
        system_prompt: zeroTokenBlock(),
        tool_definitions: zeroTokenBlock(),
        assistant_context: zeroTokenBlock(),
        user_messages: zeroTokenBlock(),
        tools: zeroTokenBlock(),
        files: zeroTokenBlock(),
        unattributed: zeroTokenBlock(),
      };
    }

    function emptyMonthlyBundle(monthKey) {
      const fallbackAnalysis = APP_DATA?.periods?.allTime?.analysis || APP_DATA.analysis || {};
      return {
        monthKey,
        label: formatMonthLabelFromKey(monthKey),
        summary: {
          sessionCount: 0,
          chatCallCount: 0,
          toolCallCount: 0,
          messageCount: 0,
          modelCount: 0,
          segmentCount: 0,
          modelSwitchCount: 0,
          contextResetCount: 0,
          totals: zeroTokenBlock(),
          cacheHitRate: 0,
          aiCredits: 0,
          peakPromptTokens: 0,
        },
        analysis: {
          models: [],
          tools: [],
          toolCatalog: [],
          files: [],
          topChats: [],
          slowestTools: [],
          overhead: zeroOverheadBuckets(),
          telemetry: fallbackAnalysis.telemetry || { sections: [], observedFields: [], entryTypes: {} },
          monthlyTrends: fallbackAnalysis.monthlyTrends || [],
        },
        analysisBilled: {
          models: [],
          tools: [],
          toolCatalog: [],
          files: [],
          topChats: [],
          slowestTools: [],
          overhead: zeroOverheadBuckets(),
          telemetry: fallbackAnalysis.telemetry || { sections: [], observedFields: [], entryTypes: {} },
          monthlyTrends: fallbackAnalysis.monthlyTrends || [],
        },
        sessionIds: [],
      };
    }

    function activePeriodBundle() {
      const periods = APP_DATA.periods || {};
      if (STATE.usagePeriod === 'allTime') {
        return periods.allTime || {
          summary: APP_DATA.summary || {},
          analysis: APP_DATA.analysis || {},
          sessionIds: (APP_DATA.sessions || []).map((session) => session.id),
        };
      }

      const monthly = periods.monthly;
      const monthKey = currentMonthKey();
      if (monthly && monthly.monthKey === monthKey) {
        return monthly;
      }
      return emptyMonthlyBundle(monthKey);
    }

    function activeSummary() {
      return activePeriodBundle().summary || APP_DATA.summary || {};
    }

    function activeAnalysis() {
      return activePeriodBundle().analysis || APP_DATA.analysis || {};
    }

    function activePeriodLabel() {
      if (STATE.usagePeriod === 'allTime') {
        return (APP_DATA.periods?.labels?.allTime) || 'All time';
      }
      const bundle = activePeriodBundle();
      if (bundle?.label) return bundle.label;
      return formatMonthLabelFromKey(currentMonthKey());
    }

    function sessionsForActivePeriod() {
      const bundle = activePeriodBundle();
      if (!Array.isArray(bundle?.sessionIds)) {
        return APP_DATA.sessions || [];
      }
      const allowed = new Set(bundle.sessionIds);
      return (APP_DATA.sessions || []).filter((session) => allowed.has(session.id));
    }

    function visibleSessions() {
      return sessionsForActivePeriod().filter((session) => !isSessionHidden(session.id));
    }

    function markSessionsHidden(sessionIds) {
      let changed = 0;
      for (const sessionId of sessionIds || []) {
        if (!sessionId || HIDDEN_SESSION_IDS.has(sessionId)) continue;
        HIDDEN_SESSION_IDS.add(sessionId);
        changed += 1;
      }
      if (changed) {
        persistHiddenSessionIds();
      }
      return changed;
    }

    function restoreHiddenChats() {
      if (!HIDDEN_SESSION_IDS.size) return;
      if (!confirm(`Restore ${HIDDEN_SESSION_IDS.size} hidden chats to the Chats tab?`)) return;
      HIDDEN_SESSION_IDS.clear();
      persistHiddenSessionIds();
      renderApp();
    }

    function escapeHtml(value) {
      return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
    }

    function formatInteger(value) {
      return Math.round(Number(value || 0)).toLocaleString();
    }

    function formatCompact(value) {
      const n = Number(value || 0);
      if (Math.abs(n) >= 1000000) return `${(n / 1000000).toFixed(1)}M`;
      if (Math.abs(n) >= 1000) return `${(n / 1000).toFixed(1)}K`;
      return Math.round(n).toString();
    }

    function formatCost(value) {
      return `$${Number(value || 0).toFixed(4)}`;
    }

    function formatDuration(ms) {
      const value = Number(ms || 0);
      if (!value) return '—';
      if (value < 1000) return `${value.toFixed(0)}ms`;
      return `${(value / 1000).toFixed(2)}s`;
    }

    function formatTimestamp(ts) {
      if (!ts) return '—';
      return new Date(Number(ts)).toLocaleString();
    }

    function formatPercent(value) {
      return `${Number(value || 0).toFixed(1)}%`;
    }

    function formatSigned(value) {
      const n = Number(value || 0);
      const prefix = n > 0 ? '+' : '';
      return `${prefix}${Math.round(n).toLocaleString()}`;
    }

    function sortArrow(key) {
      if (STATE.fileSortKey !== key) return '↕';
      return STATE.fileSortDir === 'desc' ? '↓' : '↑';
    }

    function renderStatCell(label, value, className = '', hideMobile = false) {
      return `
        <div class="stat-col ${hideMobile ? 'hide-mobile' : ''}">
          <div class="label">${label}</div>
          <div class="value ${className}">${value}</div>
        </div>`;
    }

    function promptWindowLabel(breakdown) {
      if (!breakdown) return '—';
      if (breakdown.max_context_window_tokens) {
        return `${formatCompact(breakdown.prompt_tokens)} / ${formatCompact(breakdown.max_context_window_tokens)} (${formatPercent(breakdown.used_percent_of_window)})`;
      }
      return formatCompact(breakdown.prompt_tokens);
    }

    function boundaryLabel(reason) {
      const labels = {
        model_switch: 'model switch',
        context_reset: 'context reset',
        cache_reset: 'cache reset',
      };
      return labels[reason] || String(reason || '').replace(/_/g, ' ');
    }

    function overheadLabel(key) {
      const labels = {
        system_prompt: 'System Instructions',
        tool_definitions: 'Tool Definitions',
        assistant_context: 'Chat History',
        user_messages: 'User Messages',
        tools: 'Tools',
        files: 'Files',
        unattributed: 'Unattributed',
      };
      return labels[key] || String(key || '').replace(/_/g, ' ');
    }

    function overheadColor(key) {
      const colors = {
        system_prompt: '#58a6ff',
        tool_definitions: '#bc8cff',
        assistant_context: '#ff9b50',
        user_messages: '#3fb950',
        tools: '#d29922',
        files: '#39c5cf',
        unattributed: '#6f8098',
      };
      return colors[key] || '#6f8098';
    }

    function buildOverheadBreakdown(overhead, totalInput) {
      const keys = ['system_prompt', 'tool_definitions', 'assistant_context', 'user_messages', 'tools', 'files', 'unattributed'];
      const rows = keys.map((key) => ({
        key,
        label: overheadLabel(key),
        color: overheadColor(key),
        input: Number(overhead?.[key]?.input || 0),
        cost: Number(overhead?.[key]?.cost || 0),
      }));

      const normalizedTotal = Number(totalInput || 0);
      const assigned = rows.reduce((sum, row) => sum + row.input, 0);
      if (normalizedTotal > assigned) {
        const unattributed = rows.find((row) => row.key === 'unattributed');
        if (unattributed) {
          unattributed.input += (normalizedTotal - assigned);
        }
      }

      return rows.map((row) => ({
        ...row,
        pct: normalizedTotal ? (row.input / normalizedTotal) * 100 : 0,
      }));
    }

    function renderSummaryCards(summary) {
      const totals = summaryDisplayTotals(summary);
      const costLabel = isBilledMode() ? 'Billed API cost' : 'Attributed est. cost';
      const creditsLabel = isBilledMode() ? 'Billed AI credits' : 'Attributed AI credits';
      return `
        <div class="summary-grid">
          <div class="summary-card"><div class="label">Sessions</div><div class="value">${formatInteger(summary.sessionCount)}</div></div>
          <div class="summary-card"><div class="label">Chat calls</div><div class="value">${formatInteger(summary.chatCallCount)}</div></div>
          <div class="summary-card"><div class="label">Tool calls</div><div class="value">${formatInteger(summary.toolCallCount)}</div></div>
          <div class="summary-card"><div class="label">Models used</div><div class="value">${formatInteger(summary.modelCount)}</div></div>
          <div class="summary-card"><div class="label">Session segments</div><div class="value">${formatInteger(summary.segmentCount)}</div></div>
          <div class="summary-card"><div class="label">Model switches</div><div class="value">${formatInteger(summary.modelSwitchCount)}</div></div>
          <div class="summary-card"><div class="label">Context resets</div><div class="value">${formatInteger(summary.contextResetCount)}</div></div>
          <div class="summary-card"><div class="label">Total input tokens</div><div class="value input">${formatInteger(totals.input)}</div></div>
          <div class="summary-card"><div class="label">Uncached input tokens</div><div class="value uncached">${formatInteger(totals.uncached)}</div></div>
          <div class="summary-card"><div class="label">Cached-read input tokens</div><div class="value cached">${formatInteger(totals.cached)}</div></div>
          <div class="summary-card"><div class="label">Output tokens</div><div class="value output">${formatInteger(totals.output)}</div></div>
          <div class="summary-card"><div class="label">Peak prompt window</div><div class="value">${formatInteger(summary.peakPromptTokens)}</div></div>
          <div class="summary-card"><div class="label">${costLabel}</div><div class="value cost">${formatCost(totals.cost)}</div></div>
          <div class="summary-card"><div class="label">${creditsLabel}</div><div class="value credits">${(totals.cost / 0.01).toFixed(1)}</div></div>
        </div>`;
    }

    function renderHeader() {
      const summary = activeSummary();
      const totals = summaryDisplayTotals(summary);
      const modeLabel = tokenModeLabel();
      const monthLabel = formatMonthLabelFromKey(currentMonthKey());
      const periodLabel = activePeriodLabel();
      return `
        <section class="header">
          <div class="header-top">
            <div>
              <h1>📊 Copilot Chat Usage Explorer</h1>
              <div class="subtitle">This page separates <strong>prompt snapshots</strong> from <strong>billed per-call usage</strong>, and starts a new internal segment whenever the model switches or the conversation context appears to be rebuilt.</div>
              <div class="subtitle small">Generated: ${escapeHtml(APP_DATA.generatedAt)} · Period: <strong>${escapeHtml(periodLabel)}</strong> · Token mode: <strong>${escapeHtml(modeLabel)}</strong> · Cached share: ${formatPercent(cacheHitRateForBlock(totals))} · ${formatInteger(summary.segmentCount)} segments · ${formatInteger(summary.modelSwitchCount)} model switches · ${formatInteger(summary.contextResetCount)} inferred context resets</div>
              <div class="analysis-subtabs" style="margin-top:12px;margin-bottom:4px">
                <button type="button" class="subtab-button ${STATE.usagePeriod === 'monthly' ? 'active' : ''}" onclick="switchUsagePeriod('monthly')">${escapeHtml(monthLabel)}</button>
                <button type="button" class="subtab-button ${STATE.usagePeriod === 'allTime' ? 'active' : ''}" onclick="switchUsagePeriod('allTime')">All time</button>
              </div>
              <div class="analysis-subtabs" style="margin-top:8px;margin-bottom:4px">
                <button type="button" class="subtab-button ${normalizeTokenMode(STATE.tokenMode) === 'attributed' ? 'active' : ''}" onclick="switchTokenMode('attributed')">Attributed</button>
                <button type="button" class="subtab-button ${normalizeTokenMode(STATE.tokenMode) === 'billed' ? 'active' : ''}" onclick="switchTokenMode('billed')">Billed</button>
              </div>
              <div class="note small">Monthly view auto-resets when calendar month changes.</div>
            </div>
            <div style="display:flex;gap:12px;flex-direction:column;align-items:flex-end;min-width:200px">
              <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
              </div>
              <button onclick="exportToJson()" style="border:1px solid rgba(57,197,207,0.45);background:rgba(57,197,207,0.12);color:var(--teal);padding:8px 14px;border-radius:999px;cursor:pointer;font-weight:700;font-size:0.85rem;white-space:nowrap">⬇ Export JSON</button>
            </div>
          </div>
          ${renderSummaryCards(summary)}
          <div class="tabs">
            <button class="tab-button ${STATE.activeTab === 'chats' ? 'active' : ''}" onclick="switchTab('chats')">Chats</button>
            <button class="tab-button ${STATE.activeTab === 'analysis' ? 'active' : ''}" onclick="switchTab('analysis')">Analysis</button>
            <button class="tab-button ${STATE.activeTab === 'reference' ? 'active' : ''}" onclick="switchTab('reference')">Info</button>
          </div>
        </section>`;
    }

    function filteredSessions() {
      return visibleSessions().filter((session) => {
        const title = (session.title || '').toLowerCase();
        const models = (session.model_names?.length ? session.model_names : [session.model]).filter(Boolean).map((name) => String(name).toLowerCase());
        const sessionId = String(session.session_id || session.id || '').toLowerCase();
        const sourceIp = String(session.source_ip || '').toLowerCase();
        const search = STATE.search.toLowerCase();
        const searchMatch = !search || title.includes(search) || sessionId.includes(search) || sourceIp.includes(search) || models.some((name) => name.includes(search));
        const modelMatch = !STATE.model || models.includes(STATE.model.toLowerCase());
        return searchMatch && modelMatch;
      });
    }

    function pagedSessions() {
      const sessions = filteredSessions();
      const start = (STATE.page - 1) * STATE.pageSize;
      return {
        all: sessions,
        slice: sessions.slice(start, start + STATE.pageSize),
        pageCount: Math.max(1, Math.ceil(sessions.length / STATE.pageSize)),
      };
    }

    function renderSessionMeta(session) {
      const dur = session.duration_ms || 0;
      const durLabel = dur > 60000 ? `${(dur / 60000).toFixed(1)}min` : dur > 1000 ? `${(dur / 1000).toFixed(0)}s` : '\u2014';
      const modelNames = session.model_names?.length ? session.model_names.join(', ') : (session.model || 'unknown');
      const totals = sessionDisplayTotals(session);
      return `
        <div class="session-meta">
          <div class="meta-card"><div class="label">Source IP</div><div class="value">${escapeHtml(session.source_ip || 'unknown-ip')}</div></div>
          <div class="meta-card"><div class="label">Session ID</div><div class="value">${escapeHtml(session.session_id || session.id || 'unknown')}</div></div>
          <div class="meta-card"><div class="label">Primary model</div><div class="value">${escapeHtml(session.model || 'unknown')}</div></div>
          <div class="meta-card"><div class="label">Models used</div><div class="value">${escapeHtml(modelNames)}</div></div>
          <div class="meta-card"><div class="label">Duration</div><div class="value">${durLabel}</div></div>
          <div class="meta-card"><div class="label">Segments</div><div class="value">${formatInteger(session.segment_count || 0)}</div></div>
          <div class="meta-card"><div class="label">Total input</div><div class="value input">${formatInteger(totals.input)}</div></div>
          <div class="meta-card"><div class="label">Uncached input</div><div class="value uncached">${formatInteger(totals.uncached)}</div></div>
          <div class="meta-card"><div class="label">Cached-read</div><div class="value cached">${formatInteger(totals.cached)}</div></div>
          <div class="meta-card"><div class="label">Total output</div><div class="value output">${formatInteger(totals.output)}</div></div>
          <div class="meta-card"><div class="label">${isBilledMode() ? 'Billed cost' : 'Attributed est. cost'}</div><div class="value cost">${formatCost(totals.cost)}</div></div>
          <div class="meta-card"><div class="label">Cache hit rate</div><div class="value cached">${formatPercent(cacheHitRateForBlock(totals))}</div></div>
          <div class="meta-card"><div class="label">Peak prompt</div><div class="value">${formatInteger(session.peak_prompt_tokens)}</div></div>
          <div class="meta-card"><div class="label">Model switches</div><div class="value">${formatInteger(session.boundary_counts?.model_switch || 0)}</div></div>
          <div class="meta-card"><div class="label">Context resets</div><div class="value">${formatInteger(session.boundary_counts?.context_reset || 0)}</div></div>
          <div class="meta-card"><div class="label">Cache resets</div><div class="value">${formatInteger(session.boundary_counts?.cache_reset || 0)}</div></div>
        </div>`;
    }

    function renderContextBreakdown(breakdown) {
      if (!breakdown) {
        return '<div class="note">No context window breakdown available.</div>';
      }
      const segments = breakdown.categories.map((item) => {
        const colors = {
          system_instructions: '#58a6ff',
          tool_definitions: '#bc8cff',
          messages: '#ff9b50',
          tool_results: '#3fb950',
          other: '#6f8098',
        };
        return `<div title="${escapeHtml(item.label)} · ${formatInteger(item.tokens)} tokens (${formatPercent(item.percent_of_prompt)} of prompt)" style="width:${item.percent_of_prompt}%; background:${colors[item.key]}; height:100%;"></div>`;
      }).join('');
      const reserved = breakdown.reserved_percent_of_window
        ? `<div title="Reserved for response · ${formatInteger(breakdown.reserved_response_tokens)} tokens" style="width:${breakdown.reserved_percent_of_window}%; height:100%; background: repeating-linear-gradient(135deg, rgba(188,140,255,.45), rgba(188,140,255,.45) 6px, rgba(188,140,255,.18) 6px, rgba(188,140,255,.18) 12px);"></div>`
        : '';
      return `
        <div class="event-section">
          <h4>Context window estimate</h4>
          <div class="note">Prompt now: <strong>${promptWindowLabel(breakdown)}</strong> · Cached inside prompt: <strong>${formatInteger(breakdown.cached_tokens)}</strong> · Uncached prompt: <strong>${formatInteger(breakdown.uncached_tokens)}</strong></div>
          <div style="display:flex; width:100%; height:16px; overflow:hidden; border-radius:999px; margin:12px 0; background:rgba(255,255,255,.06); border:1px solid rgba(255,255,255,.08);">
            ${segments}
            ${reserved}
          </div>
          <table>
            <thead>
              <tr><th>Section</th><th class="num">Tokens</th><th class="num">% of prompt</th><th class="num">% of window</th></tr>
            </thead>
            <tbody>
              ${breakdown.categories.map((item) => `<tr><td>${escapeHtml(item.label)}</td><td class="num">${formatInteger(item.tokens)}</td><td class="num">${formatPercent(item.percent_of_prompt)}</td><td class="num">${item.percent_of_window ? formatPercent(item.percent_of_window) : '—'}</td></tr>`).join('')}
              ${breakdown.reserved_response_tokens ? `<tr><td>Reserved for response</td><td class="num">${formatInteger(breakdown.reserved_response_tokens)}</td><td class="num">—</td><td class="num">${breakdown.reserved_percent_of_window ? formatPercent(breakdown.reserved_percent_of_window) : '—'}</td></tr>` : ''}
            </tbody>
          </table>
        </div>`;
    }

    function renderEventDetailSections(event) {
      if (event.kind === 'user_message') {
        return `<div class="event-section"><h4>Full user message</h4><pre>${escapeHtml(event.content || '')}</pre></div>`;
      }

      if (event.kind === 'tool') {
        const files = event.files?.length
          ? `<div class="pill-list">${event.files.map((file) => `<span class="pill">${escapeHtml(file)}</span>`).join('')}</div>`
          : '<div class="note">No file path detected in tool arguments.</div>';
        return `
          <div class="event-body-grid">
            <div class="event-section"><h4>Files involved</h4>${files}</div>
            <div class="split-grid">
              <div class="event-section"><h4>Tool input</h4><pre>${escapeHtml(event.args_pretty || '')}</pre></div>
              <div class="event-section"><h4>Tool output</h4><pre>${escapeHtml(event.result_text || '')}</pre></div>
            </div>
          </div>`;
      }

      const emittedTools = (event.tool_calls_emitted || []).length
        ? `<div class="event-section"><h4>Tools emitted by this chat call</h4><div class="message-list">${event.tool_calls_emitted.map((tool) => `<div class="message-card"><div class="message-header"><span class="badge tool">Tool</span><strong>${escapeHtml(tool.name)}</strong></div><pre>${escapeHtml(tool.arguments || '')}</pre></div>`).join('')}</div></div>`
        : '';

      const boundarySummary = (event.boundary_reasons || []).length
        ? `<div class="event-section"><h4>Segment boundary</h4><div class="pill-list">${event.boundary_reasons.map((reason) => `<span class="badge boundary">${escapeHtml(boundaryLabel(reason))}</span>`).join('')}</div><div class="note" style="margin-top:8px">${isBilledMode() ? 'This call started a new internal segment. In billed mode we use per-call billed totals directly.' : 'This call started a new internal segment, so tool/file attribution uses the full billed input for this call instead of only the prompt-growth delta from the previous call.'}</div></div>`
        : '';

      return `
        <div class="event-body-grid">
          ${boundarySummary}
          ${renderContextBreakdown(event.context_breakdown)}
          <div class="split-grid">
            <div class="event-section"><h4>Reasoning</h4><pre>${escapeHtml(event.reasoning || '[not recorded]')}</pre></div>
            <div class="event-section"><h4>Assistant output</h4><pre>${escapeHtml(event.response_text || '[empty]')}</pre></div>
          </div>
          ${emittedTools}
        </div>`;
    }

    function renderEvent(event, session) {
      const kindBadgeClass = event.kind === 'chat' ? 'chat' : event.kind === 'tool' ? 'tool' : 'user';
      const timing = `${formatTimestamp(event.ts)} · ${formatDuration(event.duration_ms)}`;
      const modeBadge = event.kind === 'tool' ? `<span class="badge mode-${event.mode || 'other'}">${escapeHtml(event.mode || 'other')}</span>` : '';
      const genAiButton = event.kind === 'chat'
        ? `<button type="button" class="genai-button" onclick="event.stopPropagation(); openGenAiModal('${session.id}', '${event.id}')">GenAI details</button>`
        : '';
      const boundaryBadges = (event.boundary_reasons || []).map((reason) => `<span class="badge boundary">${escapeHtml(boundaryLabel(reason))}</span>`).join('');

      if (event.kind === 'chat') {
            const chatTokens = eventDisplayChatTokens(event);
        return `
          <details class="event-card">
            <summary class="event-summary-row">
              <div class="title-col">
                <div class="title-line">
                  <span class="badge ${kindBadgeClass}">chat</span>
                  <span class="title-text">${escapeHtml(event.title)}</span>
                  <span class="badge source">${escapeHtml(event.source)}</span>
                  ${boundaryBadges}
                  ${genAiButton}
                </div>
                <div class="subtext">${escapeHtml(timing)} · segment ${formatInteger(event.segment_index || 1)} · prompt snapshot + ${escapeHtml(tokenModeLabel())} call totals</div>
              </div>
              ${renderStatCell('Prompt now', formatInteger(event.prompt_tokens))}
              ${renderStatCell('Total input', formatInteger(chatTokens.input), 'input')}
              ${renderStatCell('Uncached', formatInteger(chatTokens.uncached), 'uncached')}
              ${renderStatCell('Cached-read', formatInteger(chatTokens.cached), 'cached', true)}
              ${renderStatCell('Output', formatInteger(chatTokens.output), 'output', true)}
              ${renderStatCell(isBilledMode() ? 'Billed cost' : 'Attributed est. cost', formatCost(chatTokens.cost), 'cost')}
            </summary>
            <div class="event-body">${renderEventDetailSections(event)}</div>
          </details>`;
      }

      const estimated = eventDisplayEstimatedTokens(event, session);
      return `
        <details class="event-card">
          <summary class="event-summary-row">
            <div class="title-col">
              <div class="title-line">
                <span class="badge ${kindBadgeClass}">${escapeHtml(event.kind.replace('_', ' '))}</span>
                <span class="title-text">${escapeHtml(event.title)}</span>
                <span class="badge source">${escapeHtml(event.source)}</span>
                ${modeBadge}
              </div>
              <div class="subtext">${escapeHtml(timing)} · estimated ${escapeHtml(tokenModeLabel())} impact</div>
            </div>
            ${renderStatCell('Status', escapeHtml(event.status || '—'))}
            ${renderStatCell('Duration', formatDuration(event.duration_ms))}
            ${renderStatCell('Input', '≈ ' + formatInteger(estimated.input), 'input')}
            ${renderStatCell('Output', '≈ ' + formatInteger(estimated.output), 'output')}
            ${renderStatCell('Cached', '≈ ' + formatInteger(estimated.cached), 'cached', true)}
            ${renderStatCell('Cost', formatCost(estimated.cost), 'cost')}
          </summary>
          <div class="event-body">${renderEventDetailSections(event)}</div>
        </details>`;
    }

    function renderSessionTokenBreakdown(session) {
      const overhead = sessionOverheadForMode(session);
      const totals = sessionDisplayTotals(session);
      const totalInput = Number(totals.input || 0);
      if (!totalInput) return '';

      const categories = buildOverheadBreakdown(overhead, totalInput);

      const definitions = [
        '<strong>Chat History</strong> = earlier assistant replies carried forward into later turns.',
        '<strong>Tools</strong> = tool-call payload inside chat context (tool call arguments/results, plus non-file tool metadata).',
        '<strong>Files</strong> = file-related context from read/edit tool turns (mode-aware split estimate).',
      ];

      const segments = categories
        .filter((c) => c.pct > 0)
        .map((c) => `<div title="${escapeHtml(c.label)} · ${formatInteger(c.input)} tokens (${c.pct.toFixed(1)}%)" style="width:${c.pct}%;background:${c.color};height:100%;"></div>`)
        .join('');

      return `
        <div class="event-section" style="margin-bottom:14px">
          <h4>Session token breakdown (${isBilledMode() ? 'estimated billed distribution' : 'estimated attribution'})</h4>
          <div class="note small" style="margin-bottom:8px">Where did this chat's <strong>${formatInteger(totalInput)}</strong> ${escapeHtml(tokenModeLabel())} input tokens go? This uses the same category model as the global token breakdown. Numbers can differ from a single Copilot screenshot because screenshots show one call's current prompt window, while this view aggregates usage across many calls.</div>
          <div style="display:flex;width:100%;height:16px;overflow:hidden;border-radius:999px;margin:8px 0;background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.08);">
            ${segments}
          </div>
          <table style="margin-top:8px">
            <thead><tr><th>Category</th><th class="num">Input tokens</th><th class="num">% of total</th><th class="num">Est. cost</th></tr></thead>
            <tbody>
              ${categories.map((c) => `<tr><td><span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:${c.color};margin-right:6px;vertical-align:middle"></span>${escapeHtml(c.label)}</td><td class="num">${formatInteger(c.input)}</td><td class="num">${c.pct.toFixed(1)}%</td><td class="num">${c.cost > 0 ? formatCost(c.cost) : '—'}</td></tr>`).join('')}
            </tbody>
          </table>
          <div class="note small" style="margin-top:10px">${definitions.join('<br>')}</div>
        </div>`;
    }

    function renderSession(session, sessionIndex) {
      const dur = session.duration_ms || 0;
      const durLabel = dur > 60000 ? `${(dur / 60000).toFixed(0)}m` : dur > 1000 ? `${(dur / 1000).toFixed(0)}s` : dur ? `${dur.toFixed(0)}ms` : '\u2014';
      const modelNames = (session.model_names?.length ? session.model_names : [session.model]).filter(Boolean);
      const modelBadges = modelNames.slice(0, 3).map((modelName) => `<span class="badge model">${escapeHtml(modelName)}</span>`).join('');
      const extraModels = modelNames.length > 3 ? `<span class="badge source">+${formatInteger(modelNames.length - 3)} models</span>` : '';
      const sourceBadge = `<span class="badge source">${escapeHtml(session.source_ip || 'unknown-ip')}</span>`;
      const totals = sessionDisplayTotals(session);
      return `
        <details class="session-card">
          <summary class="session-summary-row">
            <div class="title-col">
              <div class="title-line">
                ${modelBadges || `<span class="badge model">${escapeHtml(session.model || 'unknown')}</span>`}
                ${extraModels}
                ${sourceBadge}
                <span class="title-text">${escapeHtml(session.title)}</span>
              </div>
              <div class="subtext">${escapeHtml(formatTimestamp(session.timestamp))} \u00b7 ${formatInteger(session.chat_count)} calls \u00b7 ${formatInteger(session.tool_count)} tools \u00b7 ${formatInteger(session.segment_count || 0)} segments \u00b7 ${durLabel}</div>
            </div>
            ${renderStatCell('Total input', formatInteger(totals.input), 'input')}
            ${renderStatCell('Uncached', formatInteger(totals.uncached), 'uncached')}
            ${renderStatCell('Cached-read', formatInteger(totals.cached), 'cached', true)}
            ${renderStatCell('Output', formatInteger(totals.output), 'output')}
            ${renderStatCell('Segments', formatInteger(session.segment_count || 0))}
            ${renderStatCell('Cost', formatCost(totals.cost), 'cost')}
          </summary>
          <div class="session-body">
            <div style="display:flex;justify-content:flex-end;gap:8px;margin-bottom:12px;flex-wrap:wrap">
              <button type="button" onclick="event.stopPropagation();openFullChatModal('${session.id}')" style="border:1px solid rgba(88,166,255,0.45);background:rgba(88,166,255,0.14);color:var(--blue);padding:6px 12px;border-radius:999px;cursor:pointer;font-weight:700;font-size:0.82rem">📂 Show full chat</button>
              <button type="button" onclick="event.stopPropagation();openModelCompareModal('${session.id}')" style="border:1px solid rgba(188,140,255,0.45);background:rgba(188,140,255,0.12);color:var(--purple);padding:6px 12px;border-radius:999px;cursor:pointer;font-weight:700;font-size:0.82rem">⚖ Compare models</button>
              <button type="button" onclick="event.stopPropagation();exportSessionToJson('${session.id}')" style="border:1px solid rgba(57,197,207,0.45);background:rgba(57,197,207,0.12);color:var(--teal);padding:6px 12px;border-radius:999px;cursor:pointer;font-weight:700;font-size:0.82rem">⬇ Export chat JSON</button>
              <button type="button" onclick="event.stopPropagation();deleteSessionPrompt('${session.id}')" style="border:1px solid rgba(248,81,73,0.45);background:rgba(248,81,73,0.12);color:var(--red);padding:6px 12px;border-radius:999px;cursor:pointer;font-weight:700;font-size:0.82rem">🗑 Delete chat</button>
            </div>
            ${renderSessionMeta(session)}
            ${renderSessionTokenBreakdown(session)}
            <div class="note small" style="margin-top:12px;text-align:center">Per-call timeline, tool calls and GenAI details load on demand — press <strong>📂 Show full chat</strong>.</div>
          </div>
        </details>`;
    }

    function renderPagination(allCount, pageCount) {
      return `
        <div class="pagination">
          <div class="note">Showing ${allCount ? `${(STATE.page - 1) * STATE.pageSize + 1}-${Math.min(STATE.page * STATE.pageSize, allCount)}` : '0'} of ${formatInteger(allCount)} chats</div>
          <div class="pagination-controls">
            <label class="note">Per page</label>
            <select onchange="setPageSize(this.value)">
              ${[5, 10, 20, 50, 100].map((size) => `<option value="${size}" ${STATE.pageSize === size ? 'selected' : ''}>${size}</option>`).join('')}
            </select>
            <button type="button" onclick="changePage(-1)" ${STATE.page <= 1 ? 'disabled' : ''}>Prev</button>
            <span class="note">Page ${STATE.page} / ${pageCount}</span>
            <button type="button" onclick="changePage(1)" ${STATE.page >= pageCount ? 'disabled' : ''}>Next</button>
          </div>
        </div>`;
    }

    function renderChatsTab() {
      const models = [...new Set(visibleSessions().flatMap((session) => (session.model_names?.length ? session.model_names : [session.model]).filter(Boolean)))].sort();
      const pages = pagedSessions();
      const sessionsHtml = pages.slice.map((session) => renderSession(session)).join('');
      const hiddenCount = HIDDEN_SESSION_IDS.size;
      return `
        <section class="panel">
          <div class="filter-bar">
            <input type="text" id="chatSearchInput" placeholder="Search by chat title, model, session ID, or IP…" value="${escapeHtml(STATE.search)}" oninput="setSearch(this.value)">
            <select onchange="setModelFilter(this.value)">
              <option value="">All models</option>
              ${models.map((model) => `<option value="${escapeHtml(model)}" ${STATE.model === model ? 'selected' : ''}>${escapeHtml(model)}</option>`).join('')}
            </select>
            <div style="display:flex;gap:8px;flex-wrap:wrap;margin-left:auto">
              <button type="button" onclick="openChatDeleteModal()" style="border:1px solid rgba(248,81,73,0.45);background:rgba(248,81,73,0.12);color:var(--red);padding:8px 12px;border-radius:10px;cursor:pointer;font-weight:700">🗑 Delete chats</button>
              ${hiddenCount ? `<button type="button" onclick="restoreHiddenChats()" style="border:1px solid rgba(88,166,255,0.45);background:rgba(88,166,255,0.12);color:var(--blue);padding:8px 12px;border-radius:10px;cursor:pointer;font-weight:700">↩ Restore hidden (${formatInteger(hiddenCount)})</button>` : ''}
            </div>
          </div>
          <div class="legend">${isBilledMode() ? 'Each session total uses <strong>billed per-call totals</strong> directly from API usage fields.' : 'Each session total uses <strong>prompt-growth attribution</strong>: the first call in each segment is counted at full billed cost (fresh context); subsequent calls within a segment contribute only the net-new prompt delta + output. This avoids double-counting the growing conversation history across turns.'} Model switches and context resets start new segments. <code>input</code> includes cached-read tokens; uncached input is shown separately.</div>
          <div class="note small" style="margin-top:8px">Delete actions hide chats in this browser view (persisted locally) and can be reverted with <em>Restore hidden</em>. They do not erase raw debug logs.</div>
          ${renderPagination(pages.all.length, pages.pageCount)}
        </section>
        <section class="session-list">${sessionsHtml || '<div class="panel"><div class="note">No sessions match the current filter.</div></div>'}</section>`;
    }

    function renderTable(columns, rows, options = {}) {
      const rowRenderer = options.rowRenderer || ((row) => `<tr>${columns.map((column) => `<td class="${column.numeric ? 'num' : ''}">${column.render(row)}</td>`).join('')}</tr>`);
      return `
        <div class="panel">
          <table>
            <thead>
              <tr>${columns.map((column) => `<th class="${column.numeric ? 'num' : ''}">${column.header ? column.header() : escapeHtml(column.title)}</th>`).join('')}</tr>
            </thead>
            <tbody>${rows.map((row) => rowRenderer(row)).join('')}</tbody>
          </table>
        </div>`;
    }

    function analysisSubtabs() {
      const tabs = [
        ['models', 'Model usage'],
        ['tools', 'Tool impact'],
        ['files', 'File activity'],
        ['monthlyTrends', 'Monthly trends'],
        ['insights', 'Insights'],
      ];
      return `<div class="analysis-subtabs">${tabs.map(([id, label]) => `<button type="button" class="subtab-button ${STATE.analysisTab === id ? 'active' : ''}" onclick="switchAnalysisTab('${id}')">${escapeHtml(label)}</button>`).join('')}</div>`;
    }

    function renderModelsSubtab() {
      const analysis = analysisForMode();
      return `
        <section class="panel">
          <h2 class="section-title">Model usage</h2>
          <div class="section-subtitle">These totals use <strong>${isBilledMode() ? 'billed per-call totals' : 'prompt-growth attribution'}</strong>. If a session switches models, each call is counted under the model that served it.</div>
          ${renderTable([
            { title: 'Model', render: (row) => `<div><strong>${escapeHtml(row.name)}</strong><div class="note small">${formatInteger(row.count)} chat calls across ${formatInteger(row.sessionCount)} sessions</div></div>` },
            { title: 'Total input', numeric: true, render: (row) => `<span class="value input">${formatInteger(row.input)}</span>` },
            { title: 'Uncached input', numeric: true, render: (row) => `<span class="value uncached">${formatInteger(row.uncached)}</span>` },
            { title: 'Cached-read input', numeric: true, render: (row) => `<span class="value cached">${formatInteger(row.cached)}</span>` },
            { title: 'Output', numeric: true, render: (row) => `<span class="value output">${formatInteger(row.output)}</span>` },
            { title: 'Cached share', numeric: true, render: (row) => formatPercent(row.cacheHitRate) },
            { title: 'Avg TTFT', numeric: true, render: (row) => formatDuration(row.avgTtftMs) },
            { title: 'Cost', numeric: true, render: (row) => `<span class="value cost">${formatCost(row.cost)}</span>` },
          ], analysis.models || [])}
        </section>`;
    }

    function renderToolImpactSubtabs() {
      const tabs = [
        ['usage', isBilledMode() ? 'Usage (billed est.)' : 'Usage attribution'],
        ['waste', 'Unused tool waste'],
      ];
      return `<div class="analysis-subtabs" style="margin-top:10px">${tabs.map(([id, label]) => `<button type="button" class="subtab-button ${STATE.toolImpactTab === id ? 'active' : ''}" onclick="switchToolImpactTab('${id}')">${escapeHtml(label)}</button>`).join('')}</div>`;
    }

    function sortRows(rows, sortKey, sortDir) {
      const dir = sortDir === 'desc' ? -1 : 1;
      rows.sort((a, b) => {
        const av = a[sortKey]; const bv = b[sortKey];
        if (typeof av === 'string' || typeof bv === 'string') return String(av || '').localeCompare(String(bv || '')) * dir;
        return (Number(av || 0) - Number(bv || 0)) * dir;
      });
      return rows;
    }

    function renderToolsUsageSubtab() {
      const analysis = analysisForMode();
      const search = (STATE.toolImpactSearch || '').trim().toLowerCase();
      const filteredTools = [...(analysis.tools || [])].filter((row) => {
        if (!search) return true;
        return String(row.name || '').toLowerCase().includes(search) || String(row.mode || '').toLowerCase().includes(search);
      });
      const tools = sortRows(filteredTools, STATE.toolSortKey || 'cost', STATE.toolSortDir || 'desc');
      function toolSortArrow(key) {
        if ((STATE.toolSortKey || 'cost') !== key) return '<span style="opacity:.4">\u2195</span>';
        return (STATE.toolSortDir || 'desc') === 'desc' ? '\u2193' : '\u2191';
      }
      function thBtn(key, line1, line2) {
        return `<th class="num"><button type="button" onclick="setToolSort('${key}')" style="all:unset;cursor:pointer;color:inherit;text-align:right;display:block;width:100%"><span style="display:block;line-height:1.2;font-size:.72rem">${line1}</span><span style="display:block;line-height:1.2;font-size:.72rem">${line2} ${toolSortArrow(key)}</span></button></th>`;
      }
      const totals = { count: 0, errors: 0, durationMs: 0, input: 0, output: 0, cached: 0, cost: 0, payloadTokens: 0 };
      tools.forEach(t => { totals.count += t.count; totals.errors += t.errors; totals.durationMs += t.durationMs; totals.input += t.input; totals.output += t.output; totals.cached += t.cached; totals.cost += t.cost; totals.payloadTokens += t.payloadTokens; });
      return `
          <div class="section-subtitle">${isBilledMode() ? '<strong>Payload</strong> = approx token size of tool input + output text. In billed mode, tool/file splits are billed-adjusted estimates derived from attribution shares.' : '<strong>Payload</strong> = approx token size of tool input + output text, used as weight when splitting prompt growth.'}</div>
          <div style="overflow-x:auto">
          <table>
            <thead><tr>
              <th><button type="button" onclick="setToolSort('name')" style="all:unset;cursor:pointer;color:inherit">Tool ${toolSortArrow('name')}</button></th>
              ${thBtn('count', 'Calls', '')}
              ${thBtn('avgDurationMs', 'Avg', 'Duration')}
              ${thBtn('avgInput', 'Avg', 'Input')}
              ${thBtn('avgOutput', 'Avg', 'Output')}
              ${thBtn('avgCached', 'Avg', 'Cached')}
              ${thBtn('avgCost', 'Avg', 'Cost')}
              ${thBtn('input', 'Total', 'Input')}
              ${thBtn('output', 'Total', 'Output')}
              ${thBtn('cached', 'Total', 'Cached')}
              ${thBtn('cost', 'Total', 'Cost')}
              ${thBtn('avgPayloadTokens', 'Avg', 'Payload')}
            </tr></thead>
            <tbody>
              ${tools.length ? tools.map(row => `<tr>
                <td><div><strong>${escapeHtml(row.name)}</strong><div class="pill-list"><span class="pill">${escapeHtml(row.mode)}</span><span class="pill">${formatInteger(row.errors)} err</span></div></div></td>
                <td class="num">${formatInteger(row.count)}</td>
                <td class="num">${formatDuration(row.avgDurationMs)}</td>
                <td class="num"><span class="value input">${formatInteger(row.avgInput)}</span></td>
                <td class="num"><span class="value output">${formatInteger(row.avgOutput)}</span></td>
                <td class="num"><span class="value cached">${formatInteger(row.avgCached)}</span></td>
                <td class="num"><span class="value cost">${formatCost(row.avgCost)}</span></td>
                <td class="num"><span class="value input">${formatCompact(row.input)}</span></td>
                <td class="num"><span class="value output">${formatCompact(row.output)}</span></td>
                <td class="num"><span class="value cached">${formatCompact(row.cached)}</span></td>
                <td class="num"><span class="value cost">${formatCost(row.cost)}</span></td>
                <td class="num">${formatInteger(row.avgPayloadTokens)}</td>
              </tr>`).join('') : `<tr><td colspan="12" class="note">No tools matched your search.</td></tr>`}
              <tr style="border-top:2px solid var(--border);font-weight:700">
                <td>TOTAL</td>
                <td class="num">${formatInteger(totals.count)}</td>
                <td class="num">${formatDuration(totals.durationMs / (totals.count || 1))}</td>
                <td class="num"><span class="value input">${formatInteger(totals.input / (totals.count || 1))}</span></td>
                <td class="num"><span class="value output">${formatInteger(totals.output / (totals.count || 1))}</span></td>
                <td class="num"><span class="value cached">${formatInteger(totals.cached / (totals.count || 1))}</span></td>
                <td class="num"><span class="value cost">${formatCost(totals.cost / (totals.count || 1))}</span></td>
                <td class="num"><span class="value input">${formatCompact(totals.input)}</span></td>
                <td class="num"><span class="value output">${formatCompact(totals.output)}</span></td>
                <td class="num"><span class="value cached">${formatCompact(totals.cached)}</span></td>
                <td class="num"><span class="value cost">${formatCost(totals.cost)}</span></td>
                <td class="num">${formatInteger(totals.payloadTokens / (totals.count || 1))}</td>
              </tr>
            </tbody>
          </table>
          </div>`;
    }

    function renderToolWasteSubtab() {
      const analysis = analysisForMode();
      const search = (STATE.toolImpactSearch || '').trim().toLowerCase();
      const filteredRows = [...(analysis.toolCatalog || [])].filter((row) => {
        if (!search) return true;
        return String(row.name || '').toLowerCase().includes(search) || String(row.description || '').toLowerCase().includes(search);
      });
      const rows = sortRows(filteredRows, STATE.toolWasteSortKey || 'wastedInputTokens', STATE.toolWasteSortDir || 'desc');
      function arrow(key) {
        if ((STATE.toolWasteSortKey || 'wastedInputTokens') !== key) return '<span style="opacity:.4">\u2195</span>';
        return (STATE.toolWasteSortDir || 'desc') === 'desc' ? '\u2193' : '\u2191';
      }
      function th(key, label, numeric) {
        return `<th class="${numeric ? 'num' : ''}"><button type="button" onclick="setToolWasteSort('${key}')" style="all:unset;cursor:pointer;color:inherit;display:block;width:100%;text-align:${numeric ? 'right' : 'left'}">${label} ${arrow(key)}</button></th>`;
      }
      const totals = rows.reduce((acc, row) => {
        acc.present += Number(row.presentCount || 0);
        acc.unused += Number(row.unusedPresentCount || 0);
        acc.wastedInput += Number(row.wastedInputTokens || 0);
        acc.wastedUncached += Number(row.wastedUncachedTokens || 0);
        acc.wastedCached += Number(row.wastedCachedTokens || 0);
        return acc;
      }, { present: 0, unused: 0, wastedInput: 0, wastedUncached: 0, wastedCached: 0 });
      const totalWastePercent = totals.present ? (totals.unused / totals.present * 100) : 0;
      return `
        <div class="section-subtitle"><strong>Waste</strong> estimates the description tokens for a tool each time that tool was present in the model toolset but was not called by that LLM response. Cached/uncached split is estimated from that call's observed cache-read ratio.${isBilledMode() ? ' In billed mode, these totals are billed-adjusted estimates.' : ''}</div>
        <div style="overflow-x:auto">
        <table>
          <thead><tr>
            ${th('name', 'Tool', false)}
            ${th('descriptionTokens', 'Description tokens', true)}
            ${th('presentCount', 'Present in calls', true)}
            ${th('callCount', 'Actual calls', true)}
            ${th('unusedPresentCount', 'Unused passes', true)}
            ${th('wastePercent', 'Waste %', true)}
            ${th('wastedInputTokens', 'Waste total input', true)}
            ${th('wastedUncachedTokens', 'Waste uncached input', true)}
            ${th('wastedCachedTokens', 'Waste cached-read input', true)}
            ${th('sessionCount', 'Sessions', true)}
            ${th('toolSetCount', 'Tool sets', true)}
          </tr></thead>
          <tbody>
            ${rows.length ? rows.map(row => `<tr>
              <td><details><summary><strong>${escapeHtml(row.name)}</strong></summary><pre>${escapeHtml(row.description || '[No description captured for this tool.]')}</pre></details></td>
              <td class="num">${formatInteger(row.descriptionTokens || 0)}</td>
              <td class="num">${formatInteger(row.presentCount || 0)}</td>
              <td class="num">${formatInteger(row.callCount || 0)}</td>
              <td class="num">${formatInteger(row.unusedPresentCount || 0)}</td>
              <td class="num">${formatPercent(row.wastePercent || 0)}</td>
              <td class="num"><span class="value input">${formatCompact(row.wastedInputTokens || 0)}</span></td>
              <td class="num"><span class="value uncached">${formatCompact(row.wastedUncachedTokens || 0)}</span></td>
              <td class="num"><span class="value cached">${formatCompact(row.wastedCachedTokens || 0)}</span></td>
              <td class="num">${formatInteger(row.sessionCount || 0)}</td>
              <td class="num">${formatInteger(row.toolSetCount || 0)}</td>
            </tr>`).join('') : `<tr><td colspan="11" class="note">No tools matched your search.</td></tr>`}
            <tr style="border-top:2px solid var(--border);font-weight:700">
              <td>TOTAL</td>
              <td class="num"></td>
              <td class="num">${formatInteger(totals.present)}</td>
              <td class="num"></td>
              <td class="num">${formatInteger(totals.unused)}</td>
              <td class="num">${formatPercent(totalWastePercent)}</td>
              <td class="num"><span class="value input">${formatCompact(totals.wastedInput)}</span></td>
              <td class="num"><span class="value uncached">${formatCompact(totals.wastedUncached)}</span></td>
              <td class="num"><span class="value cached">${formatCompact(totals.wastedCached)}</span></td>
              <td class="num"></td>
              <td class="num"></td>
            </tr>
          </tbody>
        </table>
        </div>`;
    }

    function renderToolsSubtab() {
      return `
        <section class="panel">
          <h2 class="section-title">Tool impact</h2>
          <div class="tool-catalog-controls">
            <input type="text" id="toolImpactSearchInput" placeholder="Search tools by name/mode/description…" value="${escapeHtml(STATE.toolImpactSearch)}" oninput="setToolImpactSearch(this.value)">
          </div>
          ${renderToolImpactSubtabs()}
          ${STATE.toolImpactTab === 'waste' ? renderToolWasteSubtab() : renderToolsUsageSubtab()}
        </section>`;
    }

    function sortFiles(sourceRows) {
      const rows = [...(sourceRows || [])];
      rows.sort((a, b) => {
        const key = STATE.fileSortKey;
        const dir = STATE.fileSortDir === 'desc' ? -1 : 1;
        const av = a[key];
        const bv = b[key];
        if (typeof av === 'string' || typeof bv === 'string') {
          return String(av).localeCompare(String(bv)) * dir;
        }
        return ((Number(av || 0) - Number(bv || 0)) * dir);
      });
      return rows;
    }

    function shortenPath(path, maxLen) {
      maxLen = maxLen || 50;
      if (!path || path.length <= maxLen) return escapeHtml(path || '');
      const parts = path.split('/');
      if (parts.length <= 3) return escapeHtml(path.slice(0, maxLen/2) + '\u2026' + path.slice(-(maxLen/2)));
      const head = parts.slice(0, 2).join('/');
      const tail = parts.slice(-2).join('/');
      return escapeHtml(head + '/\u2026/' + tail);
    }

    function renderFilesSubtab() {
      const analysis = analysisForMode();
      const search = (STATE.fileSearch || '').trim().toLowerCase();
      const filtered = [...(analysis.files || [])].filter((row) => {
        if (!search) return true;
        const tools = (row.tools || []).join(' ').toLowerCase();
        return String(row.name || '').toLowerCase().includes(search)
          || String(row.path || '').toLowerCase().includes(search)
          || String(row.shortPath || '').toLowerCase().includes(search)
          || tools.includes(search);
      });
      const rows = sortFiles(filtered);
      const columns = [
        ['name', 'File'],
        ['readCount', 'Reads'],
        ['editCount', 'Edits'],
        ['avgInput', 'Avg Input'],
        ['avgOutput', 'Avg Output'],
        ['avgCached', 'Avg Cached'],
        ['input', 'Total Input'],
        ['output', 'Total Output'],
        ['cached', 'Total Cached'],
        ['payloadTokens', 'Payload'],
        ['avgCost', 'Avg Cost'],
        ['cost', 'Cost'],
      ];
      const fileTotals = { readCount: 0, editCount: 0, input: 0, output: 0, cached: 0, cost: 0, payloadTokens: 0 };
      rows.forEach(r => { fileTotals.readCount += r.readCount; fileTotals.editCount += r.editCount; fileTotals.input += r.input; fileTotals.output += r.output; fileTotals.cached += r.cached; fileTotals.cost += r.cost; fileTotals.payloadTokens += r.payloadTokens; });
      const totalOps = fileTotals.readCount + fileTotals.editCount;
      return `
        <section class="panel">
          <h2 class="section-title">File activity</h2>
          <div class="section-subtitle">Click a file to see per-tool usage summary. ${isBilledMode() ? 'Values are billed-adjusted estimates based on observed attribution shares.' : 'Long paths shortened; hover for full path.'}</div>
          <div class="tool-catalog-controls">
            <input type="text" id="fileSearchInput" placeholder="Search files by name/path/tool…" value="${escapeHtml(STATE.fileSearch)}" oninput="setFileSearch(this.value)">
          </div>
          <div style="overflow-x:auto">
          <table>
            <thead>
              <tr>
                ${columns.map(([key, label]) => `<th class="${key !== 'name' ? 'num' : ''}"><button type="button" onclick="setFileSort('${key}')" style="all:unset;cursor:pointer;color:inherit">${escapeHtml(label)} ${sortArrow(key)}</button></th>`).join('')}
              </tr>
            </thead>
            <tbody>
              ${rows.map((row) => `<tr class="clickable-row" onclick="openFileModal('${encodeURIComponent(row.path)}')">
                <td><div title="${escapeHtml(row.path)}"><strong>${escapeHtml(row.name)}</strong></div></td>
                <td class="num">${formatInteger(row.readCount)}</td>
                <td class="num">${formatInteger(row.editCount)}</td>
                <td class="num"><span class="value input">${formatInteger(row.avgInput)}</span></td>
                <td class="num"><span class="value output">${formatInteger(row.avgOutput)}</span></td>
                <td class="num"><span class="value cached">${formatInteger(row.avgCached)}</span></td>
                <td class="num"><span class="value input">${formatCompact(row.input)}</span></td>
                <td class="num"><span class="value output">${formatCompact(row.output)}</span></td>
                <td class="num"><span class="value cached">${formatCompact(row.cached)}</span></td>
                <td class="num">${formatInteger(row.payloadTokens)}</td>
                <td class="num"><span class="value cost">${formatCost(row.avgCost)}</span></td>
                <td class="num"><span class="value cost">${formatCost(row.cost)}</span></td>
              </tr>`).join('')}
              <tr style="border-top:2px solid var(--border);font-weight:700">
                <td>TOTAL (${rows.length} files)</td>
                <td class="num">${formatInteger(fileTotals.readCount)}</td>
                <td class="num">${formatInteger(fileTotals.editCount)}</td>
                <td class="num"><span class="value input">${formatInteger(totalOps ? fileTotals.input / totalOps : 0)}</span></td>
                <td class="num"><span class="value output">${formatInteger(totalOps ? fileTotals.output / totalOps : 0)}</span></td>
                <td class="num"><span class="value cached">${formatInteger(totalOps ? fileTotals.cached / totalOps : 0)}</span></td>
                <td class="num"><span class="value input">${formatCompact(fileTotals.input)}</span></td>
                <td class="num"><span class="value output">${formatCompact(fileTotals.output)}</span></td>
                <td class="num"><span class="value cached">${formatCompact(fileTotals.cached)}</span></td>
                <td class="num">${formatInteger(fileTotals.payloadTokens)}</td>
                <td class="num"><span class="value cost">${formatCost(totalOps ? fileTotals.cost / totalOps : 0)}</span></td>
                <td class="num"><span class="value cost">${formatCost(fileTotals.cost)}</span></td>
              </tr>
            </tbody>
          </table>
          </div>
        </section>`;
    }

    function monthlyTrendMetricConfig() {
      return {
        cost: {
          label: 'Cost',
          short: 'Cost',
          color: '#39c5cf',
          value: (row) => Number(row?.totals?.cost || 0),
          format: (value) => formatCost(value),
        },
        input: {
          label: 'Input tokens',
          short: 'Input',
          color: '#58a6ff',
          value: (row) => Number(row?.totals?.input || 0),
          format: (value) => formatInteger(value),
        },
        uncached: {
          label: 'Uncached input',
          short: 'Uncached',
          color: '#d29922',
          value: (row) => Number(row?.totals?.uncached || 0),
          format: (value) => formatInteger(value),
        },
        cached: {
          label: 'Cached input',
          short: 'Cached',
          color: '#3fb950',
          value: (row) => Number(row?.totals?.cached || 0),
          format: (value) => formatInteger(value),
        },
        output: {
          label: 'Output tokens',
          short: 'Output',
          color: '#ff9b50',
          value: (row) => Number(row?.totals?.output || 0),
          format: (value) => formatInteger(value),
        },
        sessions: {
          label: 'Sessions',
          short: 'Sessions',
          color: '#bc8cff',
          value: (row) => Number(row?.sessionCount || 0),
          format: (value) => formatInteger(value),
        },
        chatCalls: {
          label: 'Chat calls',
          short: 'Chat calls',
          color: '#58a6ff',
          value: (row) => Number(row?.chatCallCount || 0),
          format: (value) => formatInteger(value),
        },
        toolCalls: {
          label: 'Tool calls',
          short: 'Tool calls',
          color: '#d29922',
          value: (row) => Number(row?.toolCallCount || 0),
          format: (value) => formatInteger(value),
        },
        cacheHitRate: {
          label: 'Cache hit rate',
          short: 'Cache hit %',
          color: '#3fb950',
          value: (row) => Number(row?.cacheHitRate || 0),
          format: (value) => formatPercent(value),
          isRate: true,
        },
      };
    }

    function renderMonthlyTrendChart(rows, metricKey) {
      const metrics = monthlyTrendMetricConfig();
      const metric = metrics[metricKey] || metrics.cost;
      const values = rows.map((row) => Number(metric.value(row) || 0));
      const maxValue = Math.max(...values, 1);

      const width = Math.max(720, rows.length * 104);
      const height = 320;
      const padLeft = 72;
      const padRight = 20;
      const padTop = 16;
      const padBottom = 54;
      const innerWidth = width - padLeft - padRight;
      const innerHeight = height - padTop - padBottom;
      const step = Math.max(1, innerWidth / Math.max(rows.length, 1));
      const barWidth = Math.max(10, Math.min(48, step * 0.5));

      const gridLines = [0, 0.25, 0.5, 0.75, 1].map((ratio) => {
        const y = padTop + innerHeight - (innerHeight * ratio);
        const label = metric.format(maxValue * ratio);
        return `
          <line x1="${padLeft}" y1="${y}" x2="${width - padRight}" y2="${y}"  stroke="rgba(255,255,255,0.08)" />
          <text x="${padLeft - 8}" y="${y + 4}" fill="var(--muted)" font-size="12" text-anchor="end">${escapeHtml(label)}</text>`;
      }).join('');

      const bars = rows.map((row, index) => {
        const value = Number(metric.value(row) || 0);
        const x = padLeft + step * index + step / 2;
        const barHeight = (value / maxValue) * innerHeight;
        const y = padTop + innerHeight - barHeight;
        const month = row.monthKey || row.label || `M${index + 1}`;
        const tooltip = `${row.label || month}\n${metric.label}: ${metric.format(value)}\nSessions: ${formatInteger(row.sessionCount || 0)} · Chats: ${formatInteger(row.chatCallCount || 0)} · Tools: ${formatInteger(row.toolCallCount || 0)}`;
        return `
          <rect x="${x - barWidth / 2}" y="${y}" width="${barWidth}" height="${Math.max(1, barHeight)}" rx="6" fill="${metric.color}" opacity="0.82"><title>${escapeHtml(tooltip)}</title></rect>
          <text x="${x}" y="${height - 16}" fill="var(--muted)" font-size="12" text-anchor="middle">${escapeHtml(month)}</text>`;
      }).join('');

      return `
        <div class="chart-card">
          <svg class="chart-svg" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none">
            ${gridLines}
            <line x1="${padLeft}" y1="${padTop + innerHeight}" x2="${width - padRight}" y2="${padTop + innerHeight}" stroke="rgba(255,255,255,0.2)" />
            ${bars}
          </svg>
          <div class="chart-legend">
            <span class="legend-item"><span class="legend-swatch" style="background:${metric.color}"></span>${escapeHtml(metric.label)}</span>
            <span class="legend-item">Bars are month totals (hover bars for details).</span>
          </div>
        </div>`;
    }

    function renderMonthlyTrendsSubtab() {
      const analysis = analysisForMode();
      const rows = [...(analysis.monthlyTrends || [])].sort((a, b) => String(a.monthKey || '').localeCompare(String(b.monthKey || '')));
      if (!rows.length) {
        return `<section class="panel"><h2 class="section-title">Monthly trends</h2><div class="note">No monthly data found yet.</div></section>`;
      }

      const metricConfig = monthlyTrendMetricConfig();
      const metricKey = metricConfig[STATE.monthlyTrendMetric] ? STATE.monthlyTrendMetric : 'cost';
      const metric = metricConfig[metricKey];
      const latest = rows[rows.length - 1];
      const previous = rows.length > 1 ? rows[rows.length - 2] : null;
      const latestValue = Number(metric.value(latest) || 0);
      const previousValue = Number(previous ? metric.value(previous) : 0);
      const delta = latestValue - previousValue;
      const deltaPercent = previous ? (previousValue ? (delta / previousValue) * 100 : null) : null;
      const deltaSign = delta > 0 ? '+' : '';
      const comparisonValue = previous ? escapeHtml(metric.format(previousValue)) : '';
      const deltaLabel = metric.isRate
        ? `${delta > 0 ? '+' : ''}${delta.toFixed(1)} pp`
        : `${deltaSign}${escapeHtml(metric.format(Math.abs(delta)))}${deltaPercent === null ? '' : `, ${deltaPercent > 0 ? '+' : ''}${deltaPercent.toFixed(1)}%`}`;

      return `
        <section class="panel">
          <h2 class="section-title">Monthly trends</h2>
          <div class="section-subtitle">Track month-over-month progress across usage, cost, and efficiency patterns (${escapeHtml(tokenModeLabel())} mode).</div>
          <div class="analysis-subtabs">
            ${Object.entries(metricConfig).map(([key, cfg]) => `<button type="button" class="subtab-button ${metricKey === key ? 'active' : ''}" onclick="switchMonthlyTrendMetric('${key}')">${escapeHtml(cfg.short)}</button>`).join('')}
          </div>
          <div class="note" style="margin-bottom:10px">
            Latest (${escapeHtml(latest.label || latest.monthKey || 'current month')}): <strong>${escapeHtml(metric.format(latestValue))}</strong>
            ${previous ? ` · vs ${escapeHtml(previous.label || previous.monthKey || 'previous month')}: <strong style="color:${delta < 0 ? 'var(--green)' : delta > 0 ? 'var(--red)' : 'var(--muted)'}">${comparisonValue}</strong>${deltaLabel ? ` (${deltaLabel})` : ''}` : ''}
          </div>
          ${renderMonthlyTrendChart(rows, metricKey)}
          <div style="overflow-x:auto;margin-top:12px">
            <table>
              <thead>
                <tr>
                  <th>Month</th>
                  <th class="num">Sessions</th>
                  <th class="num">Chat calls</th>
                  <th class="num">Tool calls</th>
                  <th class="num">Input</th>
                  <th class="num">Uncached</th>
                  <th class="num">Cached</th>
                  <th class="num">Output</th>
                  <th class="num">Cost</th>
                  <th class="num">Cache hit</th>
                </tr>
              </thead>
              <tbody>
                ${rows.map((row) => `<tr>
                  <td>${escapeHtml(row.label || row.monthKey || '—')}</td>
                  <td class="num">${formatInteger(row.sessionCount || 0)}</td>
                  <td class="num">${formatInteger(row.chatCallCount || 0)}</td>
                  <td class="num">${formatInteger(row.toolCallCount || 0)}</td>
                  <td class="num"><span class="value input">${formatCompact(row.totals?.input || 0)}</span></td>
                  <td class="num"><span class="value uncached">${formatCompact(row.totals?.uncached || 0)}</span></td>
                  <td class="num"><span class="value cached">${formatCompact(row.totals?.cached || 0)}</span></td>
                  <td class="num"><span class="value output">${formatCompact(row.totals?.output || 0)}</span></td>
                  <td class="num"><span class="value cost">${formatCost(row.totals?.cost || 0)}</span></td>
                  <td class="num">${formatPercent(row.cacheHitRate || 0)}</td>
                </tr>`).join('')}
              </tbody>
            </table>
          </div>
        </section>`;
    }

    function renderGlobalTokenPieChart(summary, analysis) {
      const totals = summaryDisplayTotals(summary);
      const totalInput = Number(totals.input || 0);
      if (!totalInput) return '<div class="note">No token data available.</div>';

      const overhead = analysis.overhead || {};
      const categories = buildOverheadBreakdown(overhead, totalInput);
      const cats = categories.filter((c) => c.input > 0);

      // SVG pie chart
      const cx = 110, cy = 110, r = 90;
      let startAngle = -Math.PI / 2;
      const slices = cats.map((cat) => {
        const pct = cat.input / totalInput;
        const angle = pct * 2 * Math.PI;
        const x1 = cx + r * Math.cos(startAngle);
        const y1 = cy + r * Math.sin(startAngle);
        const endAngle = startAngle + angle;
        const x2 = cx + r * Math.cos(endAngle);
        const y2 = cy + r * Math.sin(endAngle);
        const largeArc = angle > Math.PI ? 1 : 0;
        const d = `M ${cx} ${cy} L ${x1.toFixed(2)} ${y1.toFixed(2)} A ${r} ${r} 0 ${largeArc} 1 ${x2.toFixed(2)} ${y2.toFixed(2)} Z`;
        const label = `${cat.label}: ${formatInteger(cat.input)} tokens (${(pct * 100).toFixed(1)}%)`;
        startAngle = endAngle;
        return `<path d="${d}" fill="${cat.color}" opacity="0.85"><title>${label}</title></path>`;
      }).join('');

      const legend = categories.map((cat) => {
        return `
          <tr>
            <td><span style="display:inline-block;width:12px;height:12px;border-radius:50%;background:${cat.color};margin-right:8px;vertical-align:middle"></span>${escapeHtml(cat.label)}</td>
            <td class="num">${formatInteger(cat.input)}</td>
            <td class="num">${cat.pct.toFixed(1)}%</td>
            <td class="num">${cat.cost > 0 ? formatCost(cat.cost) : '—'}</td>
          </tr>`;
      }).join('');

      return `
        <div style="display:grid;grid-template-columns:220px 1fr;gap:24px;align-items:start">
          <div>
            <svg viewBox="0 0 220 220" width="220" height="220" style="display:block">
              ${slices}
              <circle cx="${cx}" cy="${cy}" r="38" fill="var(--panel-2)"/>
              <text x="${cx}" y="${cy - 6}" text-anchor="middle" fill="var(--muted)" font-size="11" font-family="inherit">Total input</text>
              <text x="${cx}" y="${cy + 10}" text-anchor="middle" fill="var(--text)" font-size="12" font-weight="700" font-family="inherit">${formatCompact(totalInput)}</text>
            </svg>
          </div>
          <div>
            <div class="note small" style="margin-bottom:10px">Cross-chat global breakdown of all <strong>${formatInteger(totalInput)}</strong> ${escapeHtml(tokenModeLabel())} input tokens. Shows what your prompts are actually made of across all sessions. This will not exactly match a single in-chat screenshot, which represents one request's prompt snapshot (window usage), not multi-call aggregated totals.</div>
            <table>
              <thead><tr><th>Category</th><th class="num">Input tokens</th><th class="num">% of total</th><th class="num">Est. cost</th></tr></thead>
              <tbody>${legend}</tbody>
            </table>
            <div class="note small" style="margin-top:10px">
              <strong>Chat History</strong> = earlier assistant replies carried into later turns.<br>
              <strong>Tools</strong> = tool-call payload in context (arguments/results + non-file tool metadata).<br>
              <strong>Files</strong> = file-related context from read/edit tool turns (mode-aware split estimate).
            </div>
          </div>
        </div>`;
    }

    function renderInsightsSubtab() {
      const summary = activeSummary();
      const analysis = analysisForMode();
      const summaryTotals = summaryDisplayTotals(summary);
      const overheadCards = Object.entries(analysis.overhead || {}).map(([name, block]) => `
        <div class="insight-card">
          <h4>${escapeHtml(overheadLabel(name))}</h4>
          <div class="note small">Estimated ${escapeHtml(tokenModeLabel())} bucket</div>
          <div class="pill-list" style="margin-top:10px;">
            <span class="pill">Input ${formatInteger(block.input)}</span>
            <span class="pill">Output ${formatInteger(block.output)}</span>
            <span class="pill">Cached ${formatInteger(block.cached)}</span>
            <span class="pill">Cost ${formatCost(block.cost)}</span>
          </div>
        </div>`).join('');
      const expensiveChats = (analysis.topChats || []).slice(0, 6).map((chat) => `
        <div class="insight-card">
          <h4 title="${escapeHtml(chat.title)}">${escapeHtml(chat.title.length > 60 ? chat.title.slice(0,57) + '...' : chat.title)}</h4>
          <div class="note small">${escapeHtml((chat.sessionTitle||'').slice(0,40))} \u00b7 ${escapeHtml(formatTimestamp(chat.timestamp))}</div>
          <div class="pill-list" style="margin-top:10px;">
            <span class="pill">${escapeHtml(chat.model)}</span>
            <span class="pill">Prompt ${formatInteger(chat.promptTokens)}</span>
            <span class="pill">Cached ${formatInteger(chat.cached)}</span>
            <span class="pill">Cost ${formatCost(chat.cost)}</span>
          </div>
        </div>`).join('');
      const slowestTools = (analysis.slowestTools || []).slice(0, 6).map((tool) => `
        <div class="insight-card">
          <h4 title="${escapeHtml(tool.title)}">${escapeHtml(tool.title.length > 55 ? tool.title.slice(0,52) + '...' : tool.title)}</h4>
          <div class="note small">${escapeHtml((tool.sessionTitle||'').slice(0,40))} \u00b7 ${escapeHtml(formatTimestamp(tool.timestamp))}</div>
          <div class="pill-list" style="margin-top:10px;">
            <span class="pill">${escapeHtml(tool.name)}</span>
            <span class="pill">${formatDuration(tool.durationMs)}</span>
            <span class="pill">Input ${formatInteger(tool.estimated.input)}</span>
            <span class="pill">${formatCost(tool.estimated.cost)}</span>
          </div>
        </div>`).join('');

      function collapsible(title, innerHtml, startOpen) {
        const openAttr = startOpen ? ' open' : '';
        return `<details class="panel collapsible-section" style="cursor:default"${openAttr}>
          <summary style="cursor:pointer;display:flex;align-items:center;gap:8px;user-select:none;padding:14px 18px">
            <span style="font-size:1.2rem;font-weight:700;width:22px;text-align:center;font-family:monospace" class="collapse-icon">${startOpen ? '\u2212' : '+'}</span>
            <h2 class="section-title" style="margin:0">${title}</h2>
          </summary>
          <div style="padding:0 18px 18px">${innerHtml}</div>
        </details>`;
      }

      return `
        <div class="analysis-grid">
          ${collapsible('Interesting breakdowns', `
            <div class="insights-grid">
              <div class="insight-card">
                <h4>Top-level summary</h4>
                <ul class="help-list">
                  <li>${formatInteger(summary.sessionCount)} sessions</li>
                  <li>${formatInteger(summary.chatCallCount)} chat calls</li>
                  <li>${formatInteger(summary.toolCallCount)} tool calls</li>
                  <li>${formatInteger(summary.modelCount)} distinct models across ${formatInteger(summary.segmentCount)} inferred segments</li>
                  <li>${formatInteger(summary.modelSwitchCount)} model switches and ${formatInteger(summary.contextResetCount)} inferred context resets</li>
                  <li>${formatPercent(cacheHitRateForBlock(summaryTotals))} cached-read share of ${escapeHtml(tokenModeLabel())} input</li>
                  <li>${formatCost(summaryTotals.cost)} total ${escapeHtml(tokenModeLabel())} spend</li>
                </ul>
              </div>
              ${overheadCards}
            </div>`, false)}
          ${collapsible('Expensive chats', `<div class="insights-grid">${expensiveChats}</div>`, false)}
          ${collapsible('Slowest tools', `<div class="insights-grid">${slowestTools}</div>`, false)}
          ${collapsible('Global token breakdown', renderGlobalTokenPieChart(summary, analysis), true)}
        </div>`;
    }

    function dataSubtabs() {
      const tabs = [
        ['prices', 'Model prices'],
        ['toolCatalog', 'Tool catalog'],
        ['tips', 'Tips & Advice'],
        ['telemetry', 'Telemetry'],
      ];
      return `<div class="analysis-subtabs">${tabs.map(([id, label]) => `<button type="button" class="subtab-button ${STATE.dataTab === id ? 'active' : ''}" onclick="switchDataTab('${id}')">${escapeHtml(label)}</button>`).join('')}</div>`;
    }

    function renderModelPricesSubtab() {
      const rows = Object.entries(PRICING_TABLE)
        .map(([name, pricing]) => ({ name, ...pricing }))
        .sort((a, b) => {
          const totalA = Number(a.input || 0) + Number(a.cached || 0) + Number(a.output || 0);
          const totalB = Number(b.input || 0) + Number(b.cached || 0) + Number(b.output || 0);
          return totalA - totalB;
        });

      return `
        <section class="panel">
          <h2 class="section-title">Model prices</h2>
          <div class="section-subtitle">Info: API-style prices per 1M tokens used by cost estimation in this dashboard.</div>
          <div class="compact-prices-wrap">
            <table class="compact-prices-table">
              <thead>
                <tr>
                  <th>Model</th>
                  <th>Input $/M</th>
                  <th>Cached-read $/M</th>
                  <th>Output $/M</th>
                </tr>
              </thead>
              <tbody>
                ${rows.map((row) => `<tr><td><strong>${escapeHtml(row.name)}</strong></td><td>${formatCost(row.input)}</td><td>${formatCost(row.cached)}</td><td>${formatCost(row.output)}</td></tr>`).join('')}
              </tbody>
            </table>
          </div>
        </section>`;
    }

    function renderToolCatalogSubtab() {
      const analysis = analysisForMode();
      const allRows = [...(analysis.toolCatalog || [])];
      if (!allRows.length) {
        return `<section class="panel"><h2 class="section-title">Tool catalog</h2><div class="note">No tool definitions were captured in the scanned logs yet.</div></section>`;
      }

      const search = (STATE.toolCatalogSearch || '').trim().toLowerCase();
      const sortKey = STATE.toolCatalogSortKey || 'descriptionTokens';
      const sortDir = STATE.toolCatalogSortDir || 'desc';

      const rows = sortRows(allRows
        .filter((row) => {
          if (!search) return true;
          return String(row.name || '').toLowerCase().includes(search) || String(row.description || '').toLowerCase().includes(search);
        }), sortKey, sortDir);

      function arrow(key) {
        if ((STATE.toolCatalogSortKey || 'descriptionTokens') !== key) return '<span style="opacity:.4">\u2195</span>';
        return (STATE.toolCatalogSortDir || 'desc') === 'desc' ? '\u2193' : '\u2191';
      }
      function th(key, label, numeric) {
        return `<th class="${numeric ? 'num' : ''}"><button type="button" onclick="setToolCatalogSort('${key}')" style="all:unset;cursor:pointer;color:inherit;display:block;width:100%;text-align:${numeric ? 'right' : 'left'}">${label} ${arrow(key)}</button></th>`;
      }

      return `
        <section class="panel">
          <h2 class="section-title">Tool description token footprint</h2>
          <div class="section-subtitle">Find context-heavy tools quickly. <strong>Tool sets</strong> means the number of distinct tool-definition payloads in which a tool appeared. Click any column header to sort ascending/descending; expand a tool name to view the full captured description.</div>
          <div class="tool-catalog-controls">
            <input type="text" id="toolCatalogSearchInput" placeholder="Search by tool name or description…" value="${escapeHtml(STATE.toolCatalogSearch)}" oninput="setToolCatalogSearch(this.value)">
          </div>
          <div class="note small" style="margin-bottom:10px">Showing ${formatInteger(rows.length)} of ${formatInteger(allRows.length)} tools.</div>
          <div style="overflow-x:auto">
          <table>
            <thead><tr>
              ${th('name', 'Tool', false)}
              ${th('descriptionTokens', 'Description tokens', true)}
              ${th('callCount', 'Calls', true)}
              ${th('sessionCount', 'Sessions', true)}
              ${th('toolSetCount', 'Tool sets', true)}
              ${th('presentCount', 'Present in calls', true)}
              ${th('wastePercent', 'Waste %', true)}
            </tr></thead>
            <tbody>
              ${rows.length ? rows.map((row) => `<tr>
                <td><details><summary><strong>${escapeHtml(row.name)}</strong></summary><pre>${escapeHtml(row.description || '[No description captured for this tool in scanned tool-definition payloads.]')}</pre></details></td>
                <td class="num"><span class="value uncached">${formatInteger(row.descriptionTokens || 0)}</span></td>
                <td class="num">${formatInteger(row.callCount || 0)}</td>
                <td class="num">${formatInteger(row.sessionCount || 0)}</td>
                <td class="num">${formatInteger(row.toolSetCount || 0)}</td>
                <td class="num">${formatInteger(row.presentCount || 0)}</td>
                <td class="num">${formatPercent(row.wastePercent || 0)}</td>
              </tr>`).join('') : '<tr><td colspan="7"><div class="note">No tools matched your search.</div></td></tr>'}
            </tbody>
          </table>
          </div>
        </section>`;
    }

    function renderTipsSubtab() {
      const tips = [
        {
          icon: '🔁',
          title: "Don't switch models mid-chat",
          severity: 'high',
          body: "Every time you switch models in a conversation, the context cache is invalidated. The next call must re-read the entire accumulated context as fresh (uncached) tokens. This can 3–10× the cost of that single turn. Start a new chat when you want to try a different model.",
        },
        {
          icon: '✂️',
          title: 'Keep chats short',
          severity: 'high',
          body: "Every new message in a chat is appended to an ever-growing context window. By turn 20, the model is re-reading the entire history on every call. Split long tasks into focused sub-chats, each under 10–15 turns. Your cache hit rate will be much higher and costs much lower.",
        },
        {
          icon: '🔧',
          title: 'Reduce active tools',
          severity: 'medium',
          body: "Tool definitions are included in every single prompt sent to the model — even if no tools are called. With 30+ tools enabled, you may be spending thousands of tokens per call just on tool schema overhead. Disable tools or skills you do not need for the current task.",
        },
        {
          icon: '🆕',
          title: 'Start a new chat for each new topic',
          severity: 'medium',
          body: "Continuing an existing chat for unrelated tasks forces the model to carry irrelevant context (previous files, messages, tool results). This inflates the prompt size and reduces cache effectiveness. A fresh chat starts with a minimal context and much better cache hit rates.",
        },
        {
          icon: '💾',
          title: 'Let the cache warm up',
          severity: 'medium',
          body: "Copilot uses prompt caching — identical leading content across consecutive turns is billed at a fraction of normal input cost. The longer you continue a focused conversation, the higher your cache hit rate becomes. Avoid making large edits to files mid-chat as this changes the prompt shape and busts the cache.",
        },
        {
          icon: '📄',
          title: 'Be selective with context files',
          severity: 'medium',
          body: "#file references and workspace context are included in every prompt turn. Attaching large files or entire directories significantly inflates your context window. Reference only the specific files relevant to the current task and remove them when no longer needed.",
        },
        {
          icon: '📝',
          title: 'Keep system prompts lean',
          severity: 'low',
          body: "Custom instructions and system prompts are prepended to every API call. A 2,000-token system prompt added to 600 chat calls costs you 1.2M extra input tokens. Audit your .github/copilot-instructions.md and VS Code custom instructions — keep them focused and concise.",
        },
        {
          icon: '⚡',
          title: 'Use cheaper models for simple tasks',
          severity: 'low',
          body: "Not every task needs a frontier model. Simple code completions, renaming, or straightforward Q&A work just as well with faster, cheaper models (e.g. gpt-4o-mini, claude-haiku). Reserve expensive models for complex reasoning, architecture decisions, or tasks that genuinely need deep understanding.",
        },
        {
          icon: '🔍',
          title: 'Monitor your cache hit rate',
          severity: 'low',
          body: "A healthy cache hit rate is 85%+ — meaning most of your input tokens are billed at the cheap cached rate. If your cache hit rate drops below 70%, you are probably switching contexts too often, switching models, or having frequent context resets. Check the Analysis → Insights tab for patterns.",
        },
        {
          icon: '🤖',
          title: 'Avoid long agentic loops',
          severity: 'low',
          body: "Autonomous agent tasks with many tool call loops (read_file, replace_string_in_file, run_in_terminal repeated 30+ times) accumulate massive context quickly. Break large agentic tasks into smaller, focused steps. If a subagent approach is available, use it — subagents start fresh contexts.",
        },
      ];

      const severityColors = {
        high: 'var(--red)',
        medium: 'var(--yellow)',
        low: 'var(--green)',
      };
      const severityLabels = { high: 'High impact', medium: 'Medium impact', low: 'Low impact' };

      return `
        <div class="analysis-grid">
          <section class="panel">
            <h2 class="section-title">Tips & Advice — Reducing Token Usage and Costs</h2>
            <div class="section-subtitle">Based on analysis of common usage patterns. High-impact tips can reduce costs by 50–80%. The <span style="color:var(--red)">red</span> badges indicate the biggest wins.</div>
            <div class="insights-grid" style="grid-template-columns: repeat(auto-fit, minmax(300px, 1fr))">
              ${tips.map((tip) => `
                <div class="insight-card" style="border-left:3px solid ${severityColors[tip.severity]}">
                  <h4 style="display:flex;align-items:center;gap:8px;white-space:normal">
                    <span style="font-size:1.4rem">${tip.icon}</span>
                    <span>${escapeHtml(tip.title)}</span>
                    <span style="margin-left:auto;font-size:0.7rem;font-weight:700;color:${severityColors[tip.severity]};white-space:nowrap">${severityLabels[tip.severity]}</span>
                  </h4>
                  <div class="note small" style="line-height:1.6">${escapeHtml(tip.body)}</div>
                </div>`).join('')}
            </div>
          </section>
        </div>`;
    }

    function renderTelemetrySubtab() {
      const telemetry = activeAnalysis().telemetry || { sections: [], observedFields: [], entryTypes: {} };
      return `
        <div class="analysis-grid">
          <section class="panel">
            <h2 class="section-title">Telemetry coverage</h2>
            <div class="section-subtitle">What the current Copilot debug / OTel data gives directly, and what the dashboard must estimate.</div>
            <div class="insights-grid">
              ${(telemetry.sections || []).map((section) => `<div class="insight-card"><h4>${escapeHtml(section.name)}</h4><ul class="help-list">${(section.items || []).map((item) => `<li>${escapeHtml(item)}</li>`).join('')}</ul></div>`).join('')}
            </div>
          </section>
          <section class="panel">
            <h2 class="section-title">Observed attribute fields</h2>
            <pre>${escapeHtml(JSON.stringify(telemetry.observedFields, null, 2))}</pre>
          </section>
        </div>`;
    }

    function renderReferenceTab() {
      const tabBodies = {
        prices: renderModelPricesSubtab,
        toolCatalog: renderToolCatalogSubtab,
        tips: renderTipsSubtab,
        telemetry: renderTelemetrySubtab,
      };
      if (!tabBodies[STATE.dataTab]) {
        STATE.dataTab = 'prices';
      }
      return `<section class="panel">${dataSubtabs()}</section>${tabBodies[STATE.dataTab]()}`;
    }

    function renderAnalysisTab() {
      const tabBodies = {
        models: renderModelsSubtab,
        tools: renderToolsSubtab,
        files: renderFilesSubtab,
        monthlyTrends: renderMonthlyTrendsSubtab,
        insights: renderInsightsSubtab,
      };
      if (!tabBodies[STATE.analysisTab]) {
        STATE.analysisTab = 'models';
      }
      return `<section class="panel">${analysisSubtabs()}</section>${tabBodies[STATE.analysisTab]()}`;
    }

    function renderPart(part) {
      if (part.type === 'tool_call') {
        return `<div class="part-card"><div class="part-label">${escapeHtml(part.label)}</div><pre>${escapeHtml(part.arguments_pretty || '')}</pre></div>`;
      }
      return `<div class="part-card"><div class="part-label">${escapeHtml(part.label || part.type || 'Part')}</div><pre>${escapeHtml(part.text || '')}</pre></div>`;
    }

    function renderMessage(message) {
      return `<div class="message-card"><div class="message-header"><span class="badge ${message.role === 'user' ? 'user' : message.role === 'assistant' ? 'chat' : 'tool'}">${escapeHtml(message.role)}</span><span class="note small">${formatInteger(message.parts?.length || 0)} parts</span></div><div class="message-parts">${(message.parts || []).map(renderPart).join('')}</div></div>`;
    }

    // Cache of full session payloads ({session, assets}) fetched on demand.
    const FULL_SESSIONS = {};

    function findSessionAndEvent(sessionId, eventId) {
      const full = FULL_SESSIONS[sessionId];
      const session = full?.session;
      const event = session?.events?.find((item) => item.id === eventId);
      return { session, event, assets: full?.assets || { systemPrompts: {}, toolSets: {} } };
    }

    function renderGenAiModal(sessionId, eventId) {
      const { session, event, assets } = findSessionAndEvent(sessionId, eventId);
      if (!session || !event) return;
      const selectedTokens = eventDisplayChatTokens(event);
      const systemPrompt = event.system_prompt_id ? (assets.systemPrompts || {})[event.system_prompt_id] : null;
      const toolSet = event.tools_id ? (assets.toolSets || {})[event.tools_id] : null;
      const details = {
        source: event.source,
        debugName: event.debug_name,
        responseId: event.response_id,
        durationMs: event.duration_ms,
        ttftMs: event.ttft_ms,
        segmentIndex: event.segment_index,
        boundaryReasons: event.boundary_reasons,
        maxTokens: event.max_tokens,
        diffMode: event.diff_mode,
        attributionTokens: event.attribution_tokens,
        requestOptions: event.request_options,
        requestShape: event.request_shape,
      };

      document.getElementById('genaiModalTitle').textContent = event.title;
      document.getElementById('genaiModalSubtitle').textContent = `${session.title} · ${event.model} · ${formatTimestamp(event.ts)}`;
      document.getElementById('genaiModalStats').innerHTML = `
        <div class="meta-card"><div class="label">Prompt now</div><div class="value input">${formatInteger(event.prompt_tokens)}</div></div>
        <div class="meta-card"><div class="label">Segment</div><div class="value">${formatInteger(event.segment_index || 1)}</div></div>
        <div class="meta-card"><div class="label">Total input</div><div class="value input">${formatInteger(selectedTokens.input)}</div></div>
        <div class="meta-card"><div class="label">Uncached input</div><div class="value uncached">${formatInteger(selectedTokens.uncached)}</div></div>
        <div class="meta-card"><div class="label">Cached-read</div><div class="value cached">${formatInteger(selectedTokens.cached)}</div></div>
        <div class="meta-card"><div class="label">Output</div><div class="value output">${formatInteger(selectedTokens.output)}</div></div>
        <div class="meta-card"><div class="label">TTFT</div><div class="value">${formatDuration(event.ttft_ms)}</div></div>
        <div class="meta-card"><div class="label">${isBilledMode() ? 'Billed cost' : 'Attributed est. cost'}</div><div class="value cost">${formatCost(selectedTokens.cost)}</div></div>`;

      const tabs = [
        ['io', 'Input & output'],
        ['tools', `Tools${toolSet?.tool_names?.length ? ' ' + toolSet.tool_names.length : ''}`],
        ['context', 'Context window'],
        ['details', 'Details'],
      ];
      document.getElementById('genaiModalTabs').innerHTML = tabs.map(([id, title], index) => `<button type="button" data-tab="${id}" class="modal-tab ${index === 0 ? 'active' : ''}" onclick="switchGenAiTab('${id}')">${escapeHtml(title)}</button>`).join('');

      document.getElementById('genaiModalContent').innerHTML = `
        <div id="genai-panel-io" class="modal-panel active">
          <div class="split-grid">
            <div class="event-section"><h4>System prompt</h4><pre>${escapeHtml(systemPrompt?.plain_text || '[not available]')}</pre></div>
            <div class="event-section"><h4>Assistant output</h4><div class="message-list">${(event.response_messages || []).map(renderMessage).join('') || '<div class="note">No structured output was stored.</div>'}</div></div>
          </div>
          <div class="event-section"><h4>Input messages Copilot sent into this call</h4><div class="message-list">${(event.input_messages || []).map(renderMessage).join('') || '<div class="note">No input messages were recorded.</div>'}</div></div>
          <div class="event-section"><h4>New context added since previous call</h4><div class="message-list">${(event.new_messages || []).map(renderMessage).join('') || '<div class="note">No new messages detected or the prompt was rebuilt.</div>'}</div></div>
        </div>
        <div id="genai-panel-tools" class="modal-panel">
          <div class="event-section"><h4>Tool definitions available to the model</h4>${toolSet?.tool_names?.length ? `<div class="pill-list">${toolSet.tool_names.map((name) => `<span class="pill">${escapeHtml(name)}</span>`).join('')}</div>` : '<div class="note">No tool definitions were captured for this call.</div>'}</div>
          <div class="split-grid">
            <div class="event-section"><h4>Emitted tool calls</h4><div class="message-list">${(event.tool_calls_emitted || []).map((tool) => `<div class="message-card"><div class="message-header"><span class="badge tool">Tool call</span><strong>${escapeHtml(tool.name)}</strong></div><pre>${escapeHtml(tool.arguments || '')}</pre></div>`).join('') || '<div class="note">This chat call did not emit a tool call.</div>'}</div></div>
            <div class="event-section"><h4>Tool definition payload</h4><pre>${escapeHtml(toolSet?.plain_text || '[not available]')}</pre></div>
          </div>
        </div>
        <div id="genai-panel-context" class="modal-panel">
          ${renderContextBreakdown(event.context_breakdown)}
        </div>
        <div id="genai-panel-details" class="modal-panel">
          <div class="split-grid">
            <div class="event-section"><h4>Observed request metrics</h4><pre>${escapeHtml(JSON.stringify({ promptTokens: event.prompt_tokens, promptDiff: event.prompt_diff, cachedTokens: event.cached_tokens, uncachedPromptTokens: event.uncached_prompt_tokens, selectedMode: tokenModeLabel(), selectedTokens, billed: event.billed_tokens, attributionTokens: event.attribution_tokens, boundaryReasons: event.boundary_reasons }, null, 2))}</pre></div>
            <div class="event-section"><h4>Request metadata</h4><pre>${escapeHtml(JSON.stringify(details, null, 2))}</pre></div>
          </div>
          <div class="split-grid">
            <div class="event-section"><h4>Reasoning</h4><pre>${escapeHtml(event.reasoning || '[not recorded]')}</pre></div>
            <div class="event-section"><h4>Raw response text</h4><pre>${escapeHtml(event.response_text || '[empty]')}</pre></div>
          </div>
        </div>`;

      document.getElementById('genaiModalBackdrop').classList.add('open');
    }

    function switchGenAiTab(tabId) {
      document.querySelectorAll('#genaiModalTabs .modal-tab').forEach((button) => button.classList.toggle('active', button.dataset.tab === tabId));
      document.querySelectorAll('#genaiModalContent .modal-panel').forEach((panel) => panel.classList.toggle('active', panel.id === `genai-panel-${tabId}`));
    }

    async function openGenAiModal(sessionId, eventId) {
      if (!FULL_SESSIONS[sessionId]) {
        try {
          await fetchFullSession(sessionId);
        } catch (_err) {
          return;
        }
      }
      renderGenAiModal(sessionId, eventId);
    }

    function closeGenAiModal(event) {
      if (event && event.target && event.target !== document.getElementById('genaiModalBackdrop')) return;
      document.getElementById('genaiModalBackdrop').classList.remove('open');
    }

    async function fetchFullSession(sessionId) {
      if (FULL_SESSIONS[sessionId]) return FULL_SESSIONS[sessionId];
      const response = await fetch(`/api/session?id=${encodeURIComponent(sessionId)}`);
      if (!response.ok) {
        throw new Error(`Failed to load chat (${response.status})`);
      }
      const payload = await response.json();
      if (!payload || !payload.session) {
        throw new Error('Full chat detail is not available for this session.');
      }
      FULL_SESSIONS[sessionId] = payload;
      return payload;
    }

    function renderFullChatBody(session) {
      const events = Array.isArray(session?.events) ? session.events : [];
      const timeline = events.length
        ? events.map((event) => renderEvent(event, session)).join('')
        : '<div class="note">No per-call events were recorded for this chat.</div>';
      return `
        ${renderSessionMeta(session)}
        ${renderSessionTokenBreakdown(session)}
        <div class="timeline">${timeline}</div>`;
    }

    async function openFullChatModal(sessionId) {
      const meta = (APP_DATA.sessions || []).find((item) => item.id === sessionId);
      const backdrop = document.getElementById('fullChatModalBackdrop');
      document.getElementById('fullChatModalTitle').textContent = meta?.title || 'Full chat';
      document.getElementById('fullChatModalSubtitle').textContent = meta
        ? `${meta.model || 'unknown'} · ${formatTimestamp(meta.timestamp)} · ${formatInteger(meta.chat_count)} calls · ${formatInteger(meta.tool_count)} tools`
        : '';
      const exportBtn = document.getElementById('fullChatExportBtn');
      if (exportBtn) exportBtn.onclick = () => exportSessionToJson(sessionId);
      const body = document.getElementById('fullChatModalContent');
      body.innerHTML = '<div class="note" style="padding:24px;text-align:center">Loading full chat detail…</div>';
      backdrop.classList.add('open');
      try {
        const payload = await fetchFullSession(sessionId);
        body.innerHTML = renderFullChatBody(payload.session);
      } catch (err) {
        body.innerHTML = `<div class="note" style="padding:24px;text-align:center;color:var(--red)">${escapeHtml(String(err && err.message || err))}</div>`;
      }
    }

    function closeFullChatModal(event) {
      if (event && event.target && event.target !== document.getElementById('fullChatModalBackdrop')) return;
      document.getElementById('fullChatModalBackdrop').classList.remove('open');
    }

    function renderFileUsageSummary(file) {
      const rows = [...(file?.toolUsage || [])].sort((a, b) => Number(b.cost || 0) - Number(a.cost || 0) || Number(b.count || 0) - Number(a.count || 0));
      if (!rows.length) {
        return '<div class="note">No aggregated tool usage captured for this file.</div>';
      }
      const totals = rows.reduce((acc, row) => {
        acc.count += Number(row.count || 0);
        acc.durationMs += Number(row.durationMs || 0);
        acc.input += Number(row.input || 0);
        acc.output += Number(row.output || 0);
        acc.cached += Number(row.cached || 0);
        acc.cost += Number(row.cost || 0);
        acc.payloadTokens += Number(row.payloadTokens || 0);
        return acc;
      }, { count: 0, durationMs: 0, input: 0, output: 0, cached: 0, cost: 0, payloadTokens: 0 });
      return `
        <div class="panel">
          <div class="note">Aggregated per tool and mode for this file — no per-call timeline is stored here.</div>
          <div style="overflow-x:auto;margin-top:10px">
            <table>
              <thead><tr>
                <th>Tool</th>
                <th>Mode</th>
                <th class="num">Calls</th>
                <th class="num">Sessions</th>
                <th class="num">Avg Duration</th>
                <th class="num">Total Input</th>
                <th class="num">Total Output</th>
                <th class="num">Total Cached</th>
                <th class="num">Payload</th>
                <th class="num">Cost</th>
              </tr></thead>
              <tbody>
                ${rows.map((row) => `<tr>
                  <td><strong>${escapeHtml(row.name || 'unknown')}</strong></td>
                  <td>${escapeHtml(row.mode || 'other')}</td>
                  <td class="num">${formatInteger(row.count || 0)}</td>
                  <td class="num">${formatInteger(row.sessionCount || 0)}</td>
                  <td class="num">${formatDuration(row.avgDurationMs || 0)}</td>
                  <td class="num"><span class="value input">${formatCompact(row.input || 0)}</span></td>
                  <td class="num"><span class="value output">${formatCompact(row.output || 0)}</span></td>
                  <td class="num"><span class="value cached">${formatCompact(row.cached || 0)}</span></td>
                  <td class="num">${formatInteger(row.payloadTokens || 0)}</td>
                  <td class="num"><span class="value cost">${formatCost(row.cost || 0)}</span></td>
                </tr>`).join('')}
                <tr style="border-top:2px solid var(--border);font-weight:700">
                  <td>TOTAL</td>
                  <td></td>
                  <td class="num">${formatInteger(totals.count)}</td>
                  <td class="num">${formatInteger(file.sessionCount || 0)}</td>
                  <td class="num">${formatDuration(totals.count ? totals.durationMs / totals.count : 0)}</td>
                  <td class="num"><span class="value input">${formatCompact(totals.input)}</span></td>
                  <td class="num"><span class="value output">${formatCompact(totals.output)}</span></td>
                  <td class="num"><span class="value cached">${formatCompact(totals.cached)}</span></td>
                  <td class="num">${formatInteger(totals.payloadTokens)}</td>
                  <td class="num"><span class="value cost">${formatCost(totals.cost)}</span></td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>`;
    }

    function openFileModal(pathEncoded) {
      const path = decodeURIComponent(pathEncoded);
      const file = (analysisForMode().files || []).find((item) => item.path === path);
      if (!file) return;
      document.getElementById('fileExportBtn').onclick = () => exportFileToJson(pathEncoded);
      document.getElementById('fileModalTitle').textContent = file.name;
      document.getElementById('fileModalSubtitle').textContent = file.shortPath + ' · ' + tokenModeLabel() + ' mode · ' + formatInteger(file.toolReferenceCount || 0) + ' tool refs';
      const totalFileOps = file.readCount + file.editCount;
      document.getElementById('fileModalStats').innerHTML = `
        <div class="meta-card"><div class="label">Reads</div><div class="value">${formatInteger(file.readCount)}</div></div>
        <div class="meta-card"><div class="label">Edits</div><div class="value">${formatInteger(file.editCount)}</div></div>
        <div class="meta-card"><div class="label">Tool refs</div><div class="value">${formatInteger(file.toolReferenceCount || 0)}</div></div>
        <div class="meta-card"><div class="label">Unique tools</div><div class="value">${formatInteger((file.toolUsage || []).length)}</div></div>
        <div class="meta-card"><div class="label">Total Input</div><div class="value input">${formatInteger(file.input)}</div></div>
        <div class="meta-card"><div class="label">Total Output</div><div class="value output">${formatInteger(file.output)}</div></div>
        <div class="meta-card"><div class="label">Total Cached</div><div class="value cached">${formatInteger(file.cached)}</div></div>
        <div class="meta-card"><div class="label">Avg Input</div><div class="value input">${formatInteger(totalFileOps ? file.input / totalFileOps : 0)}</div></div>
        <div class="meta-card"><div class="label">Avg Cost</div><div class="value cost">${formatCost(totalFileOps ? file.cost / totalFileOps : 0)}</div></div>
        <div class="meta-card"><div class="label">Total Cost</div><div class="value cost">${formatCost(file.cost)}</div></div>`;
      document.getElementById('fileModalContent').innerHTML = `
        ${renderFileUsageSummary(file)}`;
      document.getElementById('fileModalBackdrop').classList.add('open');
    }

    function closeFileModal(event) {
      if (event && event.target && event.target !== document.getElementById('fileModalBackdrop')) return;
      document.getElementById('fileModalBackdrop').classList.remove('open');
    }

    function exportFileToJson(pathEncoded) {
      const path = decodeURIComponent(pathEncoded);
      const file = (analysisForMode().files || []).find((item) => item.path === path);
      if (!file) return;
      const blob = new Blob([JSON.stringify(file, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      const safeName = (file.name || 'file').replace(/[^a-zA-Z0-9._-]/g, '_');
      const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
      a.href = url;
      a.download = `file-activity-${safeName}-${ts}.json`;
      a.click();
      URL.revokeObjectURL(url);
    }

    let _searchTimer = null;
    function setSearch(value) {
      STATE.search = value;
      STATE.page = 1;
      if (_searchTimer) clearTimeout(_searchTimer);
      _searchTimer = setTimeout(() => renderApp(), 300);
    }

    let _toolCatalogSearchTimer = null;
    function setToolCatalogSearch(value) {
      STATE.toolCatalogSearch = value;
      if (_toolCatalogSearchTimer) clearTimeout(_toolCatalogSearchTimer);
      _toolCatalogSearchTimer = setTimeout(() => renderApp(), 120);
    }

    let _toolImpactSearchTimer = null;
    function setToolImpactSearch(value) {
      STATE.toolImpactSearch = value;
      if (_toolImpactSearchTimer) clearTimeout(_toolImpactSearchTimer);
      _toolImpactSearchTimer = setTimeout(() => renderApp(), 120);
    }

    let _fileSearchTimer = null;
    function setFileSearch(value) {
      STATE.fileSearch = value;
      if (_fileSearchTimer) clearTimeout(_fileSearchTimer);
      _fileSearchTimer = setTimeout(() => renderApp(), 120);
    }

    function setToolCatalogSort(key) {
      if (STATE.toolCatalogSortKey === key) {
        STATE.toolCatalogSortDir = (STATE.toolCatalogSortDir || 'desc') === 'desc' ? 'asc' : 'desc';
      } else {
        STATE.toolCatalogSortKey = key;
        STATE.toolCatalogSortDir = key === 'name' ? 'asc' : 'desc';
      }
      renderApp();
    }

    function setToolCatalogSortKey(value) {
      setToolCatalogSort(value);
    }

    function toggleToolCatalogSortDir() {
      STATE.toolCatalogSortDir = (STATE.toolCatalogSortDir || 'desc') === 'desc' ? 'asc' : 'desc';
      renderApp();
    }

    function switchToolImpactTab(tab) {
      STATE.toolImpactTab = tab;
      renderApp();
    }

    function switchMonthlyTrendMetric(metricKey) {
      STATE.monthlyTrendMetric = metricKey;
      renderApp();
    }

    function setToolWasteSort(key) {
      if (STATE.toolWasteSortKey === key) {
        STATE.toolWasteSortDir = (STATE.toolWasteSortDir || 'desc') === 'desc' ? 'asc' : 'desc';
      } else {
        STATE.toolWasteSortKey = key;
        STATE.toolWasteSortDir = key === 'name' ? 'asc' : 'desc';
      }
      renderApp();
    }

    function setModelFilter(value) {
      STATE.model = value;
      STATE.page = 1;
      renderApp();
    }

    function setPageSize(value) {
      STATE.pageSize = Number(value || 10);
      STATE.page = 1;
      renderApp();
    }

    function changePage(delta) {
      const pages = pagedSessions();
      STATE.page = Math.max(1, Math.min(pages.pageCount, STATE.page + delta));
      renderApp();
    }

    function switchTab(tabName) {
      STATE.activeTab = tabName;
      renderApp();
    }

    function switchUsagePeriod(periodName) {
      if (periodName !== 'monthly' && periodName !== 'allTime') return;
      STATE.usagePeriod = periodName;
      STATE.page = 1;
      renderApp();
    }

    function switchTokenMode(modeName) {
      const normalized = normalizeTokenMode(modeName);
      if (STATE.tokenMode === normalized) return;
      STATE.tokenMode = normalized;
      persistTokenMode();
      renderApp();
    }

    function switchAnalysisTab(tabName) {
      STATE.analysisTab = tabName;
      renderApp();
    }

    function switchDataTab(tabName) {
      STATE.dataTab = tabName;
      renderApp();
    }

    function deleteSessionPrompt(sessionId) {
      const session = APP_DATA.sessions.find((item) => item.id === sessionId);
      if (!session) return;
      const title = (session.title || 'this chat').slice(0, 90);
      if (!confirm(`Delete "${title}" from the Chats tab?`)) return;
      const changed = markSessionsHidden([sessionId]);
      if (changed) renderApp();
    }

    function visibleSessionsSortedByTimestamp() {
      return visibleSessions().slice().sort((a, b) => Number(b.timestamp || 0) - Number(a.timestamp || 0));
    }

    function setDeleteMode(mode) {
      STATE.deleteMode = mode;
      updateChatDeletePreview();
    }

    function setDeleteAgePreset(value) {
      STATE.deleteAgePreset = value;
      updateChatDeletePreview();
    }

    function setDeleteSpecificDate(value) {
      STATE.deleteCustomDate = value;
      updateChatDeletePreview();
    }

    function setDeleteKeepCount(value) {
      const parsed = Number(value || 10);
      STATE.deleteKeepCount = Number.isFinite(parsed) ? Math.max(1, Math.floor(parsed)) : 10;
      const input = document.getElementById('deleteKeepCount');
      if (input && Number(input.value) !== STATE.deleteKeepCount) {
        input.value = STATE.deleteKeepCount;
      }
      updateChatDeletePreview();
    }

    function computeChatDeletionTargets() {
      const sessions = visibleSessionsSortedByTimestamp();
      const mode = STATE.deleteMode || 'all';
      if (!sessions.length) return [];

      if (mode === 'all') {
        return sessions.map((session) => session.id);
      }

      if (mode === 'keep_last') {
        const keepCount = Math.max(1, Number(STATE.deleteKeepCount || 10));
        return sessions.slice(keepCount).map((session) => session.id);
      }

      if (mode === 'before_date') {
        let cutoffMs = 0;
        if (STATE.deleteAgePreset === 'day') {
          cutoffMs = Date.now() - 24 * 60 * 60 * 1000;
        } else if (STATE.deleteAgePreset === 'week') {
          cutoffMs = Date.now() - 7 * 24 * 60 * 60 * 1000;
        } else if (STATE.deleteAgePreset === 'month') {
          cutoffMs = Date.now() - 30 * 24 * 60 * 60 * 1000;
        } else {
          if (!STATE.deleteCustomDate) return [];
          cutoffMs = new Date(`${STATE.deleteCustomDate}T00:00:00`).getTime();
          if (!Number.isFinite(cutoffMs)) return [];
        }
        return sessions.filter((session) => Number(session.timestamp || 0) < cutoffMs).map((session) => session.id);
      }

      return [];
    }

    function updateChatDeletePreview() {
      const previewEl = document.getElementById('chatDeletePreview');
      const applyBtn = document.getElementById('chatDeleteApplyBtn');
      if (!previewEl || !applyBtn) return;

      const visibleCount = visibleSessions().length;
      const targets = computeChatDeletionTargets();
      previewEl.innerHTML = `This action will hide <strong>${formatInteger(targets.length)}</strong> of <strong>${formatInteger(visibleCount)}</strong> visible chats from the Chats tab.`;
      applyBtn.disabled = !targets.length;
      applyBtn.style.opacity = targets.length ? '1' : '0.5';
      applyBtn.style.cursor = targets.length ? 'pointer' : 'default';

      const customDateInput = document.getElementById('deleteSpecificDate');
      if (customDateInput) {
        customDateInput.disabled = STATE.deleteAgePreset !== 'custom';
      }
    }

    function openChatDeleteModal() {
      if (!STATE.deleteCustomDate) {
        STATE.deleteCustomDate = new Date().toISOString().slice(0, 10);
      }

      const radios = document.querySelectorAll('input[name="chatDeleteMode"]');
      radios.forEach((radio) => {
        radio.checked = radio.value === STATE.deleteMode;
      });
      const agePreset = document.getElementById('deleteAgePreset');
      if (agePreset) agePreset.value = STATE.deleteAgePreset;
      const specificDate = document.getElementById('deleteSpecificDate');
      if (specificDate) specificDate.value = STATE.deleteCustomDate;
      const keepCount = document.getElementById('deleteKeepCount');
      if (keepCount) keepCount.value = STATE.deleteKeepCount;

      updateChatDeletePreview();
      document.getElementById('chatDeleteModalBackdrop').classList.add('open');
    }

    function closeChatDeleteModal(event) {
      if (event && event.target && event.target !== document.getElementById('chatDeleteModalBackdrop')) return;
      document.getElementById('chatDeleteModalBackdrop').classList.remove('open');
    }

    function applyChatDeletion() {
      const targets = computeChatDeletionTargets();
      if (!targets.length) {
        alert('No chats matched this delete rule.');
        return;
      }
      if (!confirm(`Delete ${targets.length} chat(s) from the Chats tab view?`)) return;

      const changed = markSessionsHidden(targets);
      closeChatDeleteModal();
      if (changed) {
        renderApp();
      }
    }

    function setFileSort(key) {
      if (STATE.fileSortKey === key) {
        STATE.fileSortDir = STATE.fileSortDir === 'desc' ? 'asc' : 'desc';
      } else {
        STATE.fileSortKey = key;
        STATE.fileSortDir = key === 'name' ? 'asc' : 'desc';
      }
      renderApp();
    }

    function setToolSort(key) {
      if (STATE.toolSortKey === key) {
        STATE.toolSortDir = (STATE.toolSortDir || 'desc') === 'desc' ? 'asc' : 'desc';
      } else {
        STATE.toolSortKey = key;
        STATE.toolSortDir = key === 'name' ? 'asc' : 'desc';
      }
      renderApp();
    }

    function toggleAutoRefresh() { /* auto-refresh disabled */ }

    function updateRefreshInterval(value) { /* auto-refresh disabled */ }

    function exportToJson() {
      const blob = new Blob([JSON.stringify(APP_DATA, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
      a.href = url;
      a.download = `copilot-dashboard-${ts}.json`;
      a.click();
      URL.revokeObjectURL(url);
    }

    async function exportSessionToJson(sessionId) {
      const meta = (APP_DATA.sessions || []).find((s) => s.id === sessionId);
      const safeName = (meta?.title || 'chat').replace(/[^a-zA-Z0-9._-]/g, '_').slice(0, 40);
      const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
      let exportData;
      try {
        // The full chat detail lives in the on-demand full-session cache file.
        const payload = await fetchFullSession(sessionId);
        exportData = payload.session;
      } catch (err) {
        // Fall back to the compact summary if the full payload cannot be loaded.
        exportData = meta;
      }
      if (!exportData) return;
      const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `chat-${safeName}-${ts}.json`;
      a.click();
      URL.revokeObjectURL(url);
    }

    const PRICING_TABLE = __PRICING_JSON__;

    function calcModelCost(inputTokens, cachedTokens, outputTokens, pricing) {
      const uncached = Math.max(0, inputTokens - cachedTokens);
      return (uncached / 1e6) * pricing.input + (cachedTokens / 1e6) * pricing.cached + (outputTokens / 1e6) * pricing.output;
    }

    function openModelCompareModal(sessionId) {
      const session = APP_DATA.sessions.find((s) => s.id === sessionId);
      if (!session) return;
      const totals = sessionDisplayTotals(session);
      const inputTokens = totals.input || 0;
      const cachedTokens = totals.cached || 0;
      const outputTokens = totals.output || 0;
      const actualModel = session.model || 'unknown';
      const actualCost = totals.cost || 0;

      document.getElementById('modelCompareModalTitle').textContent = 'Model cost comparison';
      document.getElementById('modelCompareModalSubtitle').textContent = session.title + ' · ' + formatInteger(inputTokens) + ' input · ' + formatInteger(outputTokens) + ' output tokens (' + tokenModeLabel() + ')';

      const rows = Object.entries(PRICING_TABLE).map(([model, pricing]) => ({
        model,
        cost: calcModelCost(inputTokens, cachedTokens, outputTokens, pricing),
        pricing,
      })).sort((a, b) => a.cost - b.cost);

      const minCost = rows[0]?.cost || 0;

      document.getElementById('modelCompareModalContent').innerHTML = `
        <div class="note small" style="margin-bottom:12px">Estimated cost if this chat's ${escapeHtml(tokenModeLabel())} token usage (<strong>${formatInteger(inputTokens)}</strong> input, <strong>${formatInteger(cachedTokens)}</strong> cached, <strong>${formatInteger(outputTokens)}</strong> output) was processed by each model. Assumes same cache hit pattern.</div>
        <div style="overflow-x:auto">
        <table>
          <thead><tr>
            <th>Model</th>
            <th class="num">Input $/M</th>
            <th class="num">Cached $/M</th>
            <th class="num">Output $/M</th>
            <th class="num">Est. Cost</th>
            <th class="num">vs actual</th>
          </tr></thead>
          <tbody>
            ${rows.map((row) => {
              const isActual = row.model === actualModel;
              const delta = row.cost - actualCost;
              const isCheapest = Math.abs(row.cost - minCost) < 0.000001;
              return `<tr style="${isActual ? 'background:rgba(88,166,255,0.08);border-left:2px solid var(--blue)' : ''}">
                <td><strong style="${isCheapest ? 'color:var(--green)' : ''}">${escapeHtml(row.model)}</strong>${isActual ? ' <span class="badge chat" style="font-size:0.65rem;padding:2px 6px">current</span>' : ''}${isCheapest ? ' <span class="badge mode-read" style="font-size:0.65rem;padding:2px 6px">cheapest</span>' : ''}</td>
                <td class="num">${formatCost(row.pricing.input)}</td>
                <td class="num">${formatCost(row.pricing.cached)}</td>
                <td class="num">${formatCost(row.pricing.output)}</td>
                <td class="num"><strong style="color:var(--teal)">${formatCost(row.cost)}</strong></td>
                <td class="num" style="color:${delta < -0.0001 ? 'var(--green)' : delta > 0.0001 ? 'var(--red)' : 'var(--muted)'}">${isActual ? '—' : (delta >= 0 ? '+' : '') + formatCost(Math.abs(delta))}</td>
              </tr>`;
            }).join('')}
          </tbody>
        </table>
        </div>`;

      document.getElementById('modelCompareModalBackdrop').classList.add('open');
    }

    function closeModelCompareModal(event) {
      if (event && event.target && event.target !== document.getElementById('modelCompareModalBackdrop')) return;
      document.getElementById('modelCompareModalBackdrop').classList.remove('open');
    }

    function scheduleRefresh() { /* auto-refresh disabled */ }

    function captureInputFocusState() {
      const activeEl = document.activeElement;
      if (!activeEl || !activeEl.id) return null;
      const tagName = String(activeEl.tagName || '').toLowerCase();
      if (tagName !== 'input' && tagName !== 'textarea') return null;
      const inputType = String(activeEl.type || '').toLowerCase();
      const supportsSelection = typeof activeEl.selectionStart === 'number' && typeof activeEl.selectionEnd === 'number' && inputType !== 'number';
      return {
        id: activeEl.id,
        selectionStart: supportsSelection ? activeEl.selectionStart : null,
        selectionEnd: supportsSelection ? activeEl.selectionEnd : null,
      };
    }

    function restoreInputFocusState(state) {
      if (!state || !state.id) return;
      const nextEl = document.getElementById(state.id);
      if (!nextEl) return;
      nextEl.focus();
      if (state.selectionStart === null || state.selectionEnd === null) return;
      if (typeof nextEl.setSelectionRange !== 'function') return;
      try {
        nextEl.setSelectionRange(state.selectionStart, state.selectionEnd);
      } catch (_err) {
        // Some input types do not support selection ranges.
      }
    }

    function renderApp() {
      const app = document.getElementById('app');
      const pages = pagedSessions();
      if (STATE.page > pages.pageCount) STATE.page = pages.pageCount;
      const focusState = captureInputFocusState();
      app.innerHTML = `
        ${renderHeader()}
        <section class="tab-panel ${STATE.activeTab === 'chats' ? 'active' : ''}">${renderChatsTab()}</section>
        <section class="tab-panel ${STATE.activeTab === 'analysis' ? 'active' : ''}">${renderAnalysisTab()}</section>
        <section class="tab-panel ${STATE.activeTab === 'reference' ? 'active' : ''}">${renderReferenceTab()}</section>`;
      restoreInputFocusState(focusState);
    }

    renderApp();

  </script>

</body>
</html>'''
    html = html.replace('{{', '{').replace('}}', '}')
    html = html.replace('__PRICING_JSON__', pricing_json)
    return html.replace('__APP_JSON__', app_json)

