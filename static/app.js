"use strict";

// ── State ────────────────────────────────────────────────────────────────────
let desktops = [];
let historyPage = 1;
let historyDesktopFilter = "";
let modalGuid = null;
let monitorModalGuid = null;
let _nextRunTime = null;

// SVG icon paths
const ICON_ROTATE   = `<svg width="13" height="13" viewBox="0 0 512 512" fill="currentColor"><path d="M480.1 192l7.9 0c13.3 0 24-10.7 24-24l0-144c0-9.7-5.8-18.5-14.8-22.2S477.9 .2 471 7L419.3 58.8C375 22.1 318 0 256 0 127 0 20.3 95.4 2.6 219.5 .1 237 12.2 253.2 29.7 255.7s33.7-9.7 36.2-27.1C79.2 135.5 159.3 64 256 64 300.4 64 341.2 79 373.7 104.3L327 151c-6.9 6.9-8.9 17.2-5.2 26.2S334.3 192 344 192l136.1 0zm29.4 100.5c2.5-17.5-9.7-33.7-27.1-36.2s-33.7 9.7-36.2 27.1c-13.3 93-93.4 164.5-190.1 164.5-44.4 0-85.2-15-117.7-40.3L185 361c6.9-6.9 8.9-17.2 5.2-26.2S177.7 320 168 320L24 320c-13.3 0-24 10.7-24 24L0 488c0 9.7 5.8 18.5 14.8 22.2S34.1 511.8 41 505l51.8-51.8C137 489.9 194 512 256 512 385 512 491.7 416.6 509.4 292.5z"/></svg>`;
const ICON_PEN      = `<svg width="12" height="12" viewBox="0 0 512 512" fill="currentColor"><path d="M352.9 21.2L308 66.1 445.9 204 490.8 159.1C504.4 145.6 512 127.2 512 108s-7.6-37.6-21.2-51.1L455.1 21.2C441.6 7.6 423.2 0 404 0s-37.6 7.6-51.1 21.2zM274.1 100L58.9 315.1c-10.7 10.7-18.5 24.1-22.6 38.7L.9 481.6c-2.3 8.3 0 17.3 6.2 23.4s15.1 8.5 23.4 6.2l127.8-35.5c14.6-4.1 27.9-11.8 38.7-22.6L412 237.9 274.1 100z"/></svg>`;
const ICON_CLOCK    = `<svg width="12" height="12" viewBox="0 0 512 512" fill="currentColor"><path d="M256 0a256 256 0 1 1 0 512A256 256 0 1 1 256 0zM232 120l0 136c0 8 4 15.5 10.7 20l96 64c11 7.4 25.9 4.5 33.3-6.5s4.5-25.9-6.5-33.3L280 243.2 280 120c0-13.3-10.7-24-24-24s-24 10.7-24 24z"/></svg>`;
const ICON_MONITORS = `<svg width="12" height="12" viewBox="0 0 576 512" fill="currentColor"><path d="M64 0C28.7 0 0 28.7 0 64V352c0 35.3 28.7 64 64 64H240l-10.7 32H160c-17.7 0-32 14.3-32 32s14.3 32 32 32H416c17.7 0 32-14.3 32-32s-14.3-32-32-32H346.7L336 416H512c35.3 0 64-28.7 64-64V64c0-35.3-28.7-64-64-64H64zM512 64V352H64V64H512z"/></svg>`;
const ICON_SCROLL   = `<svg width="12" height="12" viewBox="0 0 512 512" fill="currentColor"><path d="M64 96c-17.7 0-32 14.3-32 32s14.3 32 32 32H448c17.7 0 32-14.3 32-32s-14.3-32-32-32H64zm0 128c-17.7 0-32 14.3-32 32s14.3 32 32 32H448c17.7 0 32-14.3 32-32s-14.3-32-32-32H64zm0 128c-17.7 0-32 14.3-32 32s14.3 32 32 32H320c17.7 0 32-14.3 32-32s-14.3-32-32-32H64z"/></svg>`;

// ── Init ─────────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  loadConfig();
  loadDesktops();
  fetchStatus();
  refreshClaudeStatus();
  setInterval(updateCountdown, 30000);
  setInterval(refreshClaudeStatus, 15000);

  document.getElementById("btn-generate-all").addEventListener("click", generateAll);
  document.getElementById("btn-save-settings").addEventListener("click", saveSettings);
  document.getElementById("btn-settings").addEventListener("click", openSettingsModal);
});

