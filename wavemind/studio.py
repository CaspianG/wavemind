from __future__ import annotations

import math
import time
from typing import Any

import numpy as np


STUDIO_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>WaveMind Studio</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #070707;
      --panel: #101010;
      --panel-2: #171717;
      --border: #2a2a2a;
      --text: #f4f4f4;
      --muted: #a8a8a8;
      --strong: #ffffff;
      --accent: #8ee6b3;
      --accent-2: #6ab7ff;
      --warn: #ffd166;
      --bad: #ff7a7a;
      --radius: 8px;
    }
    [data-theme="light"] {
      color-scheme: light;
      --bg: #ffffff;
      --panel: #f7f7f7;
      --panel-2: #ffffff;
      --border: #d8d8d8;
      --text: #111111;
      --muted: #5d5d5d;
      --strong: #000000;
      --accent: #0f7a42;
      --accent-2: #075eab;
      --warn: #9a6700;
      --bad: #b42318;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font: 14px/1.45 Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      letter-spacing: 0;
    }
    button, input, select, textarea {
      font: inherit;
    }
    button {
      min-height: 36px;
      border: 1px solid var(--border);
      border-radius: 7px;
      background: var(--panel-2);
      color: var(--text);
      padding: 7px 10px;
      cursor: pointer;
    }
    button.primary {
      border-color: var(--accent);
      color: var(--strong);
      font-weight: 700;
    }
    button:disabled {
      cursor: not-allowed;
      opacity: .55;
    }
    input, select, textarea {
      width: 100%;
      min-height: 36px;
      border: 1px solid var(--border);
      border-radius: 7px;
      background: var(--panel-2);
      color: var(--text);
      padding: 8px 10px;
      outline: none;
    }
    textarea {
      min-height: 82px;
      resize: vertical;
    }
    .shell {
      max-width: 1240px;
      margin: 0 auto;
      padding: 22px;
    }
    header {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 18px;
    }
    h1 {
      margin: 0;
      font-size: 28px;
      line-height: 1.1;
      font-weight: 850;
    }
    h2 {
      margin: 0 0 12px;
      font-size: 15px;
      font-weight: 800;
    }
    p {
      margin: 7px 0 0;
      color: var(--muted);
    }
    .top-actions {
      display: flex;
      gap: 8px;
      align-items: center;
      flex-wrap: wrap;
      justify-content: flex-end;
    }
    .grid {
      display: grid;
      grid-template-columns: minmax(0, 1.1fr) minmax(360px, .9fr);
      gap: 14px;
      align-items: start;
    }
    .panel {
      border: 1px solid var(--border);
      border-radius: var(--radius);
      background: var(--panel);
      padding: 14px;
    }
    .stats {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
      gap: 10px;
      margin-bottom: 14px;
    }
    .stat {
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 11px;
      background: var(--panel);
      min-height: 72px;
    }
    .stat .value {
      font-size: 22px;
      font-weight: 820;
      color: var(--strong);
      overflow-wrap: anywhere;
      line-height: 1.1;
    }
    .stat .label {
      color: var(--muted);
      font-size: 12px;
      margin-top: 2px;
    }
    .row {
      display: grid;
      grid-template-columns: 1fr 120px auto;
      gap: 8px;
      align-items: end;
    }
    .row.two {
      grid-template-columns: 1fr 1fr;
    }
    .row.one {
      grid-template-columns: 1fr;
    }
    .field {
      display: flex;
      flex-direction: column;
      gap: 5px;
      min-width: 0;
    }
    label {
      color: var(--muted);
      font-size: 12px;
      font-weight: 650;
    }
    .result, .memory {
      border-top: 1px solid var(--border);
      padding: 11px 0;
    }
    .result:first-child, .memory:first-child {
      border-top: 0;
      padding-top: 0;
    }
    .meta {
      display: flex;
      gap: 7px;
      align-items: center;
      flex-wrap: wrap;
      color: var(--muted);
      font-size: 12px;
      margin-top: 7px;
    }
    .pill {
      display: inline-flex;
      align-items: center;
      min-height: 22px;
      border: 1px solid var(--border);
      border-radius: 999px;
      padding: 2px 8px;
      color: var(--muted);
      background: var(--panel-2);
      white-space: nowrap;
    }
    .score {
      color: var(--accent);
      font-weight: 750;
    }
    .memory-text {
      overflow-wrap: anywhere;
      color: var(--strong);
    }
    .toolbar {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      align-items: center;
      margin-bottom: 10px;
    }
    .toolbar > * {
      flex: 1;
      min-width: 140px;
    }
    .toolbar button {
      flex: 0 0 auto;
    }
    .heatmap {
      display: grid;
      grid-template-columns: repeat(var(--bins), 1fr);
      gap: 2px;
      aspect-ratio: 1;
      width: 100%;
      max-width: 360px;
    }
    .cell {
      border-radius: 2px;
      background: color-mix(in srgb, var(--accent) calc(var(--v) * 100%), var(--panel-2));
      min-width: 6px;
    }
    .split {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 14px;
    }
    .danger {
      color: var(--bad);
      border-color: color-mix(in srgb, var(--bad) 55%, var(--border));
    }
    .ok { color: var(--accent); }
    .warn { color: var(--warn); }
    .status {
      min-height: 22px;
      color: var(--muted);
      font-size: 12px;
      margin-top: 8px;
    }
    .empty {
      color: var(--muted);
      padding: 12px 0;
    }
    .small-actions {
      display: flex;
      gap: 6px;
      margin-top: 8px;
      flex-wrap: wrap;
    }
    .small-actions button {
      min-height: 30px;
      padding: 5px 8px;
    }
    .suggestion {
      border-top: 1px solid var(--border);
      padding: 10px 0;
    }
    .suggestion:first-child {
      border-top: 0;
      padding-top: 0;
    }
    .suggestion-title {
      color: var(--strong);
      font-weight: 780;
    }
    .suggestion.action_required .suggestion-title,
    .suggestion.architecture_required .suggestion-title {
      color: var(--warn);
    }
    .suggestion.ok .suggestion-title {
      color: var(--accent);
    }
    @media (max-width: 920px) {
      .shell { padding: 14px; }
      header { flex-direction: column; }
      .top-actions { justify-content: flex-start; }
      .grid, .split { grid-template-columns: 1fr; }
      .stats { grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); }
      .row, .row.two { grid-template-columns: 1fr; }
    }
    @media (max-width: 420px) {
      .stats { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class="shell">
    <header>
      <div>
        <h1>WaveMind Studio</h1>
        <p>Local memory map, namespace explorer, live query tester, and one-click memory operations.</p>
      </div>
      <div class="top-actions">
        <input id="apiKey" placeholder="API key if enabled" aria-label="API key if enabled">
        <button id="theme">Light</button>
        <button id="refresh" class="primary">Refresh</button>
      </div>
    </header>

    <section class="stats" id="stats"></section>

    <main class="grid">
      <section class="panel">
        <h2>Live Query Tester</h2>
        <div class="row">
          <div class="field">
            <label for="queryText">Query</label>
            <input id="queryText" value="What does Andrey do?">
          </div>
          <div class="field">
            <label for="topK">Top K</label>
            <input id="topK" type="number" min="1" max="20" value="3">
          </div>
          <button id="queryButton" class="primary">Query</button>
        </div>
        <div id="queryResults" style="margin-top:12px"></div>
      </section>

      <section class="panel">
        <h2>Remember</h2>
        <div class="field">
          <label for="rememberText">Memory text</label>
          <textarea id="rememberText" placeholder="The user prefers short practical answers."></textarea>
        </div>
        <div class="row two" style="margin-top:8px">
          <div class="field">
            <label for="rememberTags">Tags, comma-separated</label>
            <input id="rememberTags" placeholder="preference, profile">
          </div>
          <div class="field">
            <label for="rememberTtl">TTL seconds</label>
            <input id="rememberTtl" type="number" min="0" placeholder="optional">
          </div>
        </div>
        <button id="rememberButton" class="primary" style="margin-top:10px">Remember</button>
        <div class="status" id="rememberStatus"></div>
      </section>

      <section class="panel">
        <h2>Namespace Explorer</h2>
        <div class="toolbar">
          <select id="namespace"></select>
          <input id="filter" placeholder="Filter memories">
          <button id="exportJson">Export JSON</button>
        </div>
        <div id="memories"></div>
      </section>

      <section class="panel">
        <h2>Memory Field</h2>
        <div class="split">
          <div>
            <div class="heatmap" id="heatmap" style="--bins:18"></div>
            <p>Heatmap shows current field energy. Brighter cells mean hotter or recently reinforced memory regions.</p>
          </div>
          <div>
            <h2>Operations</h2>
            <div class="field">
              <label for="backupPath">Backup path</label>
              <input id="backupPath" value="./backups">
            </div>
            <button id="backupButton" style="margin-top:8px">Backup SQLite</button>
            <div class="status" id="backupStatus"></div>
            <div class="field" style="margin-top:14px">
              <label for="importPath">Import local txt/pdf/json path</label>
              <input id="importPath" placeholder="./notes.txt">
            </div>
            <button id="importButton" style="margin-top:8px">Import</button>
            <div class="status" id="importStatus"></div>
            <div id="conflicts" style="margin-top:14px"></div>
          </div>
        </div>
      </section>

      <section class="panel">
        <h2>Memory OS Insights</h2>
        <div class="toolbar">
          <select id="memoryOsDeployment">
            <option value="local">local</option>
            <option value="production">production</option>
            <option value="serverless">serverless</option>
          </select>
          <input id="memoryOsTarget" type="number" min="0" value="50000" aria-label="Target memories">
          <button id="memoryOsButton">Analyze</button>
        </div>
        <div id="memoryOsSummary" class="meta"></div>
        <div id="memoryOsSuggestions" style="margin-top:10px"></div>
      </section>
    </main>
  </div>

  <script>
    const state = { snapshot: null };
    const $ = (id) => document.getElementById(id);

    function headers() {
      const key = $("apiKey").value.trim();
      const output = { "Content-Type": "application/json" };
      if (key) output["X-API-Key"] = key;
      return output;
    }

    function namespaceValue() {
      return $("namespace").value || "default";
    }

    async function request(path, options = {}) {
      const response = await fetch(path, {
        ...options,
        headers: { ...headers(), ...(options.headers || {}) }
      });
      if (!response.ok) {
        const text = await response.text();
        throw new Error(`${response.status} ${text}`);
      }
      return response.json();
    }

    function number(value) {
      if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
      return Number(value).toLocaleString(undefined, { maximumFractionDigits: 3 });
    }

    function esc(value) {
      return String(value ?? "").replace(/[&<>"']/g, (char) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;"
      })[char]);
    }

    function renderStats(stats) {
      const rows = [
        ["Active", stats.active_memories],
        ["Expired", stats.expired_memories],
        ["Field energy", stats.field_energy],
        ["Index", stats.index],
        ["Healthy", stats.index_healthy ? "yes" : "no"]
      ];
      $("stats").innerHTML = rows.map(([label, value]) => `
        <div class="stat">
          <div class="value">${esc(value)}</div>
          <div class="label">${esc(label)}</div>
        </div>
      `).join("");
    }

    function renderNamespaces(snapshot) {
      const current = $("namespace").value;
      const options = snapshot.namespaces.length ? snapshot.namespaces : ["default"];
      $("namespace").innerHTML = options.map((ns) => `<option value="${esc(ns)}">${esc(ns)}</option>`).join("");
      if (options.includes(current)) $("namespace").value = current;
    }

    function renderMemories() {
      const snapshot = state.snapshot;
      const filter = $("filter").value.toLowerCase();
      const memories = (snapshot?.memories || []).filter((memory) => {
        const text = `${memory.text} ${memory.namespace} ${(memory.tags || []).join(" ")}`.toLowerCase();
        return !filter || text.includes(filter);
      });
      $("memories").innerHTML = memories.length ? memories.map((memory) => `
        <div class="memory">
          <div class="memory-text">${esc(memory.text)}</div>
          <div class="meta">
            <span class="pill">id ${memory.id}</span>
            <span class="pill">${esc(memory.namespace)}</span>
            <span class="pill">priority ${number(memory.priority)}</span>
            <span class="pill">access ${memory.access_count}</span>
            ${(memory.tags || []).map((tag) => `<span class="pill">#${esc(tag)}</span>`).join("")}
            ${memory.ttl_remaining_seconds !== null ? `<span class="pill warn">ttl ${number(memory.ttl_remaining_seconds)}s</span>` : ""}
          </div>
          <div class="small-actions">
            <button onclick="feedback(${memory.id}, true)">Useful</button>
            <button onclick="feedback(${memory.id}, false)">Not useful</button>
            <button class="danger" onclick="forgetMemory(${memory.id})">Forget</button>
          </div>
        </div>
      `).join("") : `<div class="empty">No memories in this namespace yet.</div>`;
    }

    function renderConflicts(snapshot) {
      const groups = snapshot.conflict_groups || [];
      $("conflicts").innerHTML = `
        <h2>Conflict Visualizer</h2>
        ${groups.length ? groups.map((group) => `
          <div class="meta" style="margin-bottom:6px">
            <span class="pill warn">${esc(group.group)}</span>
            <span class="pill">${group.memory_ids.length} memories</span>
          </div>
        `).join("") : `<p>No conflict groups found. Add metadata conflict_group to visualize corrections.</p>`}
      `;
    }

    function renderMemoryOs(data) {
      const execution = data.execution_plan || {};
      $("memoryOsSummary").innerHTML = `
        <span class="pill ${data.ok ? "ok" : "warn"}">status ${esc(data.status)}</span>
        <span class="pill">cache ${esc(data.effective_cache_mode)}</span>
        <span class="pill">hot queries ${number(data.hot_query_count)}</span>
        <span class="pill">workers ${number(execution.max_parallel_workers || 0)}</span>
        <span class="pill">${data.read_only ? "read-only" : "mutable"}</span>
      `;
      const suggestions = data.suggestions || [];
      $("memoryOsSuggestions").innerHTML = suggestions.length ? suggestions.slice(0, 8).map((item) => `
        <div class="suggestion ${esc(item.severity)}">
          <div class="suggestion-title">${esc(item.title)}</div>
          <p>${esc(item.rationale)}</p>
          <div class="meta">
            <span class="pill">${esc(item.severity)}</span>
            <span class="pill">${esc(item.id)}</span>
          </div>
          <p>${esc(item.action)}</p>
        </div>
      `).join("") : `<div class="empty">No Memory OS suggestions yet.</div>`;
    }

    async function refreshMemoryOs() {
      $("memoryOsSuggestions").innerHTML = `<div class="empty">Analyzing memory policy...</div>`;
      try {
        const ns = encodeURIComponent(namespaceValue());
        const deployment = encodeURIComponent($("memoryOsDeployment").value || "local");
        const target = Math.max(0, Number($("memoryOsTarget").value || 0));
        const data = await request(
          `/memory-os/insights?namespace=${ns}&deployment=${deployment}&target_memories=${target}&cache_mode=auto&min_frequency=2&max_hot_queries=8`
        );
        renderMemoryOs(data);
      } catch (error) {
        $("memoryOsSummary").innerHTML = "";
        $("memoryOsSuggestions").innerHTML = `<div class="empty danger">${esc(error.message)}</div>`;
      }
    }

    async function renderHeatmap() {
      const heatmap = await request(`/studio/heatmap?bins=18`);
      $("heatmap").style.setProperty("--bins", heatmap.bins);
      $("heatmap").innerHTML = heatmap.values.map((value) => (
        `<div class="cell" title="${number(value)}" style="--v:${Math.max(0, Math.min(1, value))}"></div>`
      )).join("");
    }

    async function refresh() {
      const ns = encodeURIComponent(namespaceValue());
      const snapshot = await request(`/studio/state?namespace=${ns}&limit=200`);
      state.snapshot = snapshot;
      renderStats(snapshot.stats);
      renderNamespaces(snapshot);
      renderMemories();
      renderConflicts(snapshot);
      await renderHeatmap();
      await refreshMemoryOs();
    }

    async function runQuery() {
      $("queryResults").innerHTML = `<div class="empty">Searching...</div>`;
      try {
        const payload = {
          query: $("queryText").value,
          namespace: namespaceValue(),
          top_k: Number($("topK").value || 3)
        };
        const data = await request("/query", { method: "POST", body: JSON.stringify(payload) });
        $("queryResults").innerHTML = data.results.length ? data.results.map((result) => `
          <div class="result">
            <div class="memory-text">${esc(result.text)}</div>
            <div class="meta">
              <span class="score">score ${number(result.score)}</span>
              <span class="pill">vector ${number(result.vector_score)}</span>
              <span class="pill">field ${number(result.field_score)}</span>
              <span class="pill">${esc(result.namespace)}</span>
            </div>
            <div class="small-actions">
              <button onclick="feedback(${result.id}, true)">Useful</button>
              <button onclick="feedback(${result.id}, false)">Not useful</button>
            </div>
          </div>
        `).join("") : `<div class="empty">No matching memories.</div>`;
      } catch (error) {
        $("queryResults").innerHTML = `<div class="empty danger">${esc(error.message)}</div>`;
      }
    }

    async function remember() {
      $("rememberStatus").textContent = "Saving...";
      const ttl = $("rememberTtl").value ? Number($("rememberTtl").value) : null;
      const tags = $("rememberTags").value.split(",").map((tag) => tag.trim()).filter(Boolean);
      try {
        const data = await request("/remember", {
          method: "POST",
          body: JSON.stringify({
            text: $("rememberText").value,
            namespace: namespaceValue(),
            tags,
            ttl_seconds: ttl
          })
        });
        $("rememberStatus").innerHTML = `<span class="ok">Remembered id=${data.id}</span>`;
        $("rememberText").value = "";
        await refresh();
      } catch (error) {
        $("rememberStatus").innerHTML = `<span class="danger">${esc(error.message)}</span>`;
      }
    }

    async function feedback(id, useful) {
      await request("/studio/feedback", {
        method: "POST",
        body: JSON.stringify({ id, useful })
      });
      await refresh();
    }

    async function forgetMemory(id) {
      await request(`/forget?id=${id}`, { method: "DELETE" });
      await refresh();
    }

    async function backup() {
      $("backupStatus").textContent = "Backing up...";
      try {
        const data = await request("/backup", {
          method: "POST",
          body: JSON.stringify({ path: $("backupPath").value, keep_last: 10 })
        });
        $("backupStatus").innerHTML = `<span class="ok">Backup: ${esc(data.path)}</span>`;
      } catch (error) {
        $("backupStatus").innerHTML = `<span class="danger">${esc(error.message)}</span>`;
      }
    }

    async function importPath() {
      $("importStatus").textContent = "Importing...";
      try {
        const data = await request("/import", {
          method: "POST",
          body: JSON.stringify({ path: $("importPath").value, namespace: namespaceValue() })
        });
        $("importStatus").innerHTML = `<span class="ok">Imported ${data.ids.length} chunks</span>`;
        await refresh();
      } catch (error) {
        $("importStatus").innerHTML = `<span class="danger">${esc(error.message)}</span>`;
      }
    }

    function exportJson() {
      const payload = JSON.stringify(state.snapshot || {}, null, 2);
      const url = URL.createObjectURL(new Blob([payload], { type: "application/json" }));
      const link = document.createElement("a");
      link.href = url;
      link.download = `wavemind-${namespaceValue()}.json`;
      link.click();
      URL.revokeObjectURL(url);
    }

    $("refresh").onclick = refresh;
    $("queryButton").onclick = runQuery;
    $("rememberButton").onclick = remember;
    $("backupButton").onclick = backup;
    $("importButton").onclick = importPath;
    $("exportJson").onclick = exportJson;
    $("memoryOsButton").onclick = refreshMemoryOs;
    $("namespace").onchange = refresh;
    $("filter").oninput = renderMemories;
    $("apiKey").onchange = () => localStorage.setItem("wavemindApiKey", $("apiKey").value);
    $("theme").onclick = () => {
      const next = document.documentElement.dataset.theme === "light" ? "dark" : "light";
      document.documentElement.dataset.theme = next;
      $("theme").textContent = next === "light" ? "Dark" : "Light";
      localStorage.setItem("wavemindTheme", next);
    };
    $("apiKey").value = localStorage.getItem("wavemindApiKey") || "";
    document.documentElement.dataset.theme = localStorage.getItem("wavemindTheme") || "dark";
    $("theme").textContent = document.documentElement.dataset.theme === "light" ? "Dark" : "Light";
    refresh().catch((error) => {
      $("stats").innerHTML = `<div class="stat"><div class="value">Error</div><div class="label">${esc(error.message)}</div></div>`;
    });
  </script>
</body>
</html>
"""


def memory_to_dict(record: Any) -> dict[str, Any]:
    now = time.time()
    ttl_remaining = None
    if record.expires_at is not None:
        ttl_remaining = max(0.0, float(record.expires_at) - now)
    return {
        "id": int(record.id) if record.id is not None else None,
        "text": record.text,
        "namespace": record.namespace,
        "tags": list(record.tags),
        "metadata": record.metadata,
        "created_at": float(record.created_at),
        "updated_at": float(record.updated_at),
        "expires_at": record.expires_at,
        "ttl_remaining_seconds": ttl_remaining,
        "expired": bool(record.is_expired),
        "priority": float(record.priority),
        "access_count": int(record.access_count),
    }


def studio_snapshot(
    mind: Any,
    namespace: str | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    records = mind.store.list(include_expired=True)
    namespaces = sorted({record.namespace for record in records})
    if namespace in namespaces or not namespaces:
        selected_namespace = namespace or "default"
    else:
        selected_namespace = namespaces[0]
    selected = [
        record
        for record in records
        if record.namespace == selected_namespace
    ]
    selected.sort(key=lambda record: (record.priority, record.updated_at), reverse=True)
    selected = selected[: max(0, int(limit))]
    return {
        "version": getattr(mind, "__version__", None),
        "selected_namespace": selected_namespace,
        "namespaces": namespaces,
        "stats": mind.stats(namespace=selected_namespace),
        "memories": [memory_to_dict(record) for record in selected],
        "conflict_groups": conflict_groups(selected),
    }


def conflict_groups(records: list[Any]) -> list[dict[str, Any]]:
    groups: dict[str, list[int]] = {}
    for record in records:
        group = record.metadata.get("conflict_group") if isinstance(record.metadata, dict) else None
        if group and record.id is not None:
            groups.setdefault(str(group), []).append(int(record.id))
    return [
        {"group": group, "memory_ids": ids}
        for group, ids in sorted(groups.items())
        if len(ids) > 1
    ]


def field_heatmap(mind: Any, bins: int = 18) -> dict[str, Any]:
    bins = max(4, min(48, int(bins)))
    magnitude = np.sum(np.abs(mind.field.state), axis=2)
    if not np.any(magnitude):
        return {"bins": bins, "values": [0.0 for _ in range(bins * bins)]}

    height, width = magnitude.shape
    y_edges = np.linspace(0, height, bins + 1, dtype=int)
    x_edges = np.linspace(0, width, bins + 1, dtype=int)
    values: list[float] = []
    for y in range(bins):
        for x in range(bins):
            block = magnitude[y_edges[y]: y_edges[y + 1], x_edges[x]: x_edges[x + 1]]
            values.append(float(block.mean()) if block.size else 0.0)
    max_value = max(values) or 1.0
    normalized = [round(math.sqrt(value / max_value), 4) for value in values]
    return {"bins": bins, "values": normalized}
