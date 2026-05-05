/* =====================================================
   EMBER MEMORY CONTROLLER v2
   Pure JS — pywebview API wrapper
   ===================================================== */

// ── Helpers ───────────────────────────────────────────
var toastTimer = null;
function showToast(msg, type) {
  var el = document.getElementById('toast');
  el.textContent = msg;
  el.className = 'toast show ' + (type || 'inf');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(function() { el.classList.remove('show'); }, 3500);
}

function nowStr() {
  var d = new Date();
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function safeNum(v, fallback) {
  var n = parseFloat(v);
  return isNaN(n) ? (fallback || 0) : n;
}

function formatActivityTime(ts) {
  if (ts === null || ts === undefined || ts === '') return '--:--:--';
  var value = ts;
  if (typeof value === 'number') {
    if (value < 1000000000000) value = value * 1000;
  } else if (/^\d+(\.\d+)?$/.test(String(value))) {
    value = Number(value);
    if (value < 1000000000000) value = value * 1000;
  }
  var date = new Date(value);
  if (isNaN(date.getTime())) return '--:--:--';
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

// Safe wrapper around pywebview API calls
function callApi(method) {
  var args = Array.prototype.slice.call(arguments, 1);
  try {
    var fn = window.pywebview && window.pywebview.api && window.pywebview.api[method];
    if (!fn) return Promise.resolve({ ok: false, msg: 'API not ready' });
    return Promise.resolve(fn.apply(window.pywebview.api, args));
  } catch (e) {
    return Promise.resolve({ ok: false, msg: String(e) });
  }
}

// Create DOM element with text content safely
function el(tag, cls, text) {
  var e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined && text !== null) e.textContent = String(text);
  return e;
}

function setTextById(id, text) {
  var e = document.getElementById(id);
  if (e) e.textContent = String(text);
}

function copyTextToClipboard(text) {
  if (navigator.clipboard && navigator.clipboard.writeText) {
    return navigator.clipboard.writeText(text);
  }

  return new Promise(function(resolve, reject) {
    var area = document.createElement('textarea');
    area.value = text;
    area.setAttribute('readonly', 'readonly');
    area.style.position = 'fixed';
    area.style.opacity = '0';
    area.style.pointerEvents = 'none';
    document.body.appendChild(area);
    area.focus();
    area.select();

    try {
      var ok = document.execCommand('copy');
      document.body.removeChild(area);
      if (ok) resolve();
      else reject(new Error('Clipboard copy failed'));
    } catch (err) {
      document.body.removeChild(area);
      reject(err);
    }
  });
}

function openExternalUrl(url) {
  return callApi('open_external_url', url).then(function(r) {
    if (!r || !r.ok) {
      window.location.href = url;
    }
  });
}

// ── Tab switching ─────────────────────────────────────
function activateTab(tab) {
  document.querySelectorAll('.tab-btn').forEach(function(b) {
    b.classList.toggle('active', b.getAttribute('data-tab') === tab);
  });
  document.querySelectorAll('.tab-panel').forEach(function(p) { p.classList.remove('active'); });
  var panel = document.getElementById('tab-' + tab);
  if (panel) panel.classList.add('active');

  if (tab === 'dashboard') {
    startDashRefresh();
  } else {
    stopDashRefresh();
    if (tab === 'collections') {
      loadCollections();
      loadWorkspaces();
    }
    else if (tab === 'settings') {
      loadSettings();
      loadLaunchDirs();
    }
    else if (tab === 'cli') {
      loadCLIStatus();
      loadDesktopLauncherStatus();
    }
  }
}

function initTabs() {
  document.querySelectorAll('.tab-btn').forEach(function(btn) {
    btn.addEventListener('click', function() {
      activateTab(btn.getAttribute('data-tab'));
    });
  });
}

// =====================================================
// DASHBOARD
// =====================================================

// Force graph removed — replaced with connection table
var currentAiFilter = 'all';
var currentSessionFilter = '';
var aiDisplayNames = {
  all: 'All',
  shared: 'Shared',
  claude: 'Claude',
  gemini: 'Gemini',
  codex: 'Codex'
};

function setEngineAlive(alive) {
  document.getElementById('engineDot').classList.toggle('live', alive);
  setTextById('enginePillLabel', alive ? 'Engine Live' : 'Engine');
}

function getDashboardAiId() {
  return currentAiFilter === 'all' ? null : currentAiFilter;
}

function getDashboardScopeId() {
  return currentSessionFilter || getDashboardAiId();
}

function resetSessionFilterOptions(select) {
  if (!select) return;
  select.textContent = '';
  var option = document.createElement('option');
  option.value = '';
  option.textContent = 'All Sessions';
  select.appendChild(option);
}

function buildSessionOptionLabel(session) {
  var preview = String((session && session.last_prompt) || '').trim();
  var count = safeNum(session && session.count, 0);
  var parts = [String((session && session.id) || '')];
  if (preview) parts.push(preview);
  parts.push(String(count) + ' msgs');
  return parts.join(' | ');
}

function updateSessionFilterVisibility() {
  var wrap = document.getElementById('sessionFilterWrap');
  var select = document.getElementById('sessionFilter');
  if (!wrap) return;

  var visible = currentAiFilter !== 'all';
  wrap.classList.toggle('visible', visible);
  if (!visible) {
    currentSessionFilter = '';
    resetSessionFilterOptions(select);
    if (select) select.value = '';
  }
}

function populateSessionFilterOptions(sessions) {
  var select = document.getElementById('sessionFilter');
  if (!select) return;

  var selected = currentSessionFilter;
  var available = {};
  resetSessionFilterOptions(select);

  (sessions || []).forEach(function(session) {
    var option = document.createElement('option');
    var sessionId = String((session && session.id) || '');
    if (!sessionId) return;
    option.value = sessionId;
    option.textContent = buildSessionOptionLabel(session);
    available[sessionId] = true;
    select.appendChild(option);
  });

  if (selected && available[selected]) {
    select.value = selected;
  } else {
    currentSessionFilter = '';
    select.value = '';
  }
}

function refreshSessionFilter() {
  if (currentAiFilter === 'all') {
    updateSessionFilterVisibility();
    return Promise.resolve({ ok: true, sessions: [] });
  }

  updateSessionFilterVisibility();
  return callApi('get_recent_sessions', currentAiFilter).then(function(r) {
    if (r && r.ok) populateSessionFilterOptions(r.sessions);
    return r;
  });
}

function initSessionFilter() {
  var select = document.getElementById('sessionFilter');
  if (!select || select.getAttribute('data-ready') === 'true') return;
  select.setAttribute('data-ready', 'true');
  resetSessionFilterOptions(select);
  updateSessionFilterVisibility();
  select.addEventListener('change', function() {
    currentSessionFilter = select.value || '';
    loadDashboard();
  });
}

function getAiDisplayName(aiId) {
  var value = String(aiId || '').toLowerCase();
  return aiDisplayNames[value] || (value || 'All');
}

function updateAiFilterButtons() {
  document.querySelectorAll('.ai-filter-btn').forEach(function(btn) {
    btn.classList.toggle('active', btn.getAttribute('data-ai') === currentAiFilter);
  });
}

function registerAiDisplayName(aiId, name) {
  var key = String(aiId || '').toLowerCase();
  if (!key) return;
  aiDisplayNames[key] = String(name || aiId);
}

function wireAiFilterButtons() {
  document.querySelectorAll('.ai-filter-btn').forEach(function(btn) {
    if (btn.getAttribute('data-bound') === 'true') return;
    btn.setAttribute('data-bound', 'true');
    btn.addEventListener('click', function() {
      var nextFilter = btn.getAttribute('data-ai') || 'all';
      if (nextFilter === currentAiFilter) return;
      currentAiFilter = nextFilter;
      currentSessionFilter = '';
      updateAiFilterButtons();
      loadDashboard();
    });
  });
}

function renderCustomCliFilters(clis) {
  var bar = document.getElementById('aiFilterBar');
  var scopeSel = document.getElementById('importScope');
  var validFilters = { all: true, claude: true, gemini: true, codex: true };
  if (!bar) return;

  bar.querySelectorAll('[data-custom-cli="true"]').forEach(function(btn) {
    btn.remove();
  });
  if (scopeSel) {
    scopeSel.querySelectorAll('[data-custom-cli="true"]').forEach(function(opt) {
      opt.remove();
    });
  }

  (clis || []).forEach(function(c) {
    var cliId = String((c && c.id) || '').trim().toLowerCase();
    if (!cliId) return;
    var cliName = String((c && c.name) || cliId);
    validFilters[cliId] = true;
    registerAiDisplayName(cliId, cliName);

    var btn = document.createElement('button');
    btn.className = 'ai-filter-btn';
    btn.setAttribute('data-ai', cliId);
    btn.setAttribute('data-custom-cli', 'true');
    btn.textContent = cliName;
    bar.appendChild(btn);

    if (scopeSel) {
      var opt = document.createElement('option');
      opt.value = cliId;
      opt.textContent = cliName;
      opt.setAttribute('data-custom-cli', 'true');
      scopeSel.appendChild(opt);
    }
  });

  if (!validFilters[currentAiFilter]) {
    currentAiFilter = 'all';
    currentSessionFilter = '';
  }
  wireAiFilterButtons();
  updateAiFilterButtons();
}

function initAiFilters() {
  var bar = document.getElementById('aiFilterBar');
  if (!bar || bar.getAttribute('data-ready') === 'true') return;
  bar.setAttribute('data-ready', 'true');
  wireAiFilterButtons();

  callApi('get_custom_clis').then(function(r) {
    renderCustomCliFilters((r && r.ok && r.clis) ? r.clis : []);
  });
}

// Test Query
document.getElementById('btnTestQuery').addEventListener('click', function() {
  var input = document.getElementById('testQueryInput');
  var area = document.getElementById('testQueryResults');
  var query = input ? input.value.trim() : '';
  if (!query) return;

  area.textContent = '';
  var loading = document.createElement('div');
  loading.className = 'loading-text';
  var spin = document.createElement('div');
  spin.className = 'spinner';
  loading.appendChild(spin);
  loading.appendChild(el('span', null, ' Searching...'));
  area.appendChild(loading);

  callApi('test_query', query).then(function(r) {
    area.textContent = '';
    if (!r || !r.ok || !r.results || r.results.length === 0) {
      var empty = el('div', 'empty-state', 'No results found');
      empty.style.fontSize = '12px';
      empty.style.padding = '8px';
      area.appendChild(empty);
      return;
    }

    var header = document.createElement('div');
    header.style.cssText = 'font-size:10px; color:var(--fg-muted); margin-bottom:6px; font-family:var(--font-mono);';
    header.textContent = r.results.length + ' results in ' + (r.elapsed_ms || '?') + 'ms';
    area.appendChild(header);

    r.results.forEach(function(result) {
      var card = document.createElement('div');
      card.className = 'retrieval-result';

      var hdr = document.createElement('div');
      hdr.className = 'retrieval-result-hdr';
      var colName = document.createElement('span');
      colName.className = 'retrieval-result-collection';
      colName.textContent = result.collection;
      hdr.appendChild(colName);
      var scoreText = document.createElement('span');
      scoreText.className = 'retrieval-result-score';
      var simPct = Math.round((result.similarity || 0) * 100);
      var compPct = Math.round((result.composite_score || 0) * 100);
      scoreText.textContent = simPct + '% sim \u2022 ' + compPct + '% composite';
      hdr.appendChild(scoreText);
      card.appendChild(hdr);

      var content = document.createElement('div');
      content.className = 'retrieval-result-content';
      content.style.maxHeight = '100px';
      content.style.overflow = 'auto';
      content.textContent = result.content || '(empty)';
      card.appendChild(content);

      // X-Ray bar if breakdown available
      if (result.score_breakdown) {
        var bd = result.score_breakdown;
        var xbar = document.createElement('div');
        xbar.className = 'xray-bar';
        var total = (bd.composite_score || 0.01);
        var factors = [
          { cls: 'xray-seg-sim', val: (bd.similarity || 0) * 0.40 },
          { cls: 'xray-seg-heat', val: (bd.heat_boost || 0) * 0.25 },
          { cls: 'xray-seg-conn', val: (bd.connection_bonus || 0) * 0.20 },
          { cls: 'xray-seg-decay', val: (bd.decay_factor || 0) * 0.15 },
        ];
        factors.forEach(function(f) {
          var seg = document.createElement('div');
          seg.className = 'xray-seg ' + f.cls;
          seg.style.width = Math.max(2, Math.round(f.val / total * 100)) + '%';
          xbar.appendChild(seg);
        });
        card.appendChild(xbar);

        var legend = document.createElement('div');
        legend.className = 'xray-legend';
        var labels = [
          { color: '#6699cc', name: 'Sim', val: bd.similarity },
          { color: '#FF7820', name: 'Heat', val: bd.heat_boost },
          { color: '#10a37f', name: 'Conn', val: bd.connection_bonus },
          { color: '#888', name: 'Decay', val: bd.decay_factor },
        ];
        labels.forEach(function(l) {
          var item = document.createElement('span');
          var dot = document.createElement('span');
          dot.className = 'xray-legend-dot';
          dot.style.background = l.color;
          item.appendChild(dot);
          var txt = document.createTextNode(l.name + ': ' + Math.round((l.val || 0) * 100) + '%');
          item.appendChild(txt);
          legend.appendChild(item);
        });
        card.appendChild(legend);
      }

      area.appendChild(card);
    });
  });
});

document.getElementById('testQueryInput').addEventListener('keydown', function(e) {
  if (e.key === 'Enter') document.getElementById('btnTestQuery').click();
});

document.getElementById('btnStartCli').addEventListener('click', function() {
  activateTab('cli');
});

document.getElementById('btnStartImport').addEventListener('click', function() {
  activateTab('collections');
  setTimeout(function() {
    var btn = document.getElementById('btnImportToggle');
    var wizard = document.getElementById('importWizard');
    if (btn && wizard && !wizard.classList.contains('visible')) btn.click();
  }, 0);
});

document.getElementById('btnStartQuery').addEventListener('click', function() {
  var input = document.getElementById('testQueryInput');
  if (input) input.focus();
});

function getCollectionDisplayName(collectionName) {
  var rawName = String(collectionName || '').trim();
  if (!rawName) return 'unknown';
  var parsed = parseOwner(rawName);
  return parsed.topic || rawName;
}

function getCollectionAccentColor(collectionName) {
  var owner = parseOwner(String(collectionName || '')).owner;
  if (owner === 'gemini') return '#4285f4';
  if (owner === 'codex') return '#10a37f';
  return 'var(--ember)';
}

function loadDashboard() {
  refreshSessionFilter().then(function() {
    callApi('get_engine_stats', getDashboardScopeId()).then(function(r) {
      if (!r || !r.ok) { setEngineAlive(false); return; }
      var s = r.stats || {};
      var memCount  = s.total_memories_tracked || 0;
      var hotCount  = s.hot_memories           || 0;
      var connCount = s.total_connections || 0;
      var tickCount = s.tick_count             || 0;
      var heatMode  = s.heat_mode              || 'universal';

      setTextById('stat-memories', memCount);
      setTextById('stat-connections', connCount);
      setTextById('stat-ticks', tickCount);
      setTextById('heatModeBadge', heatMode);

      var hotEl = document.getElementById('stat-hot');
      if (hotEl) {
        hotEl.textContent = String(hotCount);
        hotEl.className = 'stat-value' + (hotCount > 0 ? ' hot' : '');
      }

      setEngineAlive(true);
      setTextById('heatRefreshTime', nowStr());
    });

    loadActiveMemory();
    loadLastRetrieval();
    loadActivityFeed();
  });
}

function loadActiveMemory() {
  var area = document.getElementById('heatMapArea');
  callApi('get_heat_map', getDashboardScopeId()).then(function(rHeat) {
    if (!area) return;

    // Fetch connection data in parallel
    callApi('get_connections', getDashboardScopeId()).then(function(rConn) {
      var connMap = {};
      if (rConn && rConn.ok && rConn.connections) {
        rConn.connections.forEach(function(c) {
          connMap[c.source] = (connMap[c.source] || 0) + 1;
          connMap[c.target] = (connMap[c.target] || 0) + 1;
        });
      }

      if (!rHeat || !rHeat.ok || !rHeat.heat || Object.keys(rHeat.heat).length === 0) {
        area.textContent = '';
        var empt = document.createElement('div');
        empt.className = 'empty-state';
        var ico = el('div', 'empty-icon', '\uD83C\uDF21');
        var msg = el('span', null, 'No memory data yet \u2014 the Engine learns as you use it');
        empt.appendChild(ico);
        empt.appendChild(msg);
        area.appendChild(empt);
        return;
      }

      var meta = rHeat.meta || {};
      var entries = Object.entries(rHeat.heat)
        .sort(function(a, b) { return b[1] - a[1]; })
        .slice(0, 15);

      var maxVal = entries.length > 0 ? entries[0][1] : 1;
      area.textContent = '';
      entries.forEach(function(entry) {
        var id = entry[0];
        var val = entry[1];
        var norm = maxVal > 0 ? val / maxVal : 0;
        var pct  = Math.max(2, Math.round(norm * 100));
        var color = heatColor(norm);

        var m = meta[id] || {};
        var label = id.length > 18 ? '\u2026' + id.slice(-16) : id;
        var tooltip = id;
        if (m.collection) {
          var col = m.collection.replace(/^claude--|^gemini--|^codex--/, '');
          var preview = m.preview || '';
          if (preview.length > 50) preview = preview.substring(0, 50) + '\u2026';
          label = col + (preview ? ': ' + preview : '');
          if (label.length > 40) label = label.substring(0, 40) + '\u2026';
          tooltip = m.collection + ' | ' + (m.preview || id);
        }

        var row = document.createElement('div');
        row.className = 'heat-bar-row';

        var lbl = el('div', 'heat-bar-label', label);
        lbl.title = tooltip;
        row.appendChild(lbl);

        var track = document.createElement('div');
        track.className = 'heat-bar-track';
        var fill = document.createElement('div');
        fill.className = 'heat-bar-fill';
        fill.style.width = pct + '%';
        fill.style.background = color;
        track.appendChild(fill);
        row.appendChild(track);

        var valEl = el('div', 'heat-bar-val', typeof val === 'number' ? val.toFixed(1) : String(val));
        row.appendChild(valEl);

        // Connection badge
        var connCount = connMap[id] || 0;
        if (connCount > 0) {
          var connBadge = document.createElement('span');
          connBadge.className = 'heat-bar-conn-badge';
          connBadge.textContent = '\u2194 ' + connCount;
          connBadge.title = connCount + ' topic connection' + (connCount > 1 ? 's' : '');
          row.appendChild(connBadge);
        }

        area.appendChild(row);
      });
    });
  });
}

function heatColor(norm) {
  if (norm <= 0) return '#2a2a2a';
  if (norm < 0.4) {
    var t = norm / 0.4;
    var r = Math.round(42 + t * 213);
    var g = Math.round(42 + t * 118);
    return 'rgb(' + r + ',' + g + ',42)';
  }
  var t2 = (norm - 0.4) / 0.6;
  var g2 = Math.round(160 - t2 * 91);
  return 'rgb(255,' + g2 + ',0)';
}

function buildHeatBarRow(id, val, maxVal, meta) {
  var norm = maxVal > 0 ? val / maxVal : 0;
  var pct  = Math.max(2, Math.round(norm * 100));
  var color = heatColor(norm);

  // Use metadata for readable label: [collection] preview...
  var label = id.length > 18 ? '\u2026' + id.slice(-16) : id;
  var tooltip = id;
  if (meta && meta.collection) {
    var col = meta.collection.replace(/^claude--|^gemini--|^codex--/, '');
    var preview = meta.preview || '';
    if (preview.length > 50) preview = preview.substring(0, 50) + '\u2026';
    label = col + (preview ? ': ' + preview : '');
    if (label.length > 40) label = label.substring(0, 40) + '\u2026';
    tooltip = meta.collection + ' | ' + (meta.preview || id);
  }

  var row = document.createElement('div');
  row.className = 'heat-bar-row';

  var lbl = el('div', 'heat-bar-label', label);
  lbl.title = tooltip;

  var track = document.createElement('div');
  track.className = 'heat-bar-track';

  var fill = document.createElement('div');
  fill.className = 'heat-bar-fill';
  fill.style.width = pct + '%';
  fill.style.background = color;
  track.appendChild(fill);

  var valEl = el('div', 'heat-bar-val', typeof val === 'number' ? val.toFixed(1) : String(val));

  row.appendChild(lbl);
  row.appendChild(track);
  row.appendChild(valEl);

  // Build expandable detail panel
  var wrapper = document.createElement('div');
  wrapper.appendChild(row);

  if (meta && meta.preview) {
    var detail = document.createElement('div');
    detail.className = 'heat-detail';

    var colDiv = document.createElement('div');
    colDiv.className = 'heat-detail-collection';
    colDiv.textContent = meta.collection || 'unknown';
    detail.appendChild(colDiv);

    var contentDiv = document.createElement('div');
    contentDiv.className = 'heat-detail-content';
    contentDiv.textContent = meta.preview;
    detail.appendChild(contentDiv);

    var metaDiv = document.createElement('div');
    metaDiv.className = 'heat-detail-meta';
    var heatSpan = document.createElement('span');
    heatSpan.textContent = 'Heat: ' + (typeof val === 'number' ? val.toFixed(2) : val);
    var idSpan = document.createElement('span');
    idSpan.textContent = 'ID: ' + id.substring(0, 24) + '\u2026';
    metaDiv.appendChild(heatSpan);
    metaDiv.appendChild(idSpan);
    detail.appendChild(metaDiv);

    wrapper.appendChild(detail);

    row.addEventListener('click', function() {
      detail.classList.toggle('open');
    });
  }

  return wrapper;
}

function setRetrievalActionButtonState(button, active) {
  if (button) button.style.opacity = active ? '1' : '0.4';
}

function createRetrievalActionButton(icon, title, onClick) {
  var button = document.createElement('button');
  button.style.cssText = 'background:none; border:none; cursor:pointer; font-size:14px; opacity:0.4; padding:2px 6px;';
  button.textContent = icon;
  button.title = title;
  button.addEventListener('click', function(evt) {
    evt.preventDefault();
    evt.stopPropagation();
    onClick(button);
  });
  return button;
}

function closePinTopicEditor(card) {
  var existing = card.querySelector('.pin-topic-editor');
  if (existing && existing.parentNode) {
    existing.parentNode.removeChild(existing);
  }
}

function openPinTopicEditor(card, anchor, result, pinBtn) {
  var existing = card.querySelector('.pin-topic-editor');
  if (existing) {
    var existingInput = existing.querySelector('input');
    if (existingInput) existingInput.focus();
    return;
  }

  var editor = document.createElement('div');
  editor.className = 'pin-topic-editor';
  editor.style.cssText = 'display:flex; gap:6px; margin-top:6px; align-items:center; flex-wrap:wrap;';

  var input = document.createElement('input');
  input.type = 'text';
  input.placeholder = 'Pin for topic';
  input.style.cssText = 'flex:1; min-width:160px; background:var(--bg-surface); border:1px solid var(--border); color:var(--fg); padding:6px 8px; border-radius:4px; font-size:11px;';

  var confirmBtn = document.createElement('button');
  confirmBtn.style.cssText = 'background:rgba(255,120,32,0.14); border:1px solid rgba(255,120,32,0.25); color:var(--ember-mid); cursor:pointer; padding:5px 10px; border-radius:4px; font-size:11px;';
  confirmBtn.textContent = 'Pin';

  var cancelBtn = document.createElement('button');
  cancelBtn.style.cssText = 'background:transparent; border:1px solid var(--border); color:var(--fg-muted); cursor:pointer; padding:5px 10px; border-radius:4px; font-size:11px;';
  cancelBtn.textContent = 'Cancel';

  function submitPin() {
    var topic = input.value.trim();
    if (!topic) {
      showToast('Enter a topic to pin', 'err');
      input.focus();
      return;
    }

    input.disabled = true;
    confirmBtn.disabled = true;
    cancelBtn.disabled = true;

    callApi('pin_memory', result.id, topic, result.collection).then(function(r) {
      input.disabled = false;
      confirmBtn.disabled = false;
      cancelBtn.disabled = false;

      if (r && r.ok) {
        setRetrievalActionButtonState(pinBtn, true);
        closePinTopicEditor(card);
        showToast(r.msg || 'Pinned', 'ok');
      } else {
        showToast((r && r.msg) || 'Pin failed', 'err');
        input.focus();
      }
    });
  }

  confirmBtn.addEventListener('click', function(evt) {
    evt.preventDefault();
    evt.stopPropagation();
    submitPin();
  });

  cancelBtn.addEventListener('click', function(evt) {
    evt.preventDefault();
    evt.stopPropagation();
    closePinTopicEditor(card);
  });

  input.addEventListener('keydown', function(evt) {
    if (evt.key === 'Enter') {
      evt.preventDefault();
      submitPin();
    } else if (evt.key === 'Escape') {
      evt.preventDefault();
      closePinTopicEditor(card);
    }
  });

  editor.appendChild(input);
  editor.appendChild(confirmBtn);
  editor.appendChild(cancelBtn);

  if (anchor && anchor.parentNode === card && anchor.nextSibling) {
    card.insertBefore(editor, anchor.nextSibling);
  } else {
    card.appendChild(editor);
  }

  input.focus();
}

// Last Retrieval panel
function loadLastRetrieval() {
  var area = document.getElementById('lastRetrievalArea');
  if (!area) return;
  setTextById('retrievalRefreshTime', nowStr());

  callApi('get_last_retrieval', getDashboardScopeId()).then(function(r) {
    if (!r || !r.ok || !r.retrieval || !r.retrieval.results) {
      area.textContent = '';
      var empt = document.createElement('div');
      empt.className = 'empty-state';
      var ico = el('div', 'empty-icon', '\uD83D\uDD0D');
      var label = currentSessionFilter
        ? ('session ' + currentSessionFilter + ' retrieval')
        : (currentAiFilter === 'all' ? 'retrieval' : (getAiDisplayName(currentAiFilter) + ' retrieval'));
      var msg = el('span', null, 'Waiting for first ' + label + '...');
      empt.appendChild(ico);
      empt.appendChild(msg);
      area.appendChild(empt);
      return;
    }

    var ret = r.retrieval;
    area.textContent = '';

    // Prompt that triggered this retrieval
    var promptBox = document.createElement('div');
    promptBox.className = 'retrieval-prompt';
    var promptLabel = document.createElement('div');
    promptLabel.className = 'retrieval-prompt-label';
    var retrievalAi = ret.ai_id || getDashboardAiId() || 'all';
    promptLabel.textContent = 'Query (' + getAiDisplayName(retrievalAi) + ') \u2022 ' + (ret.elapsed_ms || '?') + 'ms \u2022 ' + ret.results.length + ' results';
    promptBox.appendChild(promptLabel);
    var promptText = document.createElement('div');
    promptText.textContent = ret.prompt || '(empty)';
    promptBox.appendChild(promptText);
    area.appendChild(promptBox);

    if (!ret.results.length) {
      var noResults = document.createElement('div');
      noResults.className = 'empty-state';
      noResults.appendChild(el('span', null, 'No memories matched this query.'));
      area.appendChild(noResults);
      return;
    }

    // Each result
    ret.results.forEach(function(result, i) {
      var card = document.createElement('div');
      card.className = 'retrieval-result';

      var hdr = document.createElement('div');
      hdr.className = 'retrieval-result-hdr';

      var colName = document.createElement('span');
      colName.className = 'retrieval-result-collection';
      colName.textContent = result.collection;
      hdr.appendChild(colName);

      var scoreText = document.createElement('span');
      scoreText.className = 'retrieval-result-score';
      var simPct = Math.round((result.similarity || 0) * 100);
      var compPct = Math.round((result.composite_score || 0) * 100);
      scoreText.textContent = simPct + '% sim \u2022 ' + compPct + '% composite';
      hdr.appendChild(scoreText);

      card.appendChild(hdr);

      var content = document.createElement('div');
      content.className = 'retrieval-result-content';
      content.textContent = result.content || '(empty)';
      card.appendChild(content);

      var breakdown = result.score_breakdown || {};
      var similarity = safeNum(breakdown.similarity, safeNum(result.similarity, 0));
      var heatBoost = safeNum(breakdown.heat_boost, 0);
      var connectionBonus = safeNum(breakdown.connection_bonus, 0);
      var decayFactor = safeNum(breakdown.decay_factor, 0);
      var compositeScore = safeNum(breakdown.composite_score, safeNum(result.composite_score, 0));

      var weightedSimilarity = similarity * 0.40;
      var weightedHeat = heatBoost * 0.25;
      var weightedConnection = connectionBonus * 0.20;
      var weightedDecay = decayFactor * 0.15;
      var totalWeighted = weightedSimilarity + weightedHeat + weightedConnection + weightedDecay;
      var scoreBase = compositeScore > 0 ? compositeScore : totalWeighted;

      var xrayBar = document.createElement('div');
      xrayBar.className = 'xray-bar';

      [
        { cls: 'xray-seg-sim', title: 'Similarity', value: weightedSimilarity },
        { cls: 'xray-seg-heat', title: 'Heat', value: weightedHeat },
        { cls: 'xray-seg-conn', title: 'Connection', value: weightedConnection },
        { cls: 'xray-seg-decay', title: 'Decay', value: weightedDecay }
      ].forEach(function(part) {
        var seg = document.createElement('div');
        var pct = scoreBase > 0 ? (part.value / scoreBase) * 100 : 0;
        seg.className = 'xray-seg ' + part.cls;
        seg.style.width = pct.toFixed(2) + '%';
        seg.title = part.title + ': ' + Math.round(pct) + '%';
        xrayBar.appendChild(seg);
      });
      card.appendChild(xrayBar);

      var feedbackRow = document.createElement('div');
      feedbackRow.style.cssText = 'display:flex; gap:8px; margin-top:4px;';

      var thumbUp = createRetrievalActionButton('\uD83D\uDC4D', 'This was helpful', function(button) {
        callApi('rate_memory', result.id, 1).then(function(r) {
          if (r && r.ok) {
            setRetrievalActionButtonState(button, true);
            showToast('Boosted', 'ok');
          } else {
            showToast((r && r.msg) || 'Rating failed', 'err');
          }
        });
      });

      var thumbDown = createRetrievalActionButton('\uD83D\uDC4E', 'Not relevant', function(button) {
        callApi('rate_memory', result.id, -1).then(function(r) {
          if (r && r.ok) {
            setRetrievalActionButtonState(button, true);
            showToast('Deprioritized', 'ok');
          } else {
            showToast((r && r.msg) || 'Rating failed', 'err');
          }
        });
      });

      var pinBtn = createRetrievalActionButton('\uD83D\uDCCC', 'Pin this memory for a topic', function(button) {
        openPinTopicEditor(card, feedbackRow, result, button);
      });

      feedbackRow.appendChild(thumbUp);
      feedbackRow.appendChild(thumbDown);
      feedbackRow.appendChild(pinBtn);
      card.appendChild(feedbackRow);

      var xrayLegend = document.createElement('div');
      xrayLegend.className = 'xray-legend';

      [
        { label: 'Similarity', color: '#6699cc', value: weightedSimilarity },
        { label: 'Heat', color: '#FF7820', value: weightedHeat },
        { label: 'Connection', color: '#10a37f', value: weightedConnection },
        { label: 'Decay', color: '#888', value: weightedDecay }
      ].forEach(function(part) {
        var item = document.createElement('span');
        var dot = document.createElement('span');
        var label = document.createElement('span');
        var pct = scoreBase > 0 ? (part.value / scoreBase) * 100 : 0;
        dot.className = 'xray-legend-dot';
        dot.style.background = part.color;
        label.textContent = part.label + ': ' + Math.round(pct) + '%';
        item.appendChild(dot);
        item.appendChild(label);
        xrayLegend.appendChild(item);
      });
      card.appendChild(xrayLegend);

      area.appendChild(card);
    });
  });
}

function loadActivityFeed() {
  var area = document.getElementById('activityFeedArea');
  if (!area) return;
  setTextById('activityRefreshTime', nowStr());

  callApi('get_activity_log', 20, getDashboardAiId(), currentSessionFilter || null).then(function(r) {
    area.textContent = '';

    if (!r || !r.ok || !r.entries || r.entries.length === 0) {
      var empt = document.createElement('div');
      empt.className = 'empty-state';
      var msg = document.createElement('span');
      msg.textContent = currentSessionFilter
        ? ('No activity yet for session ' + currentSessionFilter)
        : (currentAiFilter === 'all'
          ? 'No activity yet — send a message to your AI'
          : ('No ' + getAiDisplayName(currentAiFilter) + ' activity yet'));
      empt.appendChild(msg);
      area.appendChild(empt);
      return;
    }

    // Deduplicate: hide consecutive identical prompts per AI
    var seen = {};
    var deduped = [];
    (r.entries || []).forEach(function(entry) {
      var key = String(entry.ai_id || 'all').toLowerCase() + '|' + String(entry.prompt || '').trim().toLowerCase().substring(0, 80);
      if (seen[key]) return;
      seen[key] = true;
      deduped.push(entry);
    });

    deduped.forEach(function(entry) {
      var row = document.createElement('div');
      row.className = 'activity-entry';

      var timeEl = document.createElement('div');
      timeEl.className = 'activity-entry-time';
      timeEl.textContent = formatActivityTime(entry.ts);
      row.appendChild(timeEl);

      var promptEl = document.createElement('div');
      promptEl.className = 'activity-entry-prompt';
      var promptText = entry.prompt || '(empty prompt)';
      promptEl.title = promptText;
      var aiDot = document.createElement('span');
      aiDot.className = 'activity-ai-dot';
      aiDot.setAttribute('data-ai', String(entry.ai_id || 'all').toLowerCase());
      promptEl.appendChild(aiDot);
      var promptTextEl = document.createElement('span');
      promptTextEl.className = 'activity-entry-prompt-text';
      promptTextEl.textContent = promptText;
      promptEl.appendChild(promptTextEl);
      row.appendChild(promptEl);

      var statsEl = document.createElement('div');
      statsEl.className = 'activity-entry-stats';

      var hitBadge = document.createElement('span');
      hitBadge.className = 'activity-hit-badge';
      hitBadge.textContent = String(entry.hits || 0) + ' hits';
      statsEl.appendChild(hitBadge);

      var elapsedEl = document.createElement('span');
      elapsedEl.textContent = String(entry.elapsed_ms || 0) + 'ms';
      statsEl.appendChild(elapsedEl);

      row.appendChild(statsEl);
      area.appendChild(row);
    });
  });
}


// Heat mode toggle
document.getElementById('heatModeCard').addEventListener('click', function() {
  var badge   = document.getElementById('heatModeBadge');
  var current = badge ? badge.textContent.trim() : 'universal';
  var next    = current === 'universal' ? 'per_cli' : 'universal';
  callApi('set_heat_mode', next).then(function(r) {
    if (r && r.ok) {
      setTextById('heatModeBadge', next);
      showToast('Heat mode: ' + next, 'ok');
    } else {
      showToast((r && r.msg) || 'Failed to set mode', 'err');
    }
  });
});

document.getElementById('resetEngineCard').addEventListener('click', function() {
  if (!confirm('Reset all Engine state? This clears heat map, connections, and metadata. Cannot be undone.')) return;
  callApi('reset_engine').then(function(r) {
    if (r && r.ok) {
      showToast(r.msg || 'Engine reset', 'ok');
      loadDashboard();
    } else {
      showToast((r && r.msg) || 'Reset failed', 'err');
    }
  });
});

// Dashboard auto-refresh
var dashRefreshInterval = null;

function startDashRefresh() {
  stopDashRefresh();
  loadDashboard();
  dashRefreshInterval = setInterval(function() {
    // Skip refresh when window isn't focused to prevent flicker
    if (document.hidden) return;
    loadDashboard();
  }, 15000);
}

function stopDashRefresh() {
  if (dashRefreshInterval) { clearInterval(dashRefreshInterval); dashRefreshInterval = null; }
}

// =====================================================
// COLLECTIONS
// =====================================================

var expandedCol = null;
var collectionUiCache = null;
var collectionUiPromise = null;
var collectionUiCacheAt = 0;

function invalidateCollectionUiCache() {
  collectionUiCache = null;
  collectionUiPromise = null;
  collectionUiCacheAt = 0;
}

function getCollectionUiData(force) {
  var now = Date.now();
  if (!force && collectionUiCache && now - collectionUiCacheAt < 2000) {
    return Promise.resolve(collectionUiCache);
  }
  if (!force && collectionUiPromise) return collectionUiPromise;

  collectionUiPromise = Promise.all([
    callApi('get_collections'),
    callApi('get_collection_labels'),
    callApi('get_collection_states'),
    callApi('detect_clis')
  ]).then(function(results) {
    var data = {
      collections: results[0],
      labels: results[1],
      states: results[2],
      clis: results[3]
    };
    collectionUiCache = data;
    collectionUiCacheAt = Date.now();
    collectionUiPromise = null;
    return data;
  }).catch(function(err) {
    collectionUiPromise = null;
    throw err;
  });
  return collectionUiPromise;
}

function buildColItem(col, labels, disabledMap) {
  var wrap   = document.createElement('div');
  var defaultLabel = col.displayName || col.name;
  var labelValue = labels && Object.prototype.hasOwnProperty.call(labels, col.name) ? labels[col.name] : '';
  var disabled = !!(disabledMap && disabledMap[col.name]);
  var headerClickTimer = null;
  var renameInput = null;

  var header = document.createElement('div');
  header.className = 'col-item' + (expandedCol === col.name ? ' expanded' : '') + (disabled ? ' disabled' : '');

  var nameEl  = el('div', 'col-item-name', labelValue || defaultLabel);
  var countEl = el('div', 'col-item-count', (col.count || 0) + ' chunks');

  var toggleWrap = document.createElement('label');
  toggleWrap.className = 'toggle-switch';

  var toggleInput = document.createElement('input');
  toggleInput.type = 'checkbox';
  toggleInput.checked = !disabled;

  var toggleSlider = document.createElement('span');
  toggleSlider.className = 'toggle-slider';

  toggleWrap.appendChild(toggleInput);
  toggleWrap.appendChild(toggleSlider);

  var addFilesBtn = document.createElement('button');
  addFilesBtn.className = 'btn btn-secondary btn-sm';
  addFilesBtn.textContent = 'Add Files';

  var delBtn = document.createElement('button');
  delBtn.className = 'btn btn-danger btn-sm';
  delBtn.textContent = 'Delete';

  function currentLabel() {
    return labelValue || defaultLabel;
  }

  function renderLabel() {
    if (renameInput) return;
    nameEl.textContent = currentLabel();
  }

  function finishRename(save, originalValue) {
    if (!renameInput) return;
    var inputEl = renameInput;
    var nextValue = inputEl.value.trim();
    renameInput = null;
    renderLabel();
    if (!save) return;
    callApi('rename_collection_label', col.name, nextValue).then(function(r) {
      if (r && r.ok) {
        labelValue = nextValue;
        if (labels) labels[col.name] = nextValue;
        invalidateCollectionUiCache();
        renderLabel();
        showToast(r.msg || ('Renamed: ' + currentLabel()), 'ok');
      } else {
        renderLabel();
        showToast((r && r.msg) || 'Rename failed', 'err');
      }
    });
  }

  function startRename() {
    if (renameInput) return;
    var originalValue = currentLabel();
    nameEl.textContent = '';
    renameInput = document.createElement('input');
    renameInput.type = 'text';
    renameInput.className = 'col-rename-input';
    renameInput.value = originalValue;
    nameEl.appendChild(renameInput);
    renameInput.focus();
    renameInput.select();

    renameInput.addEventListener('click', function(e) { e.stopPropagation(); });
    renameInput.addEventListener('dblclick', function(e) { e.stopPropagation(); });
    renameInput.addEventListener('keydown', function(e) {
      if (e.key === 'Enter') {
        e.preventDefault();
        e.stopPropagation();
        finishRename(true, originalValue);
        return;
      }
      if (e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation();
        finishRename(false, originalValue);
      }
    });
    renameInput.addEventListener('blur', function() {
      finishRename(true, originalValue);
    });
  }

  header.appendChild(nameEl);
  header.appendChild(countEl);
  header.appendChild(toggleWrap);
  header.appendChild(addFilesBtn);
  header.appendChild(delBtn);

  // Search area
  var searchArea = document.createElement('div');
  searchArea.className = 'col-search-area' + (expandedCol === col.name ? ' visible' : '');
  searchArea.id = 'search-' + col.name;

  var searchRow   = document.createElement('div');
  searchRow.className = 'search-row';

  var queryInput  = document.createElement('input');
  queryInput.type = 'text';
  queryInput.className = 'fluid';
  queryInput.placeholder = 'Search this collection...';

  var limitSel = document.createElement('select');
  [5, 10, 20].forEach(function(v) {
    var opt = document.createElement('option');
    opt.value = String(v);
    opt.textContent = String(v);
    if (v === 10) opt.selected = true;
    limitSel.appendChild(opt);
  });

  var searchBtn = document.createElement('button');
  searchBtn.className = 'btn btn-secondary btn-sm';
  searchBtn.textContent = 'Search';

  searchRow.appendChild(queryInput);
  searchRow.appendChild(limitSel);
  searchRow.appendChild(searchBtn);

  var resultsEl = document.createElement('div');
  resultsEl.className = 'search-results';
  resultsEl.id = 'results-' + col.name;

  searchArea.appendChild(searchRow);
  searchArea.appendChild(resultsEl);

  wrap.appendChild(header);
  wrap.appendChild(searchArea);

  // Events
  function toggleExpanded() {
    if (expandedCol === col.name) {
      expandedCol = null;
      header.classList.remove('expanded');
      searchArea.classList.remove('visible');
    } else {
      document.querySelectorAll('.col-item').forEach(function(i) { i.classList.remove('expanded'); });
      document.querySelectorAll('.col-search-area').forEach(function(a) { a.classList.remove('visible'); });
      expandedCol = col.name;
      header.classList.add('expanded');
      searchArea.classList.add('visible');
    }
  }

  header.addEventListener('click', function(e) {
    if (addFilesBtn.contains(e.target) || delBtn.contains(e.target) || toggleWrap.contains(e.target) || (renameInput && renameInput.contains(e.target))) return;
    clearTimeout(headerClickTimer);
    headerClickTimer = setTimeout(toggleExpanded, 220);
  });

  nameEl.addEventListener('dblclick', function(e) {
    clearTimeout(headerClickTimer);
    e.preventDefault();
    e.stopPropagation();
    startRename();
  });

  toggleWrap.addEventListener('click', function(e) {
    e.stopPropagation();
  });

  toggleInput.addEventListener('change', function(e) {
    e.stopPropagation();
    callApi('toggle_collection', col.name).then(function(r) {
      if (r && r.ok) {
        disabled = !!r.disabled;
        if (disabledMap) disabledMap[col.name] = disabled;
        invalidateCollectionUiCache();
        toggleInput.checked = !disabled;
        header.classList.toggle('disabled', disabled);
        showToast((disabled ? 'Disabled' : 'Enabled') + ': ' + currentLabel(), 'ok');
      } else {
        toggleInput.checked = !disabled;
        showToast((r && r.msg) || 'Toggle failed', 'err');
      }
    });
  });

  delBtn.addEventListener('click', function() {
    if (!confirm('Delete collection "' + col.name + '"? This cannot be undone.')) return;
    callApi('delete_collection', col.name).then(function(r) {
      if (r && r.ok) {
        showToast('Deleted: ' + col.name, 'ok');
        if (expandedCol === col.name) expandedCol = null;
        invalidateCollectionUiCache();
        loadCollections(true);
      } else {
        showToast((r && r.msg) || 'Delete failed', 'err');
      }
    });
  });

  addFilesBtn.addEventListener('click', function(e) {
    e.preventDefault();
    e.stopPropagation();
    importFilesIntoExistingCollection(col, addFilesBtn, currentLabel());
  });

  function doSearch() {
    var query = queryInput.value.trim();
    if (!query) return;
    resultsEl.textContent = '';
    var loadRow = document.createElement('div');
    loadRow.className = 'loading-text';
    var spin = document.createElement('div');
    spin.className = 'spinner';
    loadRow.appendChild(spin);
    loadRow.appendChild(el('span', null, ' Searching...'));
    resultsEl.appendChild(loadRow);

    var limit = parseInt(limitSel.value, 10) || 10;
    callApi('search_collection', col.name, query, limit).then(function(r) {
      resultsEl.textContent = '';
      if (!r || !r.ok || !r.results || r.results.length === 0) {
        resultsEl.appendChild(el('div', 'empty-state', 'No results found'));
        return;
      }
      r.results.forEach(function(res) {
        var item  = document.createElement('div');
        item.className = 'search-result-item';
        var idEl    = el('div', 'search-result-id',   res.id   || '\u2014');
        var textEl  = el('div', 'search-result-text', res.text || res.document || res.content || '');
        var scoreEl = el('div', 'search-result-score', 'score: ' + (
          res.score != null ? (typeof res.score === 'number' ? res.score.toFixed(4) : res.score) : '\u2014'
        ));
        item.appendChild(idEl);
        item.appendChild(textEl);
        item.appendChild(scoreEl);
        resultsEl.appendChild(item);
      });
    });
  }

  searchBtn.addEventListener('click', doSearch);
  queryInput.addEventListener('keydown', function(e) { if (e.key === 'Enter') doSearch(); });

  return wrap;
}

// Configurable owner labels — users can rename these
// Owner labels — defaults use CLI names, customize via rename
var ownerLabels = {
  'claude': "Claude Collections",
  'gemini': "Gemini Collections",
  'codex': "Codex Collections",
  'shared': "Shared Collections",
};
var detectedCLIs = {};

function setDetectedCLIs(clis) {
  detectedCLIs = clis || {};
}

function getInstalledCLIDefs() {
  return CLI_DEFS.filter(function(def) {
    return !!(detectedCLIs[def.id] && detectedCLIs[def.id].installed);
  });
}

function buildLaunchButton(def, workspaceName) {
  var button = document.createElement('button');
  button.type = 'button';
  button.className = 'btn-launch btn-launch-' + def.id;
  button.textContent = 'Launch ' + def.launchLabel;
  button.addEventListener('click', function() {
    callApi('launch_cli', def.id, workspaceName || '').then(function(r) {
      if (r && r.ok) {
        showToast((r && r.msg) || ('Launched ' + def.launchLabel), 'ok');
      } else {
        showToast((r && r.msg) || ('Failed to launch ' + def.launchLabel), 'err');
      }
    });
  });
  return button;
}

function renderCollectionsQuickLaunch() {
  var panel = document.getElementById('collectionsQuickLaunchPanel');
  var row = document.getElementById('collectionsQuickLaunch');
  if (!panel || !row) return;

  row.textContent = '';
  var installed = getInstalledCLIDefs();
  panel.style.display = installed.length ? '' : 'none';
  installed.forEach(function(def) {
    row.appendChild(buildLaunchButton(def, ''));
  });
}

function parseOwner(colName) {
  if (colName.indexOf('claude--') === 0) return { owner: 'claude', topic: colName.substring(8) };
  if (colName.indexOf('gemini--') === 0) return { owner: 'gemini', topic: colName.substring(8) };
  if (colName.indexOf('codex--') === 0) return { owner: 'codex', topic: colName.substring(7) };
  return { owner: 'shared', topic: colName };
}

function buildOwnerSection(ownerKey, collections, labels, disabledMap) {
  var section = document.createElement('div');
  section.style.marginBottom = '16px';

  // Color coding per owner
  var ownerColors = {
    'claude': { accent: '#FF7820', bg: 'rgba(255,120,32,0.08)', text: '#FF7820' },
    'gemini': { accent: '#4285f4', bg: 'rgba(66,133,244,0.08)', text: '#4285f4' },
    'codex':  { accent: '#10a37f', bg: 'rgba(16,163,127,0.08)', text: '#10a37f' },
    'shared': { accent: '#888', bg: 'rgba(255,255,255,0.04)', text: '#aaa' },
  };
  var colors = ownerColors[ownerKey] || ownerColors['shared'];

  var header = document.createElement('div');
  header.style.cssText = 'font-size:13px; font-weight:600; color:' + colors.text + '; margin-bottom:8px; padding:6px 10px; background:' + colors.bg + '; border-radius:6px; border-left:3px solid ' + colors.accent + ';';

  var headerTop = document.createElement('div');
  headerTop.style.cssText = 'display:flex; justify-content:space-between; align-items:center;';
  var labelWrap = document.createElement('span');
  labelWrap.style.cssText = 'display:flex; align-items:center; gap:6px; cursor:pointer;';
  labelWrap.title = 'Click to rename';

  var label = document.createElement('span');
  label.textContent = ownerLabels[ownerKey] || ownerKey;

  var pencil = document.createElement('span');
  pencil.textContent = '\u270E';
  pencil.style.cssText = 'font-size:12px; opacity:0.4; transition:opacity 0.2s;';
  labelWrap.addEventListener('mouseenter', function() { pencil.style.opacity = '0.8'; });
  labelWrap.addEventListener('mouseleave', function() { pencil.style.opacity = '0.4'; });

  labelWrap.appendChild(label);
  labelWrap.appendChild(pencil);

  // Make section header renamable on click
  labelWrap.addEventListener('click', function() {
    var current = label.textContent;
    var input = document.createElement('input');
    input.type = 'text';
    input.value = current;
    input.className = 'col-rename-input';
    input.style.color = colors.text;
    label.textContent = '';
    label.appendChild(input);
    input.focus();
    input.select();

    function finishRename(save) {
      var newVal = input.value.trim();
      if (save && newVal && newVal !== current) {
        ownerLabels[ownerKey] = newVal;
        callApi('rename_collection_label', '__owner_' + ownerKey, newVal);
        invalidateCollectionUiCache();
        label.textContent = newVal;
      } else {
        label.textContent = current;
      }
    }
    input.addEventListener('keydown', function(e) {
      if (e.key === 'Enter') { e.preventDefault(); finishRename(true); }
      if (e.key === 'Escape') { e.preventDefault(); finishRename(false); }
    });
    input.addEventListener('blur', function() { finishRename(true); });
  });

  headerTop.appendChild(labelWrap);

  // Right side: count + master toggle
  var rightSide = document.createElement('div');
  rightSide.style.cssText = 'display:flex; align-items:center; gap:10px;';
  var count = document.createElement('span');
  count.style.cssText = 'font-size:11px; color:var(--fg-muted); font-weight:400;';
  var totalChunks = collections.reduce(function(sum, c) { return sum + (c.count || 0); }, 0);
  count.textContent = collections.length + (collections.length !== 1 ? ' topics' : ' topic') + ' \u2022 ' + totalChunks + ' chunks';
  rightSide.appendChild(count);

  // Master enable/disable toggle for entire section
  var masterToggle = document.createElement('label');
  masterToggle.className = 'toggle-switch';
  masterToggle.title = 'Enable/disable all in this section';
  var masterCheck = document.createElement('input');
  masterCheck.type = 'checkbox';
  // Check if ANY collection in this section is enabled
  var anyEnabled = collections.some(function(c) { return !(disabledMap && disabledMap[c.name]); });
  masterCheck.checked = anyEnabled;
  var masterSlider = document.createElement('span');
  masterSlider.className = 'toggle-slider';
  masterToggle.appendChild(masterCheck);
  masterToggle.appendChild(masterSlider);
  rightSide.appendChild(masterToggle);

  // Delete entire section button
  var delSectionBtn = document.createElement('button');
  delSectionBtn.className = 'btn btn-danger btn-sm';
  delSectionBtn.textContent = 'Delete All';
  delSectionBtn.title = 'Delete all collections in this section';
  delSectionBtn.addEventListener('click', function(e) {
    e.stopPropagation();
    var sectionLabel = ownerLabels[ownerKey] || ownerKey;
    if (!confirm('Delete ALL collections in ' + sectionLabel + '? This removes ' + collections.length + ' collections and all their data. Cannot be undone.')) return;
    var promises = collections.map(function(c) {
      return callApi('delete_collection', c.name);
    });
    Promise.all(promises).then(function() {
      showToast('Deleted all in ' + sectionLabel, 'ok');
      invalidateCollectionUiCache();
      loadCollections(true);
    });
  });
  rightSide.appendChild(delSectionBtn);

  masterCheck.addEventListener('change', function() {
    var enable = masterCheck.checked;
    // Toggle all collections in this section
    var promises = collections.map(function(c) {
      var isDisabled = disabledMap && disabledMap[c.name];
      // Only toggle if state needs to change
      if (enable && isDisabled) return callApi('toggle_collection', c.name);
      if (!enable && !isDisabled) return callApi('toggle_collection', c.name);
      return Promise.resolve();
    });
    Promise.all(promises).then(function() {
      var state = enable ? 'Enabled' : 'Disabled';
      showToast(state + ' all in ' + (ownerLabels[ownerKey] || ownerKey), 'ok');
      invalidateCollectionUiCache();
      loadCollections(true);
    });
  });

  headerTop.appendChild(rightSide);
  header.appendChild(headerTop);

  // Per-section launch buttons
  var launchRow = document.createElement('div');
  launchRow.style.cssText = 'display:flex; gap:6px; margin-top:6px;';

  var colNames = collections.map(function(c) { return c.name; });

  [
    { cli: 'claude', label: 'Launch Claude', cls: 'btn-launch btn-launch-claude' },
    { cli: 'gemini', label: 'Launch Gemini', cls: 'btn-launch btn-launch-gemini' },
    { cli: 'codex', label: 'Launch Codex', cls: 'btn-launch btn-launch-codex' },
  ].forEach(function(def) {
    var btn = document.createElement('button');
    btn.className = def.cls;
    btn.textContent = def.label;
    btn.addEventListener('click', function(e) {
      e.stopPropagation();
      // Create a temporary workspace from this section's enabled collections
      var enabledCols = {};
      colNames.forEach(function(name) {
        enabledCols[name] = !(disabledMap && disabledMap[name]);
      });
      var wsName = '_quick_' + ownerKey;
      callApi('save_workspace', wsName, ownerKey, enabledCols, '').then(function() {
        callApi('launch_cli', def.cli, wsName).then(function(r) {
          if (r && r.ok) showToast(r.msg, 'ok');
          else showToast((r && r.msg) || 'Launch failed', 'err');
        });
      });
    });
    launchRow.appendChild(btn);
  });

  header.appendChild(launchRow);
  section.appendChild(header);

  collections.forEach(function(col) {
    section.appendChild(buildColItem(col, labels, disabledMap));
  });

  return section;
}

function loadCollections(force) {
  var list = document.getElementById('colList');
  list.textContent = '';
  var loadRow = document.createElement('div');
  loadRow.className = 'loading-text';
  var spin = document.createElement('div');
  spin.className = 'spinner';
  loadRow.appendChild(spin);
  loadRow.appendChild(el('span', null, ' Loading collections...'));
  list.appendChild(loadRow);

  getCollectionUiData(!!force).then(function(data) {
    var r = data.collections;
    var labelsRes = data.labels;
    var statesRes = data.states;
    var cliRes = data.clis;
    var labels = labelsRes && labelsRes.ok && labelsRes.labels ? labelsRes.labels : {};
    var disabledMap = statesRes && statesRes.ok && statesRes.disabled ? statesRes.disabled : {};
    setDetectedCLIs(cliRes && cliRes.ok && cliRes.clis ? cliRes.clis : {});
    // Load saved owner section labels
    ['claude', 'gemini', 'codex', 'shared'].forEach(function(key) {
      var saved = labels['__owner_' + key];
      if (saved) ownerLabels[key] = saved;
    });
    renderCollectionsQuickLaunch();
    list.textContent = '';
    if (!r || !r.ok || !r.collections) {
      // API bridge might not be ready yet — retry once after a short delay
      if (!loadCollections._retried) {
        loadCollections._retried = true;
        setTimeout(function() { loadCollections._retried = false; loadCollections(true); }, 800);
      } else {
        list.appendChild(buildEmptyState('No collections found'));
        loadCollections._retried = false;
      }
      return;
    }
    var cols = r.collections;
    if (cols.length === 0) {
      list.appendChild(buildEmptyState('No collections yet \u2014 create one to get started'));
      return;
    }

    // Group by owner
    var groups = { claude: [], gemini: [], codex: [], shared: [] };
    cols.forEach(function(col) {
      var parsed = parseOwner(col.name);
      col.displayName = parsed.topic;
      if (!groups[parsed.owner]) groups[parsed.owner] = [];
      groups[parsed.owner].push(col);
    });

    // Render in order: the current AI first, then others, then shared last
    var order = ['claude', 'gemini', 'codex', 'shared'];
    order.forEach(function(key) {
      if (groups[key] && groups[key].length > 0) {
        list.appendChild(buildOwnerSection(key, groups[key], labels, disabledMap));
      }
    });
  });
}

function buildEmptyState(msg) {
  var d = document.createElement('div');
  d.className = 'empty-state';
  d.appendChild(el('div', 'empty-icon', '\uD83D\uDCE6'));
  d.appendChild(el('span', null, msg));
  return d;
}

function clearImportSuccess() {
  var host = document.getElementById('importSuccessHost');
  if (!host) return;
  host.textContent = '';
}

function setImportProgress(message) {
  var progress = document.getElementById('importProgressText');
  if (!progress) return;
  progress.textContent = message || '';
}

var IMPORT_MODE_EXISTING = 'existing';
var IMPORT_MODE_NEW = 'new';
var importSelectedItems = [];
var currentImportMode = IMPORT_MODE_EXISTING;

function sanitizeCollectionName(raw) {
  return raw.toLowerCase().replace(/[^a-z0-9._-]/g, '-').replace(/-+/g, '-').replace(/^-|-$/g, '') || 'collection';
}

function buildScopedCollectionName(name, scope) {
  var resolvedScope = scope || 'shared';
  return resolvedScope === 'shared' ? name : (resolvedScope + '--' + name);
}

function maybeSaveCollectionLabel(fullName, displayName, internalName) {
  var label = String(displayName || '').trim();
  var internal = String(internalName || '').trim();
  if (!label || label === internal) {
    return Promise.resolve({ ok: true, skipped: true });
  }
  return callApi('rename_collection_label', fullName, label).then(function(r) {
    return r || { ok: false, msg: 'Failed to save display label' };
  }).catch(function(err) {
    return { ok: false, msg: String(err) };
  });
}

function getImportPathBaseName(path) {
  var cleaned = String(path || '').replace(/[\\/]+$/, '');
  if (!cleaned) return '';
  var parts = cleaned.split(/[\\/]/);
  return parts[parts.length - 1] || cleaned;
}

function focusImportWizard() {
  if (currentImportMode === IMPORT_MODE_EXISTING) {
    var select = document.getElementById('importCollectionSelect');
    if (select && !select.disabled) {
      select.focus();
      return;
    }
  }
  var nameInput = document.getElementById('importCollectionName');
  if (nameInput) nameInput.focus();
}

function buildCollectionDraft(nameInputId, scopeSelectId) {
  var nameInput = document.getElementById(nameInputId);
  var scopeSelect = document.getElementById(scopeSelectId);
  var rawName = nameInput ? nameInput.value.trim() : '';
  if (!rawName) return { ok: false, msg: 'Enter a collection name' };
  return {
    ok: true,
    name: sanitizeCollectionName(rawName),
    displayName: rawName,
    scope: scopeSelect ? (scopeSelect.value || 'shared') : 'shared'
  };
}

// resetCreateForm removed — unified into Import Knowledge

function setImportMode(mode) {
  currentImportMode = mode === IMPORT_MODE_NEW ? IMPORT_MODE_NEW : IMPORT_MODE_EXISTING;

  var existingBtn = document.getElementById('btnImportModeExisting');
  var newBtn = document.getElementById('btnImportModeNew');
  var existingPanel = document.getElementById('importModeExisting');
  var newPanel = document.getElementById('importModeNew');

  if (existingBtn) existingBtn.classList.toggle('active', currentImportMode === IMPORT_MODE_EXISTING);
  if (newBtn) newBtn.classList.toggle('active', currentImportMode === IMPORT_MODE_NEW);
  if (existingPanel) existingPanel.classList.toggle('active', currentImportMode === IMPORT_MODE_EXISTING);
  if (newPanel) newPanel.classList.toggle('active', currentImportMode === IMPORT_MODE_NEW);

  if (currentImportMode === IMPORT_MODE_NEW) {
    maybeFillImportCollectionName(false);
  }
  updateImportSubmitButton();
}

function suggestImportCollectionName() {
  var suggested = 'imported';
  if (importSelectedItems.length === 1) {
    suggested = getImportPathBaseName(importSelectedItems[0].path).replace(/\.[^.]+$/, '') || suggested;
  } else if (importSelectedItems.length > 1) {
    suggested = 'mixed-import';
  }
  return sanitizeCollectionName(suggested);
}

function maybeFillImportCollectionName(force) {
  var input = document.getElementById('importCollectionName');
  if (!input) return;
  if (currentImportMode !== IMPORT_MODE_NEW) return;
  if (force || !input.value.trim()) {
    input.value = suggestImportCollectionName();
  }
}

function updateImportSubmitButton() {
  var btn = document.getElementById('btnRunImport');
  if (!btn) return;
  btn.textContent = currentImportMode === IMPORT_MODE_NEW ? 'Create & Import' : 'Import';
}

function renderImportFileList() {
  var list = document.getElementById('importFileList');
  if (!list) return;
  list.textContent = '';

  if (!importSelectedItems.length) {
    var empty = document.createElement('div');
    empty.className = 'import-supported';
    empty.textContent = 'No files selected yet.';
    list.appendChild(empty);
    updateImportSubmitButton();
    return;
  }

  importSelectedItems.forEach(function(item) {
    var row = document.createElement('div');
    row.className = 'import-file-item';
    row.title = item.path;

    var label = document.createElement('span');
    var suffix = item.kind === 'folder' ? ' [folder]' : '';
    label.textContent = getImportPathBaseName(item.path) + suffix;

    var remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'import-file-remove';
    remove.textContent = 'X';
    remove.addEventListener('click', function() {
      importSelectedItems = importSelectedItems.filter(function(entry) {
        return entry.path !== item.path;
      });
      renderImportFileList();
      maybeFillImportCollectionName(false);
    });

    row.appendChild(label);
    row.appendChild(remove);
    list.appendChild(row);
  });

  updateImportSubmitButton();
}

function addImportSelections(paths, kind) {
  var changed = false;
  (paths || []).forEach(function(path) {
    var value = String(path || '').trim();
    if (!value) return;
    var exists = importSelectedItems.some(function(item) {
      return item.path === value;
    });
    if (exists) return;
    importSelectedItems.push({ path: value, kind: kind });
    changed = true;
  });

  if (changed) {
    renderImportFileList();
    maybeFillImportCollectionName(false);
  }
}

function getImportCollectionLabel(rawName, labels) {
  var parsed = parseOwner(String(rawName || ''));
  var saved = labels && Object.prototype.hasOwnProperty.call(labels, rawName) ? labels[rawName] : '';
  return saved || parsed.topic || rawName;
}

function refreshImportCollections(selectedName) {
  var select = document.getElementById('importCollectionSelect');
  if (!select) return Promise.resolve();

  var preferred = selectedName || select.value || '';
  select.disabled = true;
  select.textContent = '';

  var loadingOption = document.createElement('option');
  loadingOption.value = '';
  loadingOption.textContent = 'Loading collections...';
  select.appendChild(loadingOption);

  return getCollectionUiData(false).then(function(data) {
    var collectionsRes = data.collections;
    var labelsRes = data.labels;
    var labels = labelsRes && labelsRes.ok && labelsRes.labels ? labelsRes.labels : {};
    var hasSelected = false;
    var totalCollections = 0;

    select.textContent = '';

    if (collectionsRes && collectionsRes.ok && collectionsRes.collections && collectionsRes.collections.length) {
      var placeholder = document.createElement('option');
      placeholder.value = '';
      placeholder.textContent = 'Choose a collection';
      placeholder.selected = !preferred;
      select.appendChild(placeholder);

      var groups = { claude: [], gemini: [], codex: [], shared: [] };
      collectionsRes.collections.forEach(function(col) {
        var rawName = String(col.name || '');
        var parsed = parseOwner(rawName);
        if (!groups[parsed.owner]) groups[parsed.owner] = [];
        groups[parsed.owner].push({
          rawName: rawName,
          topic: parsed.topic,
          count: col.count,
          displayName: getImportCollectionLabel(rawName, labels),
          owner: parsed.owner
        });
      });

      ['claude', 'gemini', 'codex', 'shared'].forEach(function(owner) {
        var entries = groups[owner];
        if (!entries || !entries.length) return;

        totalCollections += entries.length;

        var group = document.createElement('optgroup');
        group.label = ownerLabels[owner] || owner;

        entries.forEach(function(entry) {
          var option = document.createElement('option');
          option.value = entry.rawName;
          option.textContent = entry.displayName + ' (' + String(entry.count || 0) + ' chunks)';
          option.setAttribute('data-display-name', entry.displayName);
          option.setAttribute('data-scope', entry.owner);
          option.setAttribute('data-topic', entry.topic);
          if (entry.rawName === preferred) {
            option.selected = true;
            hasSelected = true;
          }
          group.appendChild(option);
        });

        // Add "+ New Topic" option for this owner group
        var newTopicOpt = document.createElement('option');
        newTopicOpt.value = '__new_topic__' + owner;
        newTopicOpt.textContent = '+ New Topic';
        newTopicOpt.setAttribute('data-scope', owner);
        group.appendChild(newTopicOpt);

        select.appendChild(group);
      });

      if (!hasSelected) {
        placeholder.selected = true;
      }
    } else {
      var emptyOption = document.createElement('option');
      emptyOption.value = '';
      emptyOption.textContent = 'No collections available';
      emptyOption.selected = true;
      select.appendChild(emptyOption);
    }

    select.disabled = false;
    if (!totalCollections && currentImportMode === IMPORT_MODE_EXISTING) {
      setImportMode(IMPORT_MODE_NEW);
    }
  }).catch(function(err) {
    select.textContent = '';
    var emptyOption = document.createElement('option');
    emptyOption.value = '';
    emptyOption.textContent = 'Unable to load collections';
    emptyOption.selected = true;
    select.appendChild(emptyOption);
    select.disabled = false;
    showToast(String(err), 'err');
  });
}

function readImportExistingSelection() {
  var select = document.getElementById('importCollectionSelect');
  if (!select) return { ok: false, msg: 'Choose a collection' };
  var option = select.options[select.selectedIndex];
  var rawName = option ? String(option.value || '').trim() : '';
  if (!rawName) return { ok: false, msg: 'Choose a collection' };

  // Handle "+ New Topic" under an existing owner group
  if (rawName.startsWith('__new_topic__')) {
    var scope = option.getAttribute('data-scope') || rawName.replace('__new_topic__', '');
    var topicInput = document.getElementById('existingNewTopicName');
    var topicRaw = topicInput ? topicInput.value.trim() : '';
    if (!topicRaw) return { ok: false, msg: 'Enter a topic name for the new collection' };
    var topicClean = sanitizeCollectionName(topicRaw);
    var fullName = scope === 'shared' ? topicClean : (scope + '--' + topicClean);
    return {
      ok: true,
      fullName: fullName,
      displayName: topicRaw,
      scope: scope,
      isNewTopic: true,
    };
  }

  return {
    ok: true,
    fullName: rawName,
    displayName: option.getAttribute('data-display-name') || getCollectionDisplayName(rawName)
  };
}

function buildImportQueryList(collectionName) {
  return [
    'What do we know about ' + collectionName + '?',
    'What decisions were made in ' + collectionName + '?',
    'Summarize the key themes in ' + collectionName,
    'What changed over time in ' + collectionName + '?'
  ];
}

function buildImportQueryButton(query) {
  var button = document.createElement('button');
  button.type = 'button';
  button.className = 'import-query-btn';
  button.textContent = query;
  button.addEventListener('click', function() {
    copyTextToClipboard(query).then(function() {
      showToast('Copied — paste into your CLI', 'ok');
    }).catch(function() {
      showToast('Unable to copy query', 'err');
    });
  });
  return button;
}

function renderImportSuccess(result, titleText, displayCollectionName) {
  var host = document.getElementById('importSuccessHost');
  if (!host) return;
  host.textContent = '';

  var card = document.createElement('div');
  card.className = 'import-success';

  var title = document.createElement('div');
  title.className = 'import-success-title';
  title.textContent = titleText || 'Import complete';

  var files = document.createElement('div');
  files.className = 'import-success-stat';
  files.textContent = 'Files imported: ' + String(result.files != null ? result.files : 0);

  var chunks = document.createElement('div');
  chunks.className = 'import-success-stat';
  chunks.textContent = 'Chunks created: ' + String(result.chunks != null ? result.chunks : 0);

  var collection = document.createElement('div');
  collection.className = 'import-success-stat';
  collection.textContent = 'Collection: ' + String(displayCollectionName || getCollectionDisplayName(result.collection || '') || 'unknown');

  card.appendChild(title);
  card.appendChild(files);
  card.appendChild(chunks);
  card.appendChild(collection);

  var prompt = document.createElement('div');
  prompt.className = 'import-query-prompt';
  prompt.textContent = 'Try one of these in your CLI to see your imported knowledge in action:';
  card.appendChild(prompt);

  var queries = document.createElement('div');
  queries.className = 'import-query-list';
  var queryCollection = String(displayCollectionName || getCollectionDisplayName(result.collection || '') || 'this collection');
  buildImportQueryList(queryCollection).forEach(function(query) {
    queries.appendChild(buildImportQueryButton(query));
  });
  card.appendChild(queries);

  host.appendChild(card);
}

function resetImportSelections() {
  importSelectedItems = [];
  renderImportFileList();
  setImportProgress('');
}

function clearImportWizardInputs() {
  var nameInput = document.getElementById('importCollectionName');
  var scopeSelect = document.getElementById('importScope');
  var select = document.getElementById('importCollectionSelect');
  if (nameInput) nameInput.value = '';
  if (scopeSelect) scopeSelect.value = 'shared';
  if (select) select.value = '';
  resetImportSelections();
  setImportMode(IMPORT_MODE_EXISTING);
}

function importFilesIntoExistingCollection(col, button, label) {
  var originalText = button ? button.textContent : '';
  if (button) {
    button.disabled = true;
    button.textContent = 'Choosing...';
  }

  callApi('browse_files').then(function(r) {
    if (!r || !r.ok || !r.paths || !r.paths.length) {
      return null;
    }
    if (button) button.textContent = 'Importing...';
    return callApi('import_files', r.paths, col.name, 'shared').then(function(importResult) {
      if (importResult && importResult.ok) {
        showToast((importResult.msg) || ('Added files to ' + label), 'ok');
        invalidateCollectionUiCache();
        loadCollections(true);
        if (document.getElementById('importWizard').classList.contains('visible')) {
          refreshImportCollections(col.name);
        }
        return;
      }
      showToast((importResult && importResult.msg) || 'Import failed', 'err');
    });
  }).catch(function(err) {
    showToast(String(err), 'err');
  }).finally(function() {
    if (button) {
      button.disabled = false;
      button.textContent = originalText;
    }
  });
}

document.getElementById('btnImportToggle').addEventListener('click', function() {
  var wizard = document.getElementById('importWizard');
  var show = !wizard.classList.contains('visible');
  wizard.classList.toggle('visible', show);
  if (show) {
    clearImportSuccess();
    clearImportWizardInputs();
    refreshImportCollections().finally(function() {
      focusImportWizard();
    });
  }
});

// btnCreateToggle, btnCreateCancel, btnCreateCol removed — unified into Import Knowledge

document.getElementById('importCollectionSelect').addEventListener('change', function() {
  var val = this.value;
  var topicArea = document.getElementById('existingNewTopicArea');
  if (topicArea) {
    topicArea.style.display = val.startsWith('__new_topic__') ? 'block' : 'none';
  }
});

document.getElementById('btnImportBrowseFiles').addEventListener('click', function() {
  callApi('browse_files').then(function(r) {
    if (r && r.ok && r.paths && r.paths.length) {
      addImportSelections(r.paths, 'file');
    }
  }).catch(function(err) {
    showToast(String(err), 'err');
  });
});

document.getElementById('btnImportBrowseFolder').addEventListener('click', function() {
  callApi('browse_directory').then(function(r) {
    if (r && r.ok && r.path) {
      addImportSelections([r.path], 'folder');
    }
  }).catch(function(err) {
    showToast(String(err), 'err');
  });
});

document.getElementById('btnImportModeExisting').addEventListener('click', function() {
  setImportMode(IMPORT_MODE_EXISTING);
});

document.getElementById('btnImportModeNew').addEventListener('click', function() {
  setImportMode(IMPORT_MODE_NEW);
});

document.getElementById('btnRunImport').addEventListener('click', function() {
  var btn = document.getElementById('btnRunImport');
  var selectedPaths = importSelectedItems.map(function(item) { return item.path; });
  var destination = null;
  var draft = null;
  var fullName = '';

  if (!selectedPaths.length) {
    showToast('Select files or a folder to import', 'err');
    return;
  }

  clearImportSuccess();

  if (currentImportMode === IMPORT_MODE_EXISTING) {
    destination = readImportExistingSelection();
    if (!destination || !destination.ok) {
      showToast((destination && destination.msg) || 'Choose a collection', 'err');
      return;
    }
  } else {
    draft = buildCollectionDraft('importCollectionName', 'importScope');
    if (!draft || !draft.ok) {
      showToast((draft && draft.msg) || 'Enter a collection name', 'err');
      return;
    }
    fullName = buildScopedCollectionName(draft.name, draft.scope);
  }

  btn.disabled = true;
  if (currentImportMode === IMPORT_MODE_EXISTING) {
    btn.textContent = 'Importing...';
    setImportProgress('Importing ' + selectedPaths.length + ' item' + (selectedPaths.length === 1 ? '' : 's') + '...');
  } else {
    btn.textContent = 'Creating & Importing...';
    setImportProgress('Creating collection and importing ' + selectedPaths.length + ' item' + (selectedPaths.length === 1 ? '' : 's') + '...');
  }

  var action = currentImportMode === IMPORT_MODE_EXISTING
    ? callApi('import_files', selectedPaths, destination.fullName, destination.scope || 'shared').then(function(r) {
        if (!r || !r.ok) {
          showToast((r && r.msg) || 'Import failed', 'err');
          return;
        }
        // Save display label for new topics
        if (destination.isNewTopic && destination.displayName !== sanitizeCollectionName(destination.displayName)) {
          callApi('rename_collection_label', destination.fullName, destination.displayName);
        }
        renderImportSuccess(r, destination.isNewTopic ? 'Topic created and imported' : 'Import complete', destination.displayName);
        showToast((destination.isNewTopic ? 'Created and imported: ' : 'Imported into ') + destination.displayName, 'ok');
        // Clear new topic input
        var topicInput = document.getElementById('existingNewTopicName');
        if (topicInput) topicInput.value = '';
        var topicArea = document.getElementById('existingNewTopicArea');
        if (topicArea) topicArea.style.display = 'none';
        resetImportSelections();
        invalidateCollectionUiCache();
        loadCollections(true);
        return refreshImportCollections(destination.fullName);
      })
    : callApi('import_files', selectedPaths, draft.name, draft.scope).then(function(r) {
        if (!r || !r.ok) {
          showToast((r && r.msg) || 'Import failed', 'err');
          return;
        }
        return maybeSaveCollectionLabel(fullName, draft.displayName, draft.name).then(function(labelResult) {
          renderImportSuccess(r, 'Collection created and imported', draft.displayName);
          if (labelResult && labelResult.ok === false) {
            showToast((labelResult.msg) || ('Created ' + draft.displayName + ', but failed to save display label'), 'err');
          } else {
            showToast('Created and imported: ' + draft.displayName, 'ok');
          }
          // Save section header display name if provided
          var sectionNameInput = document.getElementById('importCollectionDisplayName');
          if (sectionNameInput && sectionNameInput.value.trim()) {
            var sectionLabel = sectionNameInput.value.trim();
            ownerLabels[draft.scope] = sectionLabel;
            callApi('rename_collection_label', '__owner_' + draft.scope, sectionLabel);
            sectionNameInput.value = '';
          }
          var nameInput = document.getElementById('importCollectionName');
          var scopeSelect = document.getElementById('importScope');
          if (nameInput) nameInput.value = '';
          if (scopeSelect) scopeSelect.value = 'shared';
          resetImportSelections();
          invalidateCollectionUiCache();
          loadCollections(true);
          setImportMode(IMPORT_MODE_EXISTING);
          return refreshImportCollections(fullName);
        });
      });

  action.catch(function(err) {
    showToast(String(err), 'err');
  }).finally(function() {
    btn.disabled = false;
    updateImportSubmitButton();
    setImportProgress('');
  });
});

document.getElementById('importCollectionName').addEventListener('keydown', function(e) {
  if (e.key === 'Enter') {
    e.preventDefault();
    document.getElementById('btnRunImport').click();
  }
});

// =====================================================
// SETTINGS
// =====================================================

var workspaceCollections = [];

function setWorkspaceChipState(chip, active) {
  chip.classList.toggle('active', !!active);
  chip.classList.toggle('inactive', !active);
}

function buildWorkspaceChip(def, enabled) {
  var chip = document.createElement('label');
  chip.className = 'workspace-col-chip ' + (enabled ? 'active' : 'inactive');
  chip.setAttribute('data-collection-name', def.name);
  if (def.count != null) chip.title = def.name + ' (' + def.count + ' chunks)';

  var input = document.createElement('input');
  input.type = 'checkbox';
  input.checked = !!enabled;
  input.setAttribute('data-collection-name', def.name);

  var text = el('span', null, def.name);

  chip.appendChild(input);
  chip.appendChild(text);

  input.addEventListener('change', function() {
    setWorkspaceChipState(chip, input.checked);
  });

  return chip;
}

function listWorkspaceCollectionDefs(collections, workspaces) {
  var defs = [];
  var seen = {};

  (collections || []).forEach(function(col) {
    if (!col || !col.name || seen[col.name]) return;
    seen[col.name] = true;
    defs.push({ name: col.name, count: col.count });
  });

  Object.keys(workspaces || {}).forEach(function(name) {
    var workspace = workspaces[name] || {};
    var cols = workspace.collections || {};
    Object.keys(cols).forEach(function(colName) {
      if (!colName || seen[colName]) return;
      seen[colName] = true;
      defs.push({ name: colName, count: null });
    });
  });

  defs.sort(function(a, b) { return a.name.localeCompare(b.name); });
  return defs;
}

function readWorkspaceCollections(container) {
  var collections = {};
  if (!container) return collections;
  container.querySelectorAll('input[type="checkbox"][data-collection-name]').forEach(function(input) {
    collections[input.getAttribute('data-collection-name')] = !!input.checked;
  });
  return collections;
}

function setWorkspaceCwdState(input, hint, clearBtn) {
  var value = input ? input.value.trim() : '';
  if (input) input.title = value;
  if (hint) hint.style.display = value ? 'block' : 'none';
  if (clearBtn) clearBtn.disabled = !value;
}

function readWorkspaceCardState(card, name) {
  var labelInput = card ? card.querySelector('input[data-role="workspace-label"]') : null;
  var cols = card ? card.querySelector('[data-role="workspace-cols"]') : null;
  var cwdInput = card ? card.querySelector('input[data-role="workspace-cwd"]') : null;
  return {
    label: labelInput ? labelInput.value.trim() : name,
    collections: readWorkspaceCollections(cols),
    cwd: cwdInput ? cwdInput.value.trim() : ''
  };
}

function persistWorkspace(name, label, collections, cwd, successMsg) {
  return callApi('save_workspace', name, label || name, collections, cwd || '').then(function(r) {
    if (r && r.ok) {
      showToast(successMsg || r.msg || ('Workspace "' + name + '" saved'), 'ok');
      loadWorkspaces();
      return true;
    }
    showToast((r && r.msg) || 'Failed to save workspace', 'err');
    return false;
  });
}

function resetWorkspaceForm() {
  var form = document.getElementById('workspaceCreateForm');
  var nameInput = document.getElementById('newWorkspaceName');
  var labelInput = document.getElementById('newWorkspaceLabel');
  var cwdInput = document.getElementById('newWorkspaceCwd');
  var cwdClearBtn = document.getElementById('btnWorkspaceClearCwd');
  var cols = document.getElementById('newWorkspaceCollections');

  if (nameInput) nameInput.value = '';
  if (labelInput) labelInput.value = '';
  if (cwdInput) cwdInput.value = '';
  setWorkspaceCwdState(cwdInput, null, cwdClearBtn);
  if (cols) {
    cols.querySelectorAll('input[type="checkbox"][data-collection-name]').forEach(function(input) {
      input.checked = false;
      if (input.parentElement) setWorkspaceChipState(input.parentElement, false);
    });
  }
  if (form) form.classList.remove('visible');
}

function renderWorkspaceCreateCollections() {
  var container = document.getElementById('newWorkspaceCollections');
  if (!container) return;
  container.textContent = '';

  if (workspaceCollections.length === 0) {
    container.appendChild(el('div', 'workspace-summary', 'No collections available yet.'));
    return;
  }

  workspaceCollections.forEach(function(def) {
    container.appendChild(buildWorkspaceChip(def, false));
  });
}

function renderWorkspaceCard(name, workspace) {
  var card = document.createElement('div');
  card.className = 'workspace-card';
  card.setAttribute('data-workspace-name', name);

  var title = el('div', 'workspace-title', workspace && workspace.label ? workspace.label : name);
  var hint = el('div', 'workspace-name-hint', 'EMBER_WORKSPACE=' + name);

  var labelInput = document.createElement('input');
  labelInput.type = 'text';
  labelInput.className = 'workspace-label-input';
  labelInput.value = workspace && workspace.label ? workspace.label : name;
  labelInput.placeholder = 'Workspace label';
  labelInput.setAttribute('data-role', 'workspace-label');

  labelInput.addEventListener('input', function() {
    title.textContent = labelInput.value.trim() || name;
  });

  var cwdRow = document.createElement('div');
  cwdRow.className = 'workspace-cwd-row';

  var cwdLabel = el('span', 'workspace-cwd-label', 'Auto-detect directory');

  var cwdInput = document.createElement('input');
  cwdInput.type = 'text';
  cwdInput.className = 'workspace-cwd-input';
  cwdInput.readOnly = true;
  cwdInput.placeholder = 'No directory selected';
  cwdInput.value = workspace && workspace.cwd ? workspace.cwd : '';
  cwdInput.setAttribute('data-role', 'workspace-cwd');

  var cwdBrowseBtn = document.createElement('button');
  cwdBrowseBtn.type = 'button';
  cwdBrowseBtn.className = 'btn btn-secondary btn-sm';
  cwdBrowseBtn.textContent = 'Browse';
  cwdBrowseBtn.addEventListener('click', function() {
    browseWorkspaceCwd(name);
  });

  var cwdClearBtn = document.createElement('button');
  cwdClearBtn.type = 'button';
  cwdClearBtn.className = 'btn btn-secondary btn-sm';
  cwdClearBtn.textContent = 'Clear';
  cwdClearBtn.addEventListener('click', function() {
    clearWorkspaceCwd(name);
  });

  cwdRow.appendChild(cwdLabel);
  cwdRow.appendChild(cwdInput);
  cwdRow.appendChild(cwdBrowseBtn);
  cwdRow.appendChild(cwdClearBtn);

  var cwdHint = el('div', 'workspace-cwd-hint', 'Sessions in this directory auto-use this workspace');
  setWorkspaceCwdState(cwdInput, cwdHint, cwdClearBtn);

  var cols = document.createElement('div');
  cols.className = 'workspace-cols';
  cols.setAttribute('data-role', 'workspace-cols');

  if (workspaceCollections.length === 0) {
    cols.appendChild(el('div', 'workspace-summary', 'No collections available yet.'));
  } else {
    var selected = (workspace && workspace.collections) || {};
    workspaceCollections.forEach(function(def) {
      cols.appendChild(buildWorkspaceChip(def, !!selected[def.name]));
    });
  }

  var actions = document.createElement('div');
  actions.className = 'workspace-actions';

  var deleteBtn = document.createElement('button');
  deleteBtn.className = 'btn btn-danger btn-sm';
  deleteBtn.textContent = 'Delete';
  deleteBtn.addEventListener('click', function() {
    deleteWorkspace(name);
  });

  var saveBtn = document.createElement('button');
  saveBtn.className = 'btn btn-primary btn-sm';
  saveBtn.textContent = 'Save';
  saveBtn.addEventListener('click', function() {
    saveWorkspace(name);
  });

  actions.appendChild(deleteBtn);
  actions.appendChild(saveBtn);

  var launchRow = document.createElement('div');
  launchRow.className = 'workspace-launch';
  getInstalledCLIDefs().forEach(function(def) {
    launchRow.appendChild(buildLaunchButton(def, name));
  });

  card.appendChild(title);
  card.appendChild(hint);
  card.appendChild(labelInput);
  card.appendChild(cwdRow);
  card.appendChild(cwdHint);
  card.appendChild(cols);
  card.appendChild(actions);
  if (launchRow.childNodes.length) {
    card.appendChild(launchRow);
  }
  return card;
}

function findWorkspaceCard(name) {
  var list = document.getElementById('workspaceList');
  if (!list) return null;
  var cards = list.querySelectorAll('.workspace-card[data-workspace-name]');
  for (var i = 0; i < cards.length; i++) {
    if (cards[i].getAttribute('data-workspace-name') === name) return cards[i];
  }
  return null;
}

function loadWorkspaces() {
  var list = document.getElementById('workspaceList');
  if (!list) return;

  list.textContent = '';
  var loadRow = document.createElement('div');
  loadRow.className = 'loading-text';
  var spin = document.createElement('div');
  spin.className = 'spinner';
  loadRow.appendChild(spin);
  loadRow.appendChild(el('span', null, ' Loading workspaces...'));
  list.appendChild(loadRow);

  Promise.all([
    callApi('get_workspaces'),
    getCollectionUiData(false)
  ]).then(function(results) {
    var workspacesRes = results[0];
    var collectionData = results[1] || {};
    var collectionsRes = collectionData.collections;
    var cliRes = collectionData.clis;
    var workspaces = workspacesRes && workspacesRes.ok && workspacesRes.workspaces ? workspacesRes.workspaces : {};
    setDetectedCLIs(cliRes && cliRes.ok && cliRes.clis ? cliRes.clis : {});

    if (!workspacesRes || !workspacesRes.ok) {
      workspaceCollections = listWorkspaceCollectionDefs(
        collectionsRes && collectionsRes.ok ? collectionsRes.collections : [],
        {}
      );
      renderWorkspaceCreateCollections();
      list.textContent = '';
      list.appendChild(buildEmptyState((workspacesRes && workspacesRes.msg) || 'Failed to load workspaces'));
      return;
    }

    workspaceCollections = listWorkspaceCollectionDefs(
      collectionsRes && collectionsRes.ok ? collectionsRes.collections : [],
      workspaces
    );
    renderWorkspaceCreateCollections();

    list.textContent = '';
    var names = Object.keys(workspaces).sort();
    if (names.length === 0) {
      var empty = buildEmptyState('No workspaces yet — create one to define a search scope');
      empty.classList.add('workspace-empty');
      list.appendChild(empty);
      return;
    }

    names.forEach(function(name) {
      list.appendChild(renderWorkspaceCard(name, workspaces[name] || {}));
    });
  });
}

function saveWorkspace(name) {
  var card = findWorkspaceCard(name);
  if (!card) {
    showToast('Workspace not found', 'err');
    return;
  }

  var state = readWorkspaceCardState(card, name);
  persistWorkspace(name, state.label || name, state.collections, state.cwd);
}

function browseWorkspaceCwd(name) {
  callApi('browse_directory').then(function(r) {
    if (!r || !r.ok || !r.path) return;
    var card = findWorkspaceCard(name);
    if (!card) {
      showToast('Workspace not found', 'err');
      return;
    }
    var state = readWorkspaceCardState(card, name);
    persistWorkspace(name, state.label || name, state.collections, r.path, 'Auto-detect directory updated');
  }).catch(function(err) {
    showToast(String(err), 'err');
  });
}

function clearWorkspaceCwd(name) {
  var card = findWorkspaceCard(name);
  if (!card) {
    showToast('Workspace not found', 'err');
    return;
  }

  var state = readWorkspaceCardState(card, name);
  if (!state.cwd) return;

  var deleted = false;
  var errorMsg = 'Failed to clear auto-detect directory';

  callApi('delete_workspace', name).then(function(r) {
    if (!r || !r.ok) {
      throw new Error((r && r.msg) || errorMsg);
    }
    deleted = true;
    return callApi('save_workspace', name, state.label || name, state.collections, '');
  }).then(function(r) {
    if (r && r.ok) {
      showToast('Auto-detect directory cleared', 'ok');
      loadWorkspaces();
      return;
    }
    throw new Error((r && r.msg) || errorMsg);
  }).catch(function(err) {
    var message = String(err && err.message ? err.message : err);
    if (!deleted) {
      showToast(message, 'err');
      return;
    }
    callApi('save_workspace', name, state.label || name, state.collections, state.cwd).then(function(restoreRes) {
      if (!restoreRes || !restoreRes.ok) {
        showToast(message + ' Workspace restore failed.', 'err');
      } else {
        showToast(message, 'err');
      }
      loadWorkspaces();
    });
  });
}

function createWorkspace() {
  var nameInput = document.getElementById('newWorkspaceName');
  var labelInput = document.getElementById('newWorkspaceLabel');
  var cwdInput = document.getElementById('newWorkspaceCwd');
  var cols = document.getElementById('newWorkspaceCollections');
  var name = nameInput ? nameInput.value.trim() : '';
  var label = labelInput ? labelInput.value.trim() : '';
  var cwd = cwdInput ? cwdInput.value.trim() : '';

  if (!name) {
    showToast('Enter a workspace name', 'err');
    return;
  }
  if (!/^[a-z0-9][a-z0-9_-]*$/.test(name)) {
    showToast('Workspace name must be a slug: lowercase letters, numbers, - or _', 'err');
    return;
  }
  if (findWorkspaceCard(name)) {
    showToast('Workspace already exists', 'err');
    return;
  }

  callApi('save_workspace', name, label || name, readWorkspaceCollections(cols), cwd).then(function(r) {
    if (r && r.ok) {
      showToast(r.msg || ('Workspace "' + name + '" created'), 'ok');
      resetWorkspaceForm();
      loadWorkspaces();
    } else {
      showToast((r && r.msg) || 'Failed to create workspace', 'err');
    }
  });
}

function deleteWorkspace(name) {
  if (!confirm('Delete workspace "' + name + '"?')) return;
  callApi('delete_workspace', name).then(function(r) {
    if (r && r.ok) {
      showToast(r.msg || ('Workspace "' + name + '" deleted'), 'ok');
      loadWorkspaces();
    } else {
      showToast((r && r.msg) || 'Failed to delete workspace', 'err');
    }
  });
}

document.getElementById('btnWorkspaceToggle').addEventListener('click', function() {
  var form = document.getElementById('workspaceCreateForm');
  if (!form) return;
  form.classList.toggle('visible');
  if (form.classList.contains('visible')) {
    var nameInput = document.getElementById('newWorkspaceName');
    if (nameInput) nameInput.focus();
  }
});

document.getElementById('btnWorkspaceCancel').addEventListener('click', function() {
  resetWorkspaceForm();
});

document.getElementById('btnWorkspaceBrowseCwd').addEventListener('click', function() {
  callApi('browse_directory').then(function(r) {
    if (!r || !r.ok || !r.path) return;
    var input = document.getElementById('newWorkspaceCwd');
    var clearBtn = document.getElementById('btnWorkspaceClearCwd');
    if (!input) return;
    input.value = r.path;
    setWorkspaceCwdState(input, null, clearBtn);
  }).catch(function(err) {
    showToast(String(err), 'err');
  });
});

document.getElementById('btnWorkspaceClearCwd').addEventListener('click', function() {
  var input = document.getElementById('newWorkspaceCwd');
  var clearBtn = document.getElementById('btnWorkspaceClearCwd');
  if (!input) return;
  input.value = '';
  setWorkspaceCwdState(input, null, clearBtn);
});

document.getElementById('btnCreateWorkspace').addEventListener('click', function() {
  createWorkspace();
});

document.getElementById('newWorkspaceName').addEventListener('keydown', function(e) {
  if (e.key === 'Enter') createWorkspace();
});

document.getElementById('newWorkspaceLabel').addEventListener('keydown', function(e) {
  if (e.key === 'Enter') createWorkspace();
});

var currentProvider = 'ollama';
var launchDirDefaults = {};
var launchDirDefaultsLoaded = false;
var LAUNCH_DIR_DEFS = [
  { id: 'claude', label: 'Claude', color: '#FF7820' },
  { id: 'gemini', label: 'Gemini', color: '#4285f4' },
  { id: 'codex',  label: 'Codex',  color: '#10a37f' }
];

function setProvider(name) {
  document.querySelectorAll('.provider-card').forEach(function(c) {
    c.classList.toggle('selected', c.getAttribute('data-provider') === name);
  });
  currentProvider = name;
  var ollamaSection = document.getElementById('ollamaStatusSection');
  if (ollamaSection) ollamaSection.style.display = name === 'ollama' ? '' : 'none';
}

document.querySelectorAll('.provider-card').forEach(function(card) {
  card.addEventListener('click', function() {
    var provider = card.getAttribute('data-provider');
    setProvider(provider);
    populateModelSelect(provider);
  });
});

function getLaunchDirInputId(cli) {
  return 'launchDirInput-' + cli;
}

function getLaunchDirInput(cli) {
  return document.getElementById(getLaunchDirInputId(cli));
}

function ensureLaunchDirsSection() {
  var host = document.getElementById('launchDirsSectionHost');
  if (!host || host.childNodes.length) return;

  var section = document.createElement('div');
  section.className = 'settings-section';

  var title = document.createElement('div');
  title.className = 'settings-section-title';
  title.textContent = 'Launch Directories';

  var subtitle = document.createElement('div');
  subtitle.className = 'launch-dir-subtitle';
  subtitle.textContent = 'Where each CLI opens when launched from the controller';

  var card = document.createElement('div');
  card.className = 'card';
  card.style.marginBottom = '0';

  LAUNCH_DIR_DEFS.forEach(function(def) {
    var row = document.createElement('div');
    row.className = 'launch-dir-row';

    var label = document.createElement('div');
    label.className = 'launch-dir-label';
    label.textContent = def.label;
    label.style.color = def.color;

    var input = document.createElement('input');
    input.type = 'text';
    input.className = 'launch-dir-input';
    input.id = getLaunchDirInputId(def.id);
    input.readOnly = true;
    input.placeholder = 'Loading...';

    var actions = document.createElement('div');
    actions.className = 'launch-dir-actions';

    var browseBtn = document.createElement('button');
    browseBtn.type = 'button';
    browseBtn.className = 'btn btn-secondary btn-sm';
    browseBtn.textContent = 'Browse';
    browseBtn.addEventListener('click', function() {
      browseLaunchDir(def.id);
    });

    var resetBtn = document.createElement('button');
    resetBtn.type = 'button';
    resetBtn.className = 'btn btn-secondary btn-sm';
    resetBtn.textContent = 'Reset to Home';
    resetBtn.addEventListener('click', function() {
      resetLaunchDir(def.id);
    });

    actions.appendChild(browseBtn);
    actions.appendChild(resetBtn);
    row.appendChild(label);
    row.appendChild(input);
    row.appendChild(actions);
    card.appendChild(row);
  });

  section.appendChild(title);
  section.appendChild(subtitle);
  section.appendChild(card);
  host.appendChild(section);
}

function setLaunchDirInputs(dirs) {
  LAUNCH_DIR_DEFS.forEach(function(def) {
    var input = getLaunchDirInput(def.id);
    if (input) input.value = dirs && dirs[def.id] ? dirs[def.id] : '';
  });
}

function setLaunchDirValue(cli, value) {
  var input = getLaunchDirInput(cli);
  if (input) input.value = value || '';
}

function loadLaunchDirs() {
  ensureLaunchDirsSection();
  callApi('get_launch_dirs').then(function(r) {
    if (!r || !r.ok || !r.dirs) {
      setLaunchDirInputs({});
      return;
    }

    if (!launchDirDefaultsLoaded) {
      LAUNCH_DIR_DEFS.forEach(function(def) {
        launchDirDefaults[def.id] = r.dirs[def.id] || '';
      });
      launchDirDefaultsLoaded = true;
    }

    setLaunchDirInputs(r.dirs);
  });
}

function saveLaunchDir(cli, path) {
  return callApi('set_launch_dir', cli, path).then(function(r) {
    if (r && r.ok) {
      setLaunchDirValue(cli, path);
      showToast((r.msg) || 'Launch directory updated', 'ok');
      return true;
    }
    showToast((r && r.msg) || 'Failed to update launch directory', 'err');
    return false;
  });
}

function browseLaunchDir(cli) {
  callApi('browse_directory').then(function(r) {
    if (!r || !r.ok || !r.path) return;
    saveLaunchDir(cli, r.path);
  });
}

function resetLaunchDir(cli) {
  var homePath = launchDirDefaults[cli] || '';
  if (!homePath) {
    showToast('Home path unavailable', 'err');
    return;
  }
  saveLaunchDir(cli, homePath);
}

function loadSettings() {
  callApi('get_config').then(function(r) {
    if (!r) return;
    var provider = r.embedding_provider || 'ollama';

    var be = document.getElementById('backendSelect');
    if (be && r.backend) {
      var backendValue = r.backend === 'chroma' ? 'chromadb' : (r.backend === 'sqlite_vss' ? 'sqlite-vec' : r.backend);
      be.value = backendValue;
      if (be.value !== backendValue) be.value = 'chromadb';
    }

    var nm = document.getElementById('namespaceModeSelect');
    if (nm) nm.value = r.namespace_mode || 'scoped';

    var dd = document.getElementById('dataDir');
    if (dd && r.data_dir) dd.value = r.data_dir;

    var ou = document.getElementById('ollamaUrl');
    if (ou) ou.value = (r.ollama_url || 'http://localhost:11434/api/embeddings')
      .replace('/api/embeddings', '')
      .replace('/api/embed', '');

    var st = document.getElementById('simThreshold');
    if (st && r.similarity_threshold != null) st.value = r.similarity_threshold;

    var mr = document.getElementById('maxResults');
    if (mr && r.max_results != null) mr.value = r.max_results;

    var mp = document.getElementById('maxPreviewChars');
    if (mp && r.max_preview != null) mp.value = r.max_preview;

    var aq = document.getElementById('autoQueryToggle');
    if (aq) aq.checked = (String(r.auto_query).toLowerCase() === 'true');

    var ems = document.getElementById('embeddingModelSelect');
    if (ems) {
      var p = provider;
      var model = r.embedding_model || '';
      if (p === 'openai') model = r.openai_embedding_model || model;
      if (p === 'google') model = r.google_embedding_model || model;
      if (p === 'openrouter') model = r.openrouter_embedding_model || model;
      ems.dataset.current = model;
    }

    markSavedProviderKey('openai', r.openai_key);
    markSavedProviderKey('google', r.google_key);
    markSavedProviderKey('openrouter', r.openrouter_key);

    setProvider(provider);
    populateModelSelect(provider);
    if (provider === 'ollama') {
      checkOllamaStatus();
    }

    // Reset re-embed warning on load
    var warn = document.getElementById('modelChangeWarning');
    if (warn) warn.style.display = 'none';
    var ems = document.getElementById('embeddingModelSelect');
    if (ems) ems.dataset.initial = ems.dataset.current || ems.value;
    
  });
}

var PROVIDER_MODELS = {};

function getProviderKeyValue(provider) {
  var inputMap = { openai: 'keyOpenAI', google: 'keyGoogle', openrouter: 'keyOpenRouter' };
  var input = document.getElementById(inputMap[provider]);
  return input ? input.value.trim() : '';
}

function markSavedProviderKey(provider, savedValue) {
  var inputMap = { openai: 'keyOpenAI', google: 'keyGoogle', openrouter: 'keyOpenRouter' };
  var statusEl = document.getElementById('verifyStatus-' + provider);
  var input = document.getElementById(inputMap[provider]);
  var hasSaved = !!savedValue;
  if (input) {
    input.dataset.saved = hasSaved ? 'true' : 'false';
    if (hasSaved && !input.value) input.placeholder = 'Saved key configured';
  }
  if (statusEl && hasSaved) {
    statusEl.textContent = 'Saved key configured';
    statusEl.className = 'verify-status saved';
  } else if (statusEl && !hasSaved && statusEl.className.indexOf('verify-status') === 0) {
    statusEl.textContent = '';
    statusEl.className = 'verify-status';
  }
}

function populateModelSelect(provider) {
  var sel = document.getElementById('embeddingModelSelect');
  if (!sel) return;
  var current = sel.dataset.current || '';

  // Ollama: live Ollama discovery
  if (provider === 'ollama') {
    loadOllamaModels();
    return;
  }

  // Everyone else: ask the backend (OpenAI=live fetch, Google=best-effort, OpenRouter=supported list)
  sel.innerHTML = '';
  var loading = document.createElement('option');
  loading.value = '';
  loading.textContent = 'Loading models...';
  sel.appendChild(loading);
  sel.disabled = true;

  var cacheKey = provider + '_models';
  var keyValue = getProviderKeyValue(provider);
  var cached = keyValue ? '' : sel.dataset[cacheKey];
  if (cached) {
    try {
      var parsed = JSON.parse(cached);
      if (parsed.length > 0) {
        _fillModelSelectFromData(sel, parsed, current);
        return;
      }
    } catch (e) {}
  }

  callApi('get_provider_models', provider, keyValue).then(function(r) {
    if (!r || !r.ok || !r.models || r.models.length === 0) {
      sel.innerHTML = '';
      var opt = document.createElement('option');
      opt.value = current || '';
      opt.textContent = (r && r.msg) ? ('Could not load: ' + r.msg) : 'No models available';
      sel.appendChild(opt);
      sel.disabled = false;
      return;
    }
    _fillModelSelectFromData(sel, r.models, current);
    if (r.live && !keyValue) sel.dataset[cacheKey] = JSON.stringify(r.models);
  });
}

function _fillModelSelectFromData(sel, models, current) {
  sel.innerHTML = '';
  sel.disabled = false;
  models.forEach(function(m) {
    var opt = document.createElement('option');
    opt.value = m.id || m.name;
    var label = m.name || m.id;
    if (m.description) label += ' \u2014 ' + m.description;
    opt.textContent = label;
    var val = m.id || m.name;
    if (val === current || current.indexOf(val) === 0) opt.selected = true;
    sel.appendChild(opt);
  });
  if (!sel.value && models.length > 0) sel.value = models[0].id || models[0].name;
}

document.getElementById('embeddingModelSelect').addEventListener('change', function() {
  var warn = document.getElementById('modelChangeWarning');
  if (warn) warn.style.display = '';
});

function checkOllamaStatus() {
  var dot = document.getElementById('ollamaStatusDot');
  var txt = document.getElementById('ollamaStatusText');
  if (dot) dot.className = 'status-dot';
  if (txt) txt.textContent = 'Checking...';
  callApi('test_ollama').then(function(r) {
    if (r && r.ok) {
      if (dot) dot.className = 'status-dot ok';
      if (txt) txt.textContent = r.msg || 'Connected';
    } else {
      if (dot) dot.className = 'status-dot err';
      if (txt) txt.textContent = (r && r.msg) || 'Not reachable';
    }
  });
}

document.getElementById('btnCheckOllama').addEventListener('click', function() {
  checkOllamaStatus();
  loadOllamaModels();
});

// ── Verify Provider Keys ────────────────────────────

function verifyKey(provider) {
  var statusEl = document.getElementById('verifyStatus-' + provider);
  if (!statusEl) return;

  // Grab the key from the input field (it may not be saved yet)
  var keyValue = getProviderKeyValue(provider);

  statusEl.textContent = 'Testing...';
  statusEl.className = 'verify-status testing';
  callApi('verify_provider_auth', provider, keyValue).then(function(r) {
    if (r && r.ok) {
      statusEl.textContent = (r.msg || 'Connected') + '; saved';
      statusEl.className = 'verify-status ok';
      saveCurrentSettings({ silent: true, skipVerify: true });
      var sel = document.getElementById('embeddingModelSelect');
      if (sel && currentProvider === provider) {
        delete sel.dataset[provider + '_models'];
        populateModelSelect(provider);
      }
    } else {
      statusEl.textContent = (r && r.msg) || 'Failed';
      statusEl.className = 'verify-status err';
    }
  });
}

function verifyModelCheck() {
  var provider = currentProvider;
  var sel = document.getElementById('embeddingModelSelect');
  var statusEl = document.getElementById('verifyModelStatus');
  if (!sel || !statusEl) return;
  var model = sel.value.trim();
  if (!model) return;
  statusEl.textContent = 'Verifying...';
  statusEl.className = 'verify-status testing';
  callApi('verify_model', provider, model).then(function(r) {
    if (r && r.ok) {
      statusEl.textContent = r.msg || 'Ready';
      statusEl.className = 'verify-status ok';
    } else {
      statusEl.textContent = (r && r.msg) || 'Not validated';
      statusEl.className = 'verify-status err';
    }
  });
}

function loadOllamaModels() {
  var sel = document.getElementById('embeddingModelSelect');
  if (!sel) return;
  var current = sel.dataset.current || '';

  sel.innerHTML = '';
  var loading = document.createElement('option');
  loading.value = '';
  loading.textContent = 'Detecting Ollama models...';
  sel.appendChild(loading);
  sel.disabled = true;

  callApi('get_ollama_models').then(function(r) {
    sel.innerHTML = '';
    sel.disabled = false;

    if (!r || !r.ok || !r.models || r.models.length === 0) {
      var opt = document.createElement('option');
      opt.value = current || 'bge-m3';
      opt.textContent = (r && r.msg) ? r.msg : 'No models — run: ollama pull bge-m3';
      sel.appendChild(opt);
      return;
    }

    var hasSelected = false;
    var embeds = r.models.filter(function(m) { return m.is_embedding; });
    var others = r.models.filter(function(m) { return !m.is_embedding; });

    if (embeds.length > 0) {
      var grp = document.createElement('optgroup');
      grp.label = 'Embedding Models';
      embeds.forEach(function(m) {
        var opt = document.createElement('option');
        opt.value = m.name;
        opt.textContent = m.name + (m.size_gb ? ' (' + m.size_gb + ' GB)' : '');
        if (!hasSelected && (m.name === current || current.indexOf(m.name.split(':')[0]) === 0)) {
          opt.selected = true;
          hasSelected = true;
        }
        grp.appendChild(opt);
      });
      sel.appendChild(grp);
    }

    if (others.length > 0) {
      var grp2 = document.createElement('optgroup');
      grp2.label = 'Other Models';
      others.forEach(function(m) {
        var opt = document.createElement('option');
        opt.value = m.name;
        opt.textContent = m.name + (m.size_gb ? ' (' + m.size_gb + ' GB)' : '');
        if (!hasSelected && m.name === current) {
          opt.selected = true;
          hasSelected = true;
        }
        grp2.appendChild(opt);
      });
      sel.appendChild(grp2);
    }

    if (!hasSelected && r.models.length > 0) {
      var fallback = r.models.find(function(m) { return m.name === 'bge-m3' || m.name.indexOf('bge-m3:') === 0; });
      sel.value = (fallback || r.models[0]).name;
    }
  });
}

document.getElementById('embeddingModelSelect').addEventListener('change', function() {
  var model = this.value;
  if (!model) return;

  var warn = document.getElementById('modelChangeWarning');
  if (warn) warn.style.display = '';
  verifyModelCheck();
});

document.getElementById('btnBrowse').addEventListener('click', function() {
  callApi('browse_directory').then(function(r) {
    if (r && r.ok && r.path) document.getElementById('dataDir').value = r.path;
  });
});

var promoLink = document.getElementById('promoLink');
if (promoLink) {
  promoLink.addEventListener('click', function(ev) {
    ev.preventDefault();
    openExternalUrl(promoLink.href);
  });
}

function collectSettingsConfig() {
  var config = {
    embedding_provider:  currentProvider,
    backend:             document.getElementById('backendSelect').value,
    namespace_mode:      document.getElementById('namespaceModeSelect').value,
    data_dir:            document.getElementById('dataDir').value.trim(),
    ollama_url:           document.getElementById('ollamaUrl').value.trim(),
    similarity_threshold: safeNum(document.getElementById('simThreshold').value, 0.45),
    max_results:          parseInt(document.getElementById('maxResults').value, 10) || 5,
    max_preview_chars:    parseInt(document.getElementById('maxPreviewChars').value, 10) || 800,
    auto_query:           document.getElementById('autoQueryToggle').checked ? 'true' : 'false'
  };
  var oKey = document.getElementById('keyOpenAI').value.trim();
  var gKey = document.getElementById('keyGoogle').value.trim();
  var orKey = document.getElementById('keyOpenRouter').value.trim();
  var emVal = document.getElementById('embeddingModelSelect').value.trim();
  if (oKey) config.openai_api_key = oKey;
  if (gKey) config.google_api_key = gKey;
  if (orKey) config.openrouter_api_key = orKey;
  if (emVal) {
    if (currentProvider === 'openrouter') config.openrouter_embedding_model = emVal;
    else if (currentProvider === 'openai') config.openai_embedding_model = emVal;
    else if (currentProvider === 'google') config.google_embedding_model = emVal;
    else config.embedding_model = emVal;
  }
  return config;
}

function saveCurrentSettings(options) {
  options = options || {};
  var config = collectSettingsConfig();

  // Detect model change for re-embed warning
  var ems = document.getElementById('embeddingModelSelect');
  var modelChanged = ems && ems.dataset.initial && ems.value !== ems.dataset.initial;

  return callApi('save_settings', config).then(function(r) {
    if (r && r.ok) {
      var msg = (r.msg) || 'Settings saved';
      if (modelChanged) msg += '. Re-embed your data with: ember_memory.ingest --rebuild-all';
      if (!options.silent) showToast(msg, modelChanged ? 'warn' : 'ok');
      markSavedProviderKey('openai', config.openai_api_key || document.getElementById('keyOpenAI').dataset.saved === 'true');
      markSavedProviderKey('google', config.google_api_key || document.getElementById('keyGoogle').dataset.saved === 'true');
      markSavedProviderKey('openrouter', config.openrouter_api_key || document.getElementById('keyOpenRouter').dataset.saved === 'true');
      if (!options.skipVerify && currentProvider !== 'ollama') verifyKey(currentProvider);
    } else {
      showToast((r && r.msg) || 'Save failed', 'err');
    }
  });
}

document.getElementById('btnSaveSettings').addEventListener('click', function() {
  saveCurrentSettings();
});

var btnSaveProviderSettings = document.getElementById('btnSaveProviderSettings');
if (btnSaveProviderSettings) {
  btnSaveProviderSettings.addEventListener('click', function() {
    saveCurrentSettings();
  });
}

['ollamaUrl', 'keyOpenAI', 'keyGoogle', 'keyOpenRouter', 'embeddingModelSelect'].forEach(function(id) {
  var field = document.getElementById(id);
  if (!field) return;
  field.addEventListener('keydown', function(ev) {
    if (ev.key === 'Enter') {
      ev.preventDefault();
      saveCurrentSettings();
    }
  });
});

var customCliIdDirty = false;

function slugifyCustomCliId(value) {
  return String(value || '')
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

function addCustomCliFromForm() {
  var nameInput = document.getElementById('customCliName');
  var idInput = document.getElementById('customCliId');
  var cliName = nameInput ? nameInput.value.trim() : '';
  var cliId = idInput ? slugifyCustomCliId(idInput.value) : '';
  if (!cliName) {
    showToast('Add an AI app name first', 'err');
    if (nameInput) nameInput.focus();
    return;
  }
  if (!cliId) {
    showToast('Add a memory label first', 'err');
    if (idInput) idInput.focus();
    return;
  }

  callApi('add_custom_cli', cliId, cliName).then(function(r) {
    if (r && r.ok) {
      showToast(r.msg || 'AI app added', 'ok');
      if (nameInput) nameInput.value = '';
      if (idInput) idInput.value = '';
      customCliIdDirty = false;
      loadCustomClis();
    } else {
      showToast((r && r.msg) || 'Failed to add AI app', 'err');
    }
  });
}

var customCliNameInput = document.getElementById('customCliName');
var customCliIdInput = document.getElementById('customCliId');
if (customCliNameInput) {
  customCliNameInput.addEventListener('input', function() {
    if (customCliIdInput && !customCliIdDirty) {
      customCliIdInput.value = slugifyCustomCliId(customCliNameInput.value);
    }
  });
  customCliNameInput.addEventListener('keydown', function(e) {
    if (e.key === 'Enter') addCustomCliFromForm();
  });
}
if (customCliIdInput) {
  customCliIdInput.addEventListener('input', function() {
    customCliIdDirty = true;
    customCliIdInput.value = slugifyCustomCliId(customCliIdInput.value);
  });
  customCliIdInput.addEventListener('keydown', function(e) {
    if (e.key === 'Enter') addCustomCliFromForm();
  });
}

document.getElementById('btnAddCustomCli').addEventListener('click', addCustomCliFromForm);

function buildSnippetBlock(title, note, text) {
  var block = document.createElement('div');
  block.className = 'snippet-block';

  var head = document.createElement('div');
  head.className = 'snippet-head';
  head.appendChild(el('div', 'snippet-title', title));

  var copyBtn = document.createElement('button');
  copyBtn.className = 'btn btn-secondary btn-sm';
  copyBtn.textContent = 'Copy';
  copyBtn.addEventListener('click', function() {
    copyTextToClipboard(text || '').then(function() {
      showToast('Copied', 'ok');
    }).catch(function() {
      showToast('Unable to copy', 'err');
    });
  });
  head.appendChild(copyBtn);

  if (note) {
    block.appendChild(head);
    block.appendChild(el('div', 'snippet-note', note));
  } else {
    block.appendChild(head);
  }

  var code = document.createElement('div');
  code.className = 'snippet-code';
  code.textContent = text || '';

  block.appendChild(code);
  return block;
}

function buildPartnerSetupPrompt(c) {
  return [
    'I am setting up Ember Memory for this AI app.',
    '',
    'App name: ' + (c.name || c.id),
    'Memory label: ' + c.id,
    '',
    'Please help me connect this app to Ember Memory cleanly and safely. First, check whether this app supports MCP servers, prompt hooks, pre-prompt commands, or custom commands that receive the prompt through stdin.',
    '',
    'Before changing anything, please back up any config file you edit or show me the exact backup command. Then make the smallest safe change, check that the config format stays valid, and explain what changed in plain language.',
    '',
    'If the app supports MCP, please help me add this MCP server config safely:',
    '',
    c.mcp_config || '',
    '',
    'If the app supports prompt hooks or pre-prompt commands, please help me add this hook command safely:',
    '',
    c.hook_cmd || '',
    '',
    'If neither integration type is supported, tell me that clearly and suggest the closest manual workflow using Ember Memory search/store tools. Please explain each step for someone who is not technical.'
  ].join('\n');
}

function buildCustomCliCard(c, ignored) {
  var card = document.createElement('div');
  card.className = 'custom-cli-card';

  var main = document.createElement('div');
  main.className = 'custom-cli-main';
  main.appendChild(el('div', 'custom-cli-name', c.name || c.id));
  main.appendChild(el('div', 'custom-cli-id', 'ID: ' + c.id));
  if (ignored) {
    main.appendChild(el('span', 'badge badge-warn', 'Basic RAG Mode'));
  }

  var btn = document.createElement('button');
  btn.className = 'btn btn-danger btn-sm';
  btn.textContent = 'Remove';
  btn.addEventListener('click', function() {
    removeCustomCli(c.id);
  });
  main.appendChild(btn);
  card.appendChild(main);

  card.appendChild(el(
    'div',
    'custom-cli-help',
    'This creates a separate memory lane in Ember Memory. It does not install or modify the AI app. Use the instructions below when you are ready to connect that app.'
  ));

  var toggleRow = document.createElement('label');
  toggleRow.className = 'toggle-row';

  var toggleWrap = document.createElement('label');
  toggleWrap.className = 'toggle';
  toggleWrap.title = 'Pause adaptive Engine scoring and heat growth for this lane';

  var checkbox = document.createElement('input');
  checkbox.type = 'checkbox';
  checkbox.className = 'ignore-toggle';
  if (ignored) checkbox.checked = true;

  var track = document.createElement('div');
  track.className = 'toggle-track';

  var thumb = document.createElement('div');
  thumb.className = 'toggle-thumb';

  toggleWrap.appendChild(checkbox);
  toggleWrap.appendChild(track);
  toggleWrap.appendChild(thumb);
  toggleRow.appendChild(toggleWrap);
  toggleRow.appendChild(el('span', null, 'Use basic RAG (pause adaptive heat)'));
  card.appendChild(toggleRow);

  checkbox.addEventListener('change', function() {
    callApi('toggle_cli_ignore', c.id).then(function(r) {
      if (r && r.ok !== undefined) {
        showToast(
          (c.name || c.id) + (r.ignored ? ': basic RAG mode enabled' : ': adaptive heat active'),
          r.ignored ? 'inf' : 'ok'
        );
        loadCustomClis();
        loadDashboard();
      } else {
        checkbox.checked = !checkbox.checked;
        showToast('Toggle failed', 'err');
      }
    });
  });

  var details = document.createElement('details');
  details.className = 'custom-cli-details';
  var summary = document.createElement('summary');
  summary.textContent = 'Connection instructions';
  details.appendChild(summary);
  details.appendChild(buildSnippetBlock(
    'Prompt hook',
    'Use this when the app has a setting named hooks, pre-prompt command, prompt command, custom command, BeforeAgent, or UserPromptSubmit. A quick check: search that app\'s settings or docs for "hook" or "stdin". If it says the current prompt is sent to the command through standard input/stdin, this is the snippet to use.',
    c.hook_cmd || ''
  ));
  details.appendChild(buildSnippetBlock(
    'MCP server',
    'Use this when the app has an MCP servers section. Common local config places: Linux: ~/.claude.json, ~/.gemini/settings.json, ~/.codex/config.toml. Windows: %USERPROFILE%\\.claude.json, %USERPROFILE%\\.gemini\\settings.json, %USERPROFILE%\\.codex\\config.toml. Other apps may keep MCP settings in their own settings screen.',
    c.mcp_config || ''
  ));
  details.appendChild(buildSnippetBlock(
    'Ask your AI to help',
    'Copy this prompt into the AI app you are connecting, or into an assistant that can help edit files safely. It includes the exact snippets and asks for backups before changes.',
    buildPartnerSetupPrompt(c)
  ));
  card.appendChild(details);

  return card;
}

function loadCustomClis() {
  Promise.all([
    callApi('get_custom_clis'),
    callApi('get_engine_stats')
  ]).then(function(results) {
    var r = results[0];
    var statsR = results[1];
    var pList = document.getElementById('customClisList');
    if (!pList) return;
    pList.innerHTML = '';
    var ignored = (statsR && statsR.stats && statsR.stats.ignored_clis) || {};
    renderCustomCliFilters((r && r.ok && r.clis) ? r.clis : []);
    if (!r || !r.ok || !r.clis || r.clis.length === 0) {
      pList.innerHTML = '<div class="setting-hint">No additional AI app lanes yet.</div>';
      return;
    }
    r.clis.forEach(function(c) {
      pList.appendChild(buildCustomCliCard(c, !!ignored[c.id]));
    });
  });
}

function removeCustomCli(cliId) {
  if (!confirm("Remove the memory lane '" + cliId + "'?")) return;
  callApi('remove_custom_cli', cliId).then(function(r) {
    if (r && r.ok) {
      showToast(r.msg, 'ok');
      loadCustomClis();
    } else {
      showToast((r && r.msg) || 'Failed to remove lane', 'err');
    }
  });
}

// =====================================================
// CLI STATUS
// =====================================================

var cliIgnored = { claude: false, gemini: false, codex: false };

var CLI_DEFS = [
  { id: 'claude', label: 'Claude Code', launchLabel: 'Claude', icon: '\u25C6' },
  { id: 'gemini', label: 'Gemini CLI',  launchLabel: 'Gemini', icon: '\u2746' },
  { id: 'codex',  label: 'Codex',       launchLabel: 'Codex', icon: '\u2B21' }
];

function buildCLICard(def, info, ignored) {
  var card = document.createElement('div');
  card.className = 'cli-card';
  card.id = 'cli-card-' + def.id;

  var nameEl = el('div', 'cli-name', def.icon + ' ' + def.label);
  var pathEl = el('div', 'cli-path', info.path || '\u2014');

  var badgeRow = document.createElement('div');
  badgeRow.className = 'cli-badges';

  var instBadge = el('span', 'badge ' + (info.installed ? 'badge-ok' : 'badge-err'),
    info.installed ? '\u2713 Installed' : '\u2717 Not found');
  badgeRow.appendChild(instBadge);

  if (ignored) {
    badgeRow.appendChild(el('span', 'badge badge-warn', 'Basic RAG Mode'));
  }

  // Toggle row
  var toggleRow = document.createElement('label');
  toggleRow.className = 'toggle-row';

  var toggleWrap = document.createElement('label');
  toggleWrap.className = 'toggle';
  toggleWrap.title = 'Pause adaptive Engine scoring and heat growth for this CLI';

  var checkbox = document.createElement('input');
  checkbox.type = 'checkbox';
  checkbox.className = 'ignore-toggle';
  if (ignored) checkbox.checked = true;

  var track = document.createElement('div');
  track.className = 'toggle-track';

  var thumb = document.createElement('div');
  thumb.className = 'toggle-thumb';

  toggleWrap.appendChild(checkbox);
  toggleWrap.appendChild(track);
  toggleWrap.appendChild(thumb);

  toggleRow.appendChild(toggleWrap);
  toggleRow.appendChild(el('span', null, 'Use basic RAG (pause adaptive heat)'));

  card.appendChild(nameEl);
  card.appendChild(pathEl);
  card.appendChild(badgeRow);
  card.appendChild(toggleRow);

  checkbox.addEventListener('change', function() {
    callApi('toggle_cli_ignore', def.id).then(function(r) {
      if (r && r.ok !== undefined) {
        cliIgnored[def.id] = r.ignored;
        var existingWarn = badgeRow.querySelector('.badge-warn');
        if (r.ignored) {
          if (!existingWarn) badgeRow.appendChild(el('span', 'badge badge-warn', 'Basic RAG Mode'));
          showToast(def.label + ': basic RAG mode enabled', 'inf');
        } else {
          if (existingWarn) existingWarn.remove();
          showToast(def.label + ': adaptive heat active', 'ok');
        }
      } else {
        checkbox.checked = !checkbox.checked;
        showToast('Toggle failed', 'err');
      }
    });
  });

  return card;
}

function loadCLIStatus() {
  var grid = document.getElementById('cliGrid');
  grid.textContent = '';
  var loadRow = document.createElement('div');
  loadRow.className = 'loading-text';
  var spin = document.createElement('div');
  spin.className = 'spinner';
  loadRow.appendChild(spin);
  loadRow.appendChild(el('span', null, ' Detecting CLIs...'));
  grid.appendChild(loadRow);

  Promise.all([
    callApi('detect_clis'),
    callApi('get_engine_stats')
  ]).then(function(results) {
    var cliR   = results[0];
    var statsR = results[1];
    var clis    = (cliR && cliR.clis)   || {};
    var ignored = (statsR && statsR.stats && statsR.stats.ignored_clis) || {};
    setDetectedCLIs(clis);

    cliIgnored = Object.assign({}, ignored);

    grid.textContent = '';
    CLI_DEFS.forEach(function(def) {
      var info = clis[def.id] || {};
      grid.appendChild(buildCLICard(def, info, !!cliIgnored[def.id]));
    });
    loadCustomClis();
  });
}

document.getElementById('btnInstallAll').addEventListener('click', function() {
  var btn = document.getElementById('btnInstallAll');
  var resultEl = document.getElementById('installResult');
  btn.disabled = true;
  btn.textContent = 'Installing...';
  if (resultEl) {
    resultEl.className = 'install-result';
    resultEl.textContent = 'Writing CLI config files...';
  }
  callApi('run_install').then(function(r) {
    btn.disabled = false;
    btn.textContent = 'Run Install';
    if (r && r.ok) {
      if (resultEl) {
        resultEl.className = 'install-result ok';
        resultEl.textContent = r.msg || 'Install complete. Restart your CLIs to activate hooks.';
      }
      showToast((r.msg) || 'Install complete', 'ok');
      loadCLIStatus();
    } else {
      if (resultEl) {
        resultEl.className = 'install-result err';
        resultEl.textContent = (r && r.msg) || 'Install failed';
      }
      showToast((r && r.msg) || 'Install failed', 'err');
    }
  }).catch(function(err) {
    btn.disabled = false;
    btn.textContent = 'Run Install';
    if (resultEl) {
      resultEl.className = 'install-result err';
      resultEl.textContent = 'Install failed: ' + err;
    }
    showToast('Install failed: ' + err, 'err');
  });
});

function renderHookSelfTest(r) {
  var area = document.getElementById('hookTestResult');
  if (!area) return;
  area.textContent = '';

  (r.results || []).forEach(function(item) {
    var row = document.createElement('div');
    row.className = 'hook-test-row ' + (item.ok ? 'ok' : 'err');

    var label = document.createElement('div');
    label.className = 'hook-test-label';
    label.textContent = item.label || item.id;
    row.appendChild(label);

    var detail = document.createElement('div');
    var parts = [];
    parts.push(item.logged ? 'logged' : 'not logged');
    if (item.hook_status) parts.push(item.hook_status);
    if (item.hits !== null && item.hits !== undefined) parts.push(String(item.hits) + ' hits');
    if (item.returncode !== null && item.returncode !== undefined) parts.push('exit ' + item.returncode);
    detail.textContent = item.msg || parts.join(' \u2022 ');
    row.appendChild(detail);

    area.appendChild(row);
  });

  if (r.log_path) {
    var logRow = document.createElement('div');
    logRow.className = 'setting-hint';
    logRow.textContent = 'Trace: ' + r.log_path;
    area.appendChild(logRow);
  }
}

document.getElementById('btnHookSelfTest').addEventListener('click', function() {
  var btn = document.getElementById('btnHookSelfTest');
  var area = document.getElementById('hookTestResult');
  btn.disabled = true;
  btn.textContent = 'Testing...';
  if (area) {
    area.textContent = 'Running hook commands...';
  }
  callApi('run_hook_self_test').then(function(r) {
    btn.disabled = false;
    btn.textContent = 'Test Hooks';
    renderHookSelfTest(r || { results: [] });
    showToast((r && r.msg) || 'Hook self-test complete', r && r.ok ? 'ok' : 'warn');
  }).catch(function(err) {
    btn.disabled = false;
    btn.textContent = 'Test Hooks';
    if (area) {
      area.textContent = 'Hook self-test failed: ' + err;
    }
    showToast('Hook self-test failed: ' + err, 'err');
  });
});

// =====================================================
// DESKTOP APP LAUNCHER
// =====================================================

function loadDesktopLauncherStatus() {
  callApi('get_desktop_launcher_status').then(function(r) {
    var badge = document.getElementById('desktopStatusBadge');
    var installBtn = document.getElementById('btnInstallDesktop');
    var uninstallBtn = document.getElementById('btnUninstallDesktop');
    if (!r || !badge || !installBtn || !uninstallBtn) return;

    if (r.installed) {
      badge.textContent = 'Installed';
      badge.style.background = '#22c55e';
      badge.style.color = '#fff';
      installBtn.style.display = 'none';
      uninstallBtn.style.display = 'inline-block';
    } else {
      badge.textContent = r.ok === false ? 'Unavailable' : 'Not Installed';
      badge.style.background = '#333';
      badge.style.color = '#aaa';
      installBtn.style.display = r.ok === false ? 'none' : 'inline-block';
      uninstallBtn.style.display = 'none';
    }
  }).catch(function() {});
}

function installDesktopLauncher() {
  var btn = document.getElementById('btnInstallDesktop');
  if (btn) {
    btn.disabled = true;
    btn.textContent = 'Installing...';
  }
  callApi('install_desktop_launcher').then(function(r) {
    if (btn) {
      btn.disabled = false;
      btn.textContent = 'Install App Launcher';
    }
    if (r && r.ok) {
      showToast(r.msg || 'App launcher installed', 'ok');
      loadDesktopLauncherStatus();
    } else {
      showToast((r && r.msg) || 'Launcher install failed', 'err');
    }
  }).catch(function(err) {
    if (btn) {
      btn.disabled = false;
      btn.textContent = 'Install App Launcher';
    }
    showToast('Launcher install failed: ' + err, 'err');
  });
}

function uninstallDesktopLauncher() {
  var btn = document.getElementById('btnUninstallDesktop');
  if (btn) {
    btn.disabled = true;
    btn.textContent = 'Removing...';
  }
  callApi('uninstall_desktop_launcher').then(function(r) {
    if (btn) {
      btn.disabled = false;
      btn.textContent = 'Remove Launcher';
    }
    if (r && r.ok) {
      showToast(r.msg || 'App launcher removed', 'ok');
      loadDesktopLauncherStatus();
    } else {
      showToast((r && r.msg) || 'Launcher removal failed', 'err');
    }
  }).catch(function(err) {
    if (btn) {
      btn.disabled = false;
      btn.textContent = 'Remove Launcher';
    }
    showToast('Launcher removal failed: ' + err, 'err');
  });
}

// Add event listeners for desktop app controls
document.addEventListener('DOMContentLoaded', function() {
  var installDesktopBtn = document.getElementById('btnInstallDesktop');
  var uninstallDesktopBtn = document.getElementById('btnUninstallDesktop');

  if (installDesktopBtn) {
    installDesktopBtn.addEventListener('click', installDesktopLauncher);
  }
  if (uninstallDesktopBtn) {
    uninstallDesktopBtn.addEventListener('click', uninstallDesktopLauncher);
  }
});

// =====================================================
// INIT
// =====================================================

function init() {
  initTabs();
  initAiFilters();
  initSessionFilter();
  setTimeout(function() {
    getCollectionUiData(false).catch(function() {});
  }, 1000);
  // Load data for the default active tab
  var activeTab = document.querySelector('.tab-btn.active');
  var tab = activeTab ? activeTab.getAttribute('data-tab') : 'dashboard';
  if (tab === 'dashboard') {
    startDashRefresh();
  } else if (tab === 'collections') {
    loadCollections();
    loadWorkspaces();
  } else if (tab === 'settings') {
    loadSettings();
    loadLaunchDirs();
  } else if (tab === 'cli') {
    loadCLIStatus();
    loadDesktopLauncherStatus();
  }
}

if (window.pywebview && window.pywebview.api) {
  init();
} else {
  window.addEventListener('pywebviewready', init);
}