// ── Background ───────────────────────────────────────────────────────────────
function setBackground(filePath) {
  if (!filePath) return;
  const url = `/output/${encodeImagePath(filePath)}`;
  const bg = document.getElementById("bg-layer");
  // Preload to avoid flash
  const img = new Image();
  img.onload = () => { bg.style.backgroundImage = `url('${url}')`; };
  img.src = url;
}

function pickBackgroundFromDesktops(list) {
  // Prefer the current active desktop's wallpaper, else any with a wallpaper
  const current = list.find(d => d.is_current && d.active_wallpaper);
  const any = list.find(d => d.active_wallpaper);
  const chosen = current || any;
  if (chosen?.active_wallpaper?.file_path) {
    setBackground(chosen.active_wallpaper.file_path);
  }
}

// ── Settings modal ───────────────────────────────────────────────────────────
let _statusInterval = null;

function openSettingsModal() {
  document.getElementById("settings-modal").style.display = "flex";
  fetchStatus();
  _statusInterval = setInterval(fetchStatus, 5000);
}
function closeSettingsModal(e) {
  if (e && e.target !== document.getElementById("settings-modal")) return;
  document.getElementById("settings-modal").style.display = "none";
  clearInterval(_statusInterval);
  _statusInterval = null;
}

// ── History modal ────────────────────────────────────────────────────────────
function closeHistoryModal(e) {
  if (e && e.target !== document.getElementById("history-modal")) return;
  document.getElementById("history-modal").style.display = "none";
}

// ── ComfyUI status ────────────────────────────────────────────────────────────
function updateCountdown() {
  const el = document.getElementById("next-run-label");
  if (!el) return;
  if (!_nextRunTime) { el.textContent = ""; return; }
  const ms = new Date(_nextRunTime) - Date.now();
  if (ms <= 60000) { el.textContent = ""; return; }
  const h = Math.floor(ms / 3600000);
  const m = Math.floor((ms % 3600000) / 60000);
  el.textContent = h > 0 ? `in ${h}h ${m}m` : `in ${m}m`;
}

async function fetchStatus() {
  const dot    = document.getElementById("comfyui-dot");
  const label  = document.getElementById("comfyui-label");
  const genBtn = document.getElementById("btn-generate-all");
  try {
    const data = await api("/api/comfyui/status");
    _nextRunTime = data.next_scheduled ?? null;
    updateCountdown();
    if (dot && label) {
      if (data.running) {
        const busy = data.generating;
        dot.className = `status-dot ${busy ? "dot-busy" : "dot-ok"}`;
        label.textContent = busy ? "busy" : "online";
      } else {
        dot.className = "status-dot dot-err";
        label.textContent = "offline";
      }
    }
    if (genBtn) genBtn.disabled = !!data.generating;
  } catch {
    if (dot) { dot.className = "status-dot dot-unknown"; label.textContent = ""; }
    if (genBtn) genBtn.disabled = false;
  }
}

async function refreshClaudeStatus() {
  const dot   = document.getElementById("claude-dot");
  const label = document.getElementById("claude-label");
  if (!dot || !label) return;
  try {
    const data = await api("/api/comfyui/claude-status");
    if (data.found) {
      dot.className = "status-dot dot-ok";
      label.textContent = "claude found";
    } else {
      dot.className = "status-dot dot-err";
      label.textContent = data.path ? "not found at path" : "not configured";
    }
  } catch {
    dot.className = "status-dot dot-unknown";
    label.textContent = "unknown";
  }
}

// ── Desktops ──────────────────────────────────────────────────────────────────
async function loadDesktops(animate = false) {
  const grid = document.getElementById("desktops-grid");
  try {
    desktops = await api("/api/desktops");

    grid.innerHTML = "";
    desktops.forEach(d => grid.appendChild(makeDesktopCard(d)));

    if (animate) {
      grid.querySelectorAll(".desktop-thumb").forEach(img => {
        img.classList.add("pixel-reveal");
        img.addEventListener("animationend", () => img.classList.remove("pixel-reveal"), { once: true });
      });
    }

    // Update blurred background from wallpapers
    pickBackgroundFromDesktops(desktops);
  } catch (e) {
    grid.innerHTML = `<div class="loading-msg">Failed to load: ${e.message}</div>`;
  }
}

