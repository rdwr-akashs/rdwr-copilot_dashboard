import { computeChatDeletionTargets, pagedSessions } from './aggregate.js';
import { renderApp } from './app.js';
import { closeChatDeleteModal, updateChatDeletePreview } from './modals.js';
import { APP_DATA, STATE, markCliSessionsHidden, markSessionsHidden, normalizeTokenMode, persistLastTab, persistTokenMode } from './state.js';


    let _searchTimer = null;
    export function setSearch(value) {
      STATE.search = value;
      STATE.page = 1;
      if (_searchTimer) clearTimeout(_searchTimer);
      _searchTimer = setTimeout(() => renderApp(), 300);
    }

    let _toolCatalogSearchTimer = null;
    export function setToolCatalogSearch(value) {
      STATE.toolCatalogSearch = value;
      if (_toolCatalogSearchTimer) clearTimeout(_toolCatalogSearchTimer);
      _toolCatalogSearchTimer = setTimeout(() => renderApp(), 120);
    }

    let _toolImpactSearchTimer = null;
    export function setToolImpactSearch(value) {
      STATE.toolImpactSearch = value;
      if (_toolImpactSearchTimer) clearTimeout(_toolImpactSearchTimer);
      _toolImpactSearchTimer = setTimeout(() => renderApp(), 120);
    }

    let _fileSearchTimer = null;
    export function setFileSearch(value) {
      STATE.fileSearch = value;
      if (_fileSearchTimer) clearTimeout(_fileSearchTimer);
      _fileSearchTimer = setTimeout(() => renderApp(), 120);
    }

    export function setToolCatalogSort(key) {
      if (STATE.toolCatalogSortKey === key) {
        STATE.toolCatalogSortDir = (STATE.toolCatalogSortDir || 'desc') === 'desc' ? 'asc' : 'desc';
      } else {
        STATE.toolCatalogSortKey = key;
        STATE.toolCatalogSortDir = key === 'name' ? 'asc' : 'desc';
      }
      renderApp();
    }

    export function setToolCatalogSortKey(value) {
      setToolCatalogSort(value);
    }

    export function toggleToolCatalogSortDir() {
      STATE.toolCatalogSortDir = (STATE.toolCatalogSortDir || 'desc') === 'desc' ? 'asc' : 'desc';
      renderApp();
    }

    export function switchToolImpactTab(tab) {
      STATE.toolImpactTab = tab;
      renderApp();
    }

    export function switchMonthlyTrendMetric(metricKey) {
      STATE.monthlyTrendMetric = metricKey;
      renderApp();
    }

    export function setToolWasteSort(key) {
      if (STATE.toolWasteSortKey === key) {
        STATE.toolWasteSortDir = (STATE.toolWasteSortDir || 'desc') === 'desc' ? 'asc' : 'desc';
      } else {
        STATE.toolWasteSortKey = key;
        STATE.toolWasteSortDir = key === 'name' ? 'asc' : 'desc';
      }
      renderApp();
    }

    export function setModelFilter(value) {
      STATE.model = value;
      STATE.page = 1;
      renderApp();
    }

    export function setPageSize(value) {
      STATE.pageSize = Number(value || 10);
      STATE.page = 1;
      renderApp();
    }

    export function changePage(delta) {
      const pages = pagedSessions();
      STATE.page = Math.max(1, Math.min(pages.pageCount, STATE.page + delta));
      renderApp();
    }

    export function switchTab(tabName) {
      STATE.activeTab = tabName;
      persistLastTab(tabName);
      renderApp();
    }

    export function switchUsagePeriod(periodName) {
      if (periodName !== 'monthly' && periodName !== 'allTime') return;
      STATE.usagePeriod = periodName;
      STATE.page = 1;
      renderApp();
    }

    export function switchTokenMode(modeName) {
      const normalized = normalizeTokenMode(modeName);
      if (STATE.tokenMode === normalized) return;
      STATE.tokenMode = normalized;
      STATE.filters.tokenMode = normalized;
      persistTokenMode();
      renderApp();
    }

    export function switchAnalysisTab(tabName) {
      STATE.analysisTab = tabName;
      renderApp();
    }

    export function switchDataTab(tabName) {
      STATE.dataTab = tabName;
      renderApp();
    }

    export function deleteSessionPrompt(sessionId) {
      const session = APP_DATA.sessions.find((item) => item.id === sessionId);
      if (!session) return;
      const title = (session.title || 'this chat').slice(0, 90);
      if (!confirm(`Delete "${title}" from the Chats tab?`)) return;
      const changed = markSessionsHidden([sessionId]);
      if (changed) renderApp();
    }

    export function setDeleteMode(mode) {
      STATE.deleteMode = mode;
      updateChatDeletePreview();
    }

    export function setDeleteAgePreset(value) {
      STATE.deleteAgePreset = value;
      updateChatDeletePreview();
    }

    export function setDeleteSpecificDate(value) {
      STATE.deleteCustomDate = value;
      updateChatDeletePreview();
    }

    export function setDeleteKeepCount(value) {
      const parsed = Number(value || 10);
      STATE.deleteKeepCount = Number.isFinite(parsed) ? Math.max(1, Math.floor(parsed)) : 10;
      const input = document.getElementById('deleteKeepCount');
      if (input && Number(input.value) !== STATE.deleteKeepCount) {
        input.value = STATE.deleteKeepCount;
      }
      updateChatDeletePreview();
    }

    export function applyChatDeletion() {
      const isCli = STATE.deleteTarget === 'cli';
      const targets = computeChatDeletionTargets();
      if (!targets.length) {
        alert(isCli ? 'No CLI sessions matched this delete rule.' : 'No chats matched this delete rule.');
        return;
      }
      if (!confirm(`Delete ${targets.length} ${isCli ? 'CLI session(s)' : 'chat(s)'} from the ${isCli ? 'CLI' : 'Chats'} tab view?`)) return;

      const changed = isCli ? markCliSessionsHidden(targets) : markSessionsHidden(targets);
      closeChatDeleteModal();
      if (changed) {
        renderApp();
      }
    }

    export function setFileSort(key) {
      if (STATE.fileSortKey === key) {
        STATE.fileSortDir = STATE.fileSortDir === 'desc' ? 'asc' : 'desc';
      } else {
        STATE.fileSortKey = key;
        STATE.fileSortDir = key === 'name' ? 'asc' : 'desc';
      }
      renderApp();
    }

    export function setToolSort(key) {
      if (STATE.toolSortKey === key) {
        STATE.toolSortDir = (STATE.toolSortDir || 'desc') === 'desc' ? 'asc' : 'desc';
      } else {
        STATE.toolSortKey = key;
        STATE.toolSortDir = key === 'name' ? 'asc' : 'desc';
      }
      renderApp();
    }

    export function toggleAutoRefresh() { /* auto-refresh disabled */ }

    export function updateRefreshInterval(value) { /* auto-refresh disabled */ }

    export function exportToJson() {
      const blob = new Blob([JSON.stringify(APP_DATA, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
      a.href = url;
      a.download = `copilot-dashboard-${ts}.json`;
      a.click();
      URL.revokeObjectURL(url);
    }

    export function scheduleRefresh() { /* auto-refresh disabled */ }