const MODE_CYCLE  = { shared: 'individual', individual: 'off', off: 'shared' };
const MODE_LABEL  = { shared: 'Shared', individual: 'Solo', off: 'Off' };
const MODE_ICON   = {
  shared:     `<svg width="9" height="9" viewBox="0 0 640 512" fill="currentColor"><path d="M579.8 267.7c56.5-56.5 56.5-148 0-204.5c-50-50-128.8-56.5-186.3-15.4l-1.6 1.1c-14.4 10.3-17.7 30.3-7.4 44.6s30.3 17.7 44.6 7.4l1.6-1.1c32.1-22.9 76-19.3 103.8 8.6c31.5 31.5 31.5 82.5 0 114L422.3 334.8c-31.5 31.5-82.5 31.5-114 0c-27.9-27.9-31.5-71.8-8.6-103.8l1.1-1.6c10.3-14.4 6.9-34.4-7.4-44.6s-34.4-6.9-44.6 7.4l-1.1 1.6C206.5 251.2 213 330 263 380c56.5 56.5 148 56.5 204.5 0L579.8 267.7zM60.2 244.3c-56.5 56.5-56.5 148 0 204.5c50 50 128.8 56.5 186.3 15.4l1.6-1.1c14.4-10.3 17.7-30.3 7.4-44.6s-30.3-17.7-44.6-7.4l-1.6 1.1c-32.1 22.9-76 19.3-103.8-8.6C74 372.1 74 321.1 105.5 289.5L217.7 177.2c31.5-31.5 82.5-31.5 114 0c27.9 27.9 31.5 71.8 8.6 103.8l-1.1 1.6c-10.3 14.4-6.9 34.4 7.4 44.6s34.4 6.9 44.6-7.4l1.1-1.6C433.5 260.8 427 182 377 132c-56.5-56.5-148-56.5-204.5 0L60.2 244.3z"/></svg>`,
  individual: `<svg width="9" height="9" viewBox="0 0 512 512" fill="currentColor"><path d="M0 96C0 60.7 28.7 32 64 32H448c35.3 0 64 28.7 64 64V416c0 35.3-28.7 64-64 64H64c-35.3 0-64-28.7-64-64V96zm64 0V416H448V96H64z"/></svg>`,
  off:        `<svg width="9" height="9" viewBox="0 0 384 512" fill="currentColor"><path d="M342.6 150.6c12.5-12.5 12.5-32.8 0-45.3s-32.8-12.5-45.3 0L192 210.7 86.6 105.4c-12.5-12.5-32.8-12.5-45.3 0s-12.5 32.8 0 45.3L146.7 256 41.4 361.4c-12.5 12.5-12.5 32.8 0 45.3s32.8 12.5 45.3 0L192 301.3 297.4 406.6c12.5 12.5 32.8 12.5 45.3 0s12.5-32.8 0-45.3L237.3 256 342.6 150.6z"/></svg>`,
};

function makeDesktopCard(d) {
  const card = document.createElement("div");
  card.className = "desktop-card";

  const monitors = d.monitors || [];
  const wp = d.active_wallpaper;

  // Main wallpaper thumbnail
  const mainThumbHtml = wp
    ? `<img class="desktop-thumb" src="/output/${encodeImagePath(wp.file_path)}" alt="" loading="lazy">`
    : `<div class="desktop-thumb-placeholder">
         <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1" opacity=".18"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21,15 16,10 5,21"/></svg>
         <span>No wallpaper yet</span>
       </div>`;

  // Mini monitor strip — each thumbnail at correct aspect ratio, click to cycle mode
  const monitorsStripHtml = monitors.length ? `
    <div class="monitors-strip">
      ${monitors.map(mon => {
        const ratio = mon.width && mon.height ? (mon.width / mon.height) : (16 / 9);
        const mode = mon.mode || 'shared';
        // Prefer the actual Windows-reported wallpaper; fall back to DB record
        const wpUrl = mon.current_wallpaper_path
          ? `/output/${encodeImagePath(mon.current_wallpaper_path)}`
          : (mon.active_wallpaper ? `/output/${encodeImagePath(mon.active_wallpaper.file_path)}` : null);
        const imgHtml = wpUrl
          ? `<img class="mon-thumb-img" src="${wpUrl}" alt="" loading="lazy">`
          : `<div class="mon-thumb-empty"></div>`;
        return `
          <div class="mon-thumb mode-${mode}"
               style="aspect-ratio:${ratio.toFixed(4)}"
               data-guid="${d.guid}"
               data-path="${esc(mon.monitor_device_path)}"
               data-index="${mon.monitor_index}"
               onclick="cycleMonitorMode(event)"
               title="${MODE_LABEL[mode]} — click to cycle">
            ${imgHtml}
            <span class="mon-mode-icon">${MODE_ICON[mode]}</span>
          </div>`;
      }).join('')}
    </div>` : '';

  const genTime = wp ? `Generated ${relativeTime(wp.generated_at)}` : "Not yet generated";

  const themeText = d.theme
    ? `<span class="prompt-text">${esc(d.theme)}</span>`
    : `<span class="prompt-text empty">No theme set</span>`;

  const promptPeekHtml = wp?.prompt_text
    ? `<div class="prompt-peek-wrap" data-prompt="${esc(wp.prompt_text)}">
         <button class="icon-btn prompt-peek-btn" tabindex="-1">${ICON_SCROLL}</button>
       </div>`
    : '';

  card.innerHTML = `
    <div class="desktop-thumb-wrap">
      ${mainThumbHtml}
      ${monitorsStripHtml}
    </div>
    <div class="desktop-body">
      <div class="desktop-name">${esc(d.name)}</div>
      <div class="desktop-meta">${genTime}</div>
      <div class="prompt-display" onclick="openPromptModal('${d.guid}', '${esc(d.name)}')">
        ${themeText}
        <span class="prompt-edit-hint">${ICON_PEN}</span>
      </div>
      <div class="desktop-actions">
        <button class="icon-btn icon-btn-gold" title="Regenerate" onclick="generateOne('${d.guid}', this)">
          ${ICON_ROTATE}
        </button>
        ${wp ? `<button class="icon-btn" title="History" onclick="viewHistory('${d.guid}')">${ICON_CLOCK}</button>` : ""}
        ${promptPeekHtml}
      </div>
    </div>`;

  return card;
}

async function cycleMonitorMode(event) {
  event.stopPropagation();
  const thumb = event.currentTarget;
  const guid = thumb.dataset.guid;
  const path = thumb.dataset.path;

  const desktop = desktops.find(d => d.guid === guid);
  if (!desktop?.monitors) return;

  const mon = desktop.monitors.find(m => m.monitor_device_path === path);
  if (!mon) return;

  const oldMode = mon.mode || 'shared';
  const newMode = MODE_CYCLE[oldMode];
  mon.mode = newMode;

  // Optimistic UI update
  thumb.classList.replace(`mode-${oldMode}`, `mode-${newMode}`);
  thumb.title = `${MODE_LABEL[newMode]} — click to cycle`;
  const icon = thumb.querySelector('.mon-mode-icon');
  if (icon) icon.innerHTML = MODE_ICON[newMode];

  try {
    await api(`/api/desktops/${guid}/monitors`, 'PUT', {
      monitors: desktop.monitors.map(m => ({
        monitor_device_path: m.monitor_device_path,
        monitor_index: m.monitor_index,
        mode: m.mode || 'shared',
      })),
    });
  } catch (e) {
    // Revert
    mon.mode = oldMode;
    thumb.classList.replace(`mode-${newMode}`, `mode-${oldMode}`);
    thumb.title = `${MODE_LABEL[oldMode]} — click to cycle`;
    if (icon) icon.innerHTML = MODE_ICON[oldMode];
  }
}

// ── Theme prompt modal ────────────────────────────────────────────────────────
function openPromptModal(guid, name) {
  modalGuid = guid;
  const desktop = desktops.find(d => d.guid === guid);
  document.getElementById("modal-desktop-name").textContent = name;
  document.getElementById("modal-theme-input").value = desktop?.theme || "";
  document.getElementById("prompt-modal").style.display = "flex";
  setTimeout(() => document.getElementById("modal-theme-input").focus(), 50);
}

function closePromptModal(e) {
  if (e && e.target !== document.getElementById("prompt-modal")) return;
  document.getElementById("prompt-modal").style.display = "none";
  modalGuid = null;
}

async function saveModal() {
  if (!modalGuid) return;
  const btn = document.getElementById("modal-save-btn");
  btn.disabled = true;
  const theme = document.getElementById("modal-theme-input").value.trim();
  try {
    await api(`/api/desktops/${modalGuid}/theme`, "POST", { theme });
    document.getElementById("prompt-modal").style.display = "none";
    modalGuid = null;
    loadDesktops();
  } catch (e) {
    alert("Failed to save: " + e.message);
  } finally {
    btn.disabled = false;
  }
}

async function generateOne(guid, btn) {
  btn.disabled = true;
  btn.style.opacity = ".4";
  showProgress("Generating wallpaper…");
  try {
    await api("/api/comfyui/generate", "POST", { desktop_guid: guid });
    pollUntilDone(() => { hideProgress(); loadDesktops(true); fetchStatus(); btn.disabled = false; btn.style.opacity = ""; });
  } catch (e) {
    hideProgress();
    alert("Generation failed: " + e.message);
    btn.disabled = false;
    btn.style.opacity = "";
  }
}

async function generateAll() {
  const btn = document.getElementById("btn-generate-all");
  btn.disabled = true;
  showProgress("Generating wallpapers for all desktops…");
  try {
    await api("/api/comfyui/generate", "POST", { all: true });
    pollUntilDone(() => { hideProgress(); loadDesktops(true); fetchStatus(); });
  } catch (e) {
    hideProgress();
    alert("Generation failed: " + e.message);
    btn.disabled = false;
  }
}

function pollUntilDone(onDone) {
  const check = async () => {
    const status = await api("/api/comfyui/status").catch(() => null);
    if (!status || !status.generating) { onDone(); return; }
    if (status.progress) {
      const p = status.progress;
      // Desktop name / label
      document.getElementById("progress-desktop").textContent = p.label || "";
      // Progress bar — combine desktop + image progress
      const desktopFrac = p.desktop_total > 0
        ? (p.desktop_current - 1) / p.desktop_total
        : 0;
      const imageFrac = p.image_total > 0
        ? (p.image_current / p.image_total) / (p.desktop_total || 1)
        : 0;
      const pct = Math.round((desktopFrac + imageFrac) * 100);
      document.getElementById("progress-bar").style.width = pct + "%";
      // Image count within desktop
      const imgCountEl = document.getElementById("progress-image-count");
      if (p.image_total > 1) {
        imgCountEl.textContent = `Image ${p.image_current || "…"} of ${p.image_total}`;
      } else if (p.image_total === 1) {
        imgCountEl.textContent = "Generating image…";
      } else {
        imgCountEl.textContent = "";
      }
      // Desktop counter if multiple desktops
      const textEl = document.getElementById("progress-text");
      if (p.desktop_total > 1) {
        textEl.textContent = `Desktop ${p.desktop_current} of ${p.desktop_total}`;
      } else {
        textEl.textContent = "Generating…";
      }
      // Prompt
      const promptEl = document.getElementById("progress-prompt");
      promptEl.textContent = p.prompt || "";
    }
    setTimeout(check, 3000);
  };
  setTimeout(check, 3000);
}

function viewHistory(guid) {
  const desktop = desktops.find(d => d.guid === guid);
  document.getElementById("history-modal-desktop").textContent = desktop ? desktop.name : "";
  historyDesktopFilter = guid;
  historyPage = 1;
  document.getElementById("history-modal").style.display = "flex";
  loadHistory();
}

// ── History ───────────────────────────────────────────────────────────────────
async function loadHistory() {
  const grid = document.getElementById("history-grid");
  grid.innerHTML = '<div class="loading-msg">Loading…</div>';
  try {
    const params = new URLSearchParams({ page: historyPage, per_page: 30 });
    if (historyDesktopFilter) params.set("desktop_guid", historyDesktopFilter);
    const items = await api(`/api/wallpapers?${params}`);
    grid.innerHTML = "";
    if (!items.length) {
      grid.innerHTML = '<div class="loading-msg">No wallpapers yet.</div>';
      return;
    }
    items.forEach(wp => grid.appendChild(makeHistoryCard(wp)));
    renderPagination();
  } catch (e) {
    grid.innerHTML = `<div class="loading-msg">Error: ${e.message}</div>`;
  }
}

function makeHistoryCard(wp) {
  const card = document.createElement("div");
  card.className = "history-card" + (wp.is_active ? " active" : "");
  const url = `/output/${encodeImagePath(wp.file_path)}`;
  card.innerHTML = `
    <img class="history-thumb" src="${url}" alt="" loading="lazy">
    <div class="history-card-meta">${relativeTime(wp.generated_at)}</div>`;
  card.addEventListener("click", () => applyWallpaper(wp.id, card));
  return card;
}

async function applyWallpaper(id, card) {
  card.style.opacity = ".5";
  try {
    await api(`/api/wallpapers/${id}/apply`, "POST");
    document.querySelectorAll(".history-card").forEach(c => c.classList.remove("active"));
    card.classList.add("active");
    loadDesktops();
  } catch (e) {
    alert("Failed to apply: " + e.message);
  } finally {
    card.style.opacity = "";
  }
}

function renderPagination() {
  const el = document.getElementById("history-pagination");
  el.innerHTML = "";
  if (historyPage > 1) {
    const prev = el.appendChild(document.createElement("button"));
    prev.textContent = "← Prev";
    prev.onclick = () => { historyPage--; loadHistory(); };
  }
  const cur = el.appendChild(document.createElement("button"));
  cur.textContent = `Page ${historyPage}`;
  cur.className = "active";
  const next = el.appendChild(document.createElement("button"));
  next.textContent = "Next →";
  next.onclick = () => { historyPage++; loadHistory(); };
}

// ── Settings ──────────────────────────────────────────────────────────────────
async function loadConfig() {
  try {
    const cfg = await api("/api/config");
    document.getElementById("cfg-cron").value           = cfg.schedule_cron ?? "";
    document.getElementById("cfg-default-prompt").value = cfg.default_prompt ?? "";
    document.getElementById("cfg-negative-prompt").value= cfg.negative_prompt ?? "";
    document.getElementById("cfg-pos-node").value       = cfg.positive_prompt_node_id ?? "";
    document.getElementById("cfg-neg-node").value       = cfg.negative_prompt_node_id ?? "";
    document.getElementById("cfg-comfyui-port").value   = cfg.comfyui_port ?? 8188;
    document.getElementById("cfg-claude-path").value    = cfg.claude_path ?? "";
  } catch {}
}

async function saveSettings() {
  const btn    = document.getElementById("btn-save-settings");
  const status = document.getElementById("settings-status");
  btn.disabled = true;
  status.textContent = "";
  try {
    await api("/api/config", "POST", {
      schedule_cron:           document.getElementById("cfg-cron").value,
      default_prompt:          document.getElementById("cfg-default-prompt").value,
      negative_prompt:         document.getElementById("cfg-negative-prompt").value,
      positive_prompt_node_id: document.getElementById("cfg-pos-node").value || null,
      negative_prompt_node_id: document.getElementById("cfg-neg-node").value || null,
      comfyui_port:            parseInt(document.getElementById("cfg-comfyui-port").value, 10) || 8188,
      claude_path:             document.getElementById("cfg-claude-path").value.trim() || null,
    });
    status.textContent = "Saved!";
    setTimeout(() => status.textContent = "", 2000);
  } catch (e) {
    status.textContent = "Error: " + e.message;
    status.style.color = "#f87171";
  } finally {
    btn.disabled = false;
  }
}

// ── Monitor modal ─────────────────────────────────────────────────────────────
async function openMonitorModal(guid, name) {
  monitorModalGuid = guid;
  document.getElementById("monitor-modal-desktop").textContent = name;
  document.getElementById("monitor-modal").style.display = "flex";
  document.getElementById("monitor-list").innerHTML = '<div class="loading-msg">Detecting monitors…</div>';

  try {
    const [systemMonitors, desktopConfig] = await Promise.all([
      api("/api/monitors"),
      api(`/api/desktops/${guid}/monitors`),
    ]);

    // Merge: use detected monitors (system source of truth) with desktop config overlaid
    const configMap = Object.fromEntries(
      (desktopConfig.monitors || []).map(m => [m.monitor_device_path, m])
    );

    const monitors = systemMonitors.map(sm => ({
      device_path: sm.device_path,
      index: sm.index,
      disabled: configMap[sm.device_path]?.disabled ?? false,
    }));

    renderMonitorList(monitors);

    // Set mode radio
    const mode = desktopConfig.wallpaper_mode || "repeated";
    document.querySelector(`input[name="monitor-mode"][value="${mode}"]`).checked = true;
  } catch (e) {
    document.getElementById("monitor-list").innerHTML =
      `<div class="loading-msg">Error: ${e.message}</div>`;
  }
}

function renderMonitorList(monitors) {
  const list = document.getElementById("monitor-list");
  if (!monitors.length) {
    list.innerHTML = '<div class="loading-msg">No monitors detected.</div>';
    return;
  }
  list.innerHTML = monitors.map((mon, i) => {
    const label = `Monitor ${mon.index + 1}`;
    const path  = mon.device_path || "unknown";
    const checked = mon.disabled ? "" : "checked";
    return `
      <div class="monitor-row">
        <label class="toggle-switch">
          <input type="checkbox" ${checked} data-path="${esc(mon.device_path)}" data-index="${mon.index}">
          <span class="toggle-track"></span>
        </label>
        <div class="monitor-label">
          <div>${label}</div>
          <div class="monitor-path">${esc(path)}</div>
        </div>
      </div>`;
  }).join("");
}

function closeMonitorModal(e) {
  if (e && e.target !== document.getElementById("monitor-modal")) return;
  document.getElementById("monitor-modal").style.display = "none";
  monitorModalGuid = null;
}

async function saveMonitorConfig() {
  if (!monitorModalGuid) return;
  const btn = document.getElementById("monitor-save-btn");
  btn.disabled = true;

  const mode = document.querySelector('input[name="monitor-mode"]:checked')?.value || "repeated";

  const monitors = Array.from(
    document.querySelectorAll("#monitor-list input[type=checkbox]")
  ).map(cb => ({
    monitor_device_path: cb.dataset.path,
    monitor_index: parseInt(cb.dataset.index, 10),
    disabled: !cb.checked,
  }));

  try {
    await api(`/api/desktops/${monitorModalGuid}/monitors`, "PUT", { mode, monitors });
    document.getElementById("monitor-modal").style.display = "none";
    monitorModalGuid = null;
  } catch (e) {
    alert("Failed to save: " + e.message);
  } finally {
    btn.disabled = false;
  }
}

// ── Progress ──────────────────────────────────────────────────────────────────
function showProgress(msg) {
  document.getElementById("progress-text").textContent = msg || "Working…";
  document.getElementById("progress-desktop").textContent = "";
  document.getElementById("progress-image-count").textContent = "";
  document.getElementById("progress-prompt").textContent = "";
  document.getElementById("progress-bar").style.width = "0%";
  document.getElementById("progress-overlay").style.display = "flex";
}
function hideProgress() {
  document.getElementById("progress-overlay").style.display = "none";
}

// ── Helpers ───────────────────────────────────────────────────────────────────
async function api(path, method = "GET", body = null) {
  const opts = { method, headers: {} };
  if (body) { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
  const res = await fetch(path, opts);
  if (!res.ok) { const t = await res.text().catch(() => ""); throw new Error(`${res.status}: ${t}`); }
  return res.json();
}

function esc(str) {
  return String(str).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// Normalize active_prompt — old server returns a plain string, new server returns an object
function normalizePrompt(raw) {
  if (!raw) return null;
  if (typeof raw === "string") return { text: raw, is_ai_generated: false };
  return raw;
}

function encodeImagePath(filePath) {
  const base = filePath.replace(/\\/g, "/");
  const idx = base.indexOf("/output/");
  if (idx !== -1) return base.slice(idx + "/output/".length);
  return encodeURIComponent(base);
}

function relativeTime(isoStr) {
  const diff = Date.now() - new Date(isoStr + (isoStr.endsWith("Z") ? "" : "Z")).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1)   return "just now";
  if (m < 60)  return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24)  return `${h}h ago`;
  const d = Math.floor(h / 24);
  return `${d}d ago`;
}
