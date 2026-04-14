import argparse
import csv
import json
import os
import re
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import unquote, urlparse


ACTION_PROFILE = {
    "inbound": {"label": "入库", "delta": 1},
    "outbound": {"label": "出库", "delta": -1},
    "unknown": {"label": "未知", "delta": 0},
}

INBOUND_ALIASES = {"inbound", "in", "入库", "入"}
OUTBOUND_ALIASES = {"outbound", "out", "出库", "出"}

NAME_PATTERN = re.compile(r"(?:Name|名称)\s*[:：]\s*([^,，]+)")
ID_PATTERN = re.compile(r"ID\s*[:：]\s*([A-Za-z0-9_-]+)")


HTML_PAGE = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>物资出入库看板</title>
  <style>
    :root {
      --bg-a: #f7fbff;
      --bg-b: #eef6ef;
      --surface: #ffffffdd;
      --line: #d7e4ea;
      --text: #1d2d35;
      --muted: #5f7682;
      --accent: #0f766e;
      --accent-alt: #ea580c;
      --ok-bg: #e6f6ec;
      --ok-text: #14532d;
      --warn-bg: #fff4e5;
      --warn-text: #9a3412;
    }

    * {
      box-sizing: border-box;
    }

    body {
      margin: 0;
      color: var(--text);
      font-family: "Noto Sans SC", "PingFang SC", "Microsoft YaHei", sans-serif;
      background:
        radial-gradient(1200px 360px at 12% -10%, #d5ebff 0%, transparent 55%),
        radial-gradient(1000px 320px at 85% -20%, #d6f6dd 0%, transparent 60%),
        linear-gradient(165deg, var(--bg-a) 0%, var(--bg-b) 100%);
      min-height: 100vh;
      padding: 20px;
      animation: page-enter .45s ease-out;
    }

    @keyframes page-enter {
      from {
        opacity: 0;
        transform: translateY(6px);
      }
      to {
        opacity: 1;
        transform: translateY(0);
      }
    }

    .container {
      max-width: 1200px;
      margin: 0 auto;
      display: grid;
      gap: 16px;
    }

    .panel {
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 16px;
      backdrop-filter: blur(8px);
      box-shadow: 0 8px 26px rgba(27, 74, 89, 0.08);
    }

    .header {
      padding: 18px 20px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 14px;
      flex-wrap: wrap;
    }

    .title-wrap h1 {
      margin: 0;
      font-size: 25px;
      letter-spacing: 0.5px;
      font-family: "STKaiti", "KaiTi", serif;
    }

    .title-wrap p {
      margin: 6px 0 0;
      color: var(--muted);
      font-size: 14px;
    }

    .toolbar {
      display: flex;
      gap: 8px;
      align-items: center;
      flex-wrap: wrap;
    }

    .input,
    .select,
    .btn {
      height: 38px;
      border-radius: 10px;
      border: 1px solid var(--line);
      background: #fff;
      color: var(--text);
      font-size: 14px;
      padding: 0 12px;
    }

    .input {
      min-width: 220px;
    }

    .btn {
      cursor: pointer;
      background: linear-gradient(180deg, #ffffff 0%, #f4faf8 100%);
      transition: transform .14s ease, border-color .2s ease;
    }

    .btn:hover {
      transform: translateY(-1px);
      border-color: #bdd7d4;
    }

    .stats {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
      padding: 0 20px 20px;
    }

    .stat {
      border: 1px solid var(--line);
      border-radius: 12px;
      background: linear-gradient(180deg, #ffffff 0%, #f9fbfc 100%);
      padding: 14px;
      min-height: 86px;
      display: grid;
      align-content: center;
      gap: 4px;
      animation: card-in .4s ease both;
    }

    @keyframes card-in {
      from {
        opacity: 0;
        transform: translateY(8px);
      }
      to {
        opacity: 1;
        transform: translateY(0);
      }
    }

    .stat .name {
      font-size: 13px;
      color: var(--muted);
    }

    .stat .value {
      font-size: 24px;
      font-weight: 700;
      color: #0b5560;
    }

    .content-grid {
      display: grid;
      grid-template-columns: 2.2fr 1fr;
      gap: 16px;
    }

    .table-wrap {
      padding: 14px;
      overflow-x: auto;
    }

    table {
      width: 100%;
      border-collapse: collapse;
      min-width: 780px;
    }

    th,
    td {
      text-align: left;
      padding: 12px 10px;
      border-bottom: 1px solid #e7eef2;
      font-size: 14px;
      vertical-align: middle;
    }

    th {
      font-weight: 700;
      color: #35505c;
      background: #f8fbfd;
      position: sticky;
      top: 0;
      z-index: 1;
    }

    tbody tr {
      animation: row-in .25s ease both;
    }

    @keyframes row-in {
      from {
        opacity: 0;
        transform: translateY(6px);
      }
      to {
        opacity: 1;
        transform: translateY(0);
      }
    }

    .badge {
      display: inline-block;
      border-radius: 999px;
      font-size: 12px;
      padding: 4px 8px;
      font-weight: 700;
    }

    .badge.ok {
      background: var(--ok-bg);
      color: var(--ok-text);
    }

    .badge.warn {
      background: var(--warn-bg);
      color: var(--warn-text);
    }

    .badge.partial {
      background: #e7efff;
      color: #1e3a8a;
    }

    .link-btn {
      border: none;
      background: transparent;
      color: var(--accent);
      cursor: pointer;
      padding: 0;
      font-size: 14px;
      text-decoration: underline;
      text-decoration-style: dotted;
    }

    .side {
      padding: 14px 16px;
      display: grid;
      gap: 12px;
      align-content: start;
    }

    .side h3 {
      margin: 4px 0;
      font-size: 17px;
    }

    .event-list {
      margin: 0;
      padding-left: 18px;
      max-height: 500px;
      overflow: auto;
    }

    .event-list li {
      margin: 8px 0;
      color: #365160;
      line-height: 1.42;
      font-size: 13px;
    }

    .event-title {
      font-weight: 700;
      color: #1f3943;
    }

    .empty {
      color: var(--muted);
      text-align: center;
      padding: 26px 8px;
      font-size: 14px;
    }

    #detail-panel {
      position: fixed;
      top: 0;
      right: -480px;
      width: min(460px, 96vw);
      height: 100vh;
      z-index: 20;
      background: #fff;
      border-left: 1px solid var(--line);
      box-shadow: -12px 0 36px rgba(23, 62, 76, 0.15);
      transition: right .32s ease;
      display: flex;
      flex-direction: column;
    }

    #detail-panel.open {
      right: 0;
    }

    .detail-head {
      padding: 16px;
      border-bottom: 1px solid var(--line);
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 8px;
    }

    .detail-body {
      padding: 14px 16px 20px;
      overflow: auto;
    }

    .timeline {
      list-style: none;
      margin: 0;
      padding: 0;
      display: grid;
      gap: 10px;
    }

    .timeline-item {
      border: 1px solid #e3ebef;
      border-radius: 10px;
      padding: 10px;
      background: #fcfeff;
    }

    .timeline-main {
      display: flex;
      justify-content: space-between;
      gap: 8px;
      align-items: center;
      flex-wrap: wrap;
      margin-bottom: 6px;
    }

    .timeline-meta,
    .timeline-note {
      color: #456371;
      font-size: 12px;
      line-height: 1.42;
    }

    .muted {
      color: var(--muted);
      font-size: 12px;
    }

    .detail-section-title {
      margin: 8px 0;
      font-size: 12px;
      color: #5e7783;
      font-weight: 700;
      letter-spacing: .3px;
    }

    @media (max-width: 980px) {
      .stats {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }

      .content-grid {
        grid-template-columns: 1fr;
      }

      .input {
        min-width: 160px;
      }
    }

    @media (max-width: 640px) {
      body {
        padding: 12px;
      }

      .header {
        padding: 14px;
      }

      .stats {
        padding: 0 14px 14px;
      }

      .title-wrap h1 {
        font-size: 22px;
      }
    }
  </style>
</head>
<body>
  <div class="container">
    <section class="panel">
      <div class="header">
        <div class="title-wrap">
          <h1>物资出入库链路看板</h1>
          <p>实时读取 `material_log.csv`，按物资类型聚合个体 ID，支持状态总览与全链路追溯</p>
        </div>
        <div class="toolbar">
          <input id="keyword" class="input" type="text" placeholder="搜索物资类型 / 个体ID / 操作人" />
          <select id="stock-filter" class="select">
            <option value="all">全部状态</option>
            <option value="in">仅在库</option>
            <option value="out">仅已出库</option>
          </select>
          <button id="reload-btn" class="btn" type="button">刷新数据</button>
        </div>
      </div>

      <div class="stats">
        <div class="stat">
          <div class="name">物资类型</div>
          <div class="value" id="stat-types">0</div>
        </div>
        <div class="stat">
          <div class="name">在库个体</div>
          <div class="value" id="stat-in">0</div>
        </div>
        <div class="stat">
          <div class="name">已出库个体</div>
          <div class="value" id="stat-out">0</div>
        </div>
        <div class="stat">
          <div class="name">累计操作记录</div>
          <div class="value" id="stat-records">0</div>
        </div>
      </div>
    </section>

    <div class="content-grid">
      <section class="panel table-wrap">
        <table id="material-table">
          <thead>
            <tr>
              <th>物资类型</th>
              <th>在库状态</th>
              <th>在库/总个体</th>
              <th>在库ID</th>
              <th>已出库ID</th>
              <th>最近操作</th>
              <th>最近操作人</th>
              <th>最近时间</th>
              <th>详情</th>
            </tr>
          </thead>
          <tbody></tbody>
        </table>
      </section>

      <aside class="panel side">
        <h3>最近操作流水</h3>
        <div class="muted" id="updated-at">尚未加载</div>
        <ol class="event-list" id="event-list"></ol>
      </aside>
    </div>
  </div>

  <section id="detail-panel" aria-live="polite" aria-label="物资链路详情">
    <div class="detail-head">
      <div>
        <strong id="detail-title">物资链路</strong>
        <div class="muted" id="detail-subtitle"></div>
      </div>
      <button class="btn" id="close-detail" type="button">关闭</button>
    </div>
    <div class="detail-body">
      <div class="detail-section-title">个体状态</div>
      <ul class="timeline" id="instance-list"></ul>
      <div class="detail-section-title">操作链路</div>
      <ul class="timeline" id="timeline"></ul>
    </div>
  </section>

  <script>
    const state = {
      materials: [],
      recentEvents: [],
      keyword: "",
      stockFilter: "all"
    };

    const esc = (value) => {
      const text = String(value ?? "");
      return text
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
    };

    const formatDelta = (value) => {
      if (value > 0) return `+${value}`;
      return `${value}`;
    };

    async function fetchSummary() {
      const res = await fetch("/api/summary", { cache: "no-store" });
      if (!res.ok) {
        throw new Error(`加载失败: ${res.status}`);
      }
      return res.json();
    }

    function renderStats(payload) {
      document.getElementById("stat-types").textContent = payload.stats.material_types;
      document.getElementById("stat-in").textContent = payload.stats.in_stock_instances;
      document.getElementById("stat-out").textContent = payload.stats.out_stock_instances;
      document.getElementById("stat-records").textContent = payload.stats.total_records;
      document.getElementById("updated-at").textContent = `数据更新时间: ${payload.generated_at}`;
    }

    function filteredMaterials() {
      const kw = state.keyword.trim().toLowerCase();
      return state.materials.filter((item) => {
        const hasInStock = item.in_count > 0;
        const hasOutStock = item.out_count > 0;
        const stockPass = state.stockFilter === "all"
          || (state.stockFilter === "in" && hasInStock)
          || (state.stockFilter === "out" && hasOutStock);

        if (!stockPass) {
          return false;
        }

        if (!kw) {
          return true;
        }

        const idText = `${item.in_instance_ids.join(" ")} ${item.out_instance_ids.join(" ")}`;
        const haystack = `${item.material_name} ${idText} ${item.last_person}`.toLowerCase();
        return haystack.includes(kw);
      });
    }

    function renderTable() {
      const tbody = document.querySelector("#material-table tbody");
      const rows = filteredMaterials();

      if (!rows.length) {
        tbody.innerHTML = `<tr><td colspan="9" class="empty">没有匹配的数据</td></tr>`;
        return;
      }

      tbody.innerHTML = rows.map((item) => {
        const badgeClass = item.stock_state === "all_in"
          ? "ok"
          : (item.stock_state === "all_out" ? "warn" : "partial");
        const badgeLabel = item.stock_text;
        const inIds = item.in_instance_ids.length ? item.in_instance_ids.join(", ") : "-";
        const outIds = item.out_instance_ids.length ? item.out_instance_ids.join(", ") : "-";
        const encodedKey = encodeURIComponent(item.material_key);

        return `
          <tr>
            <td>${esc(item.material_name)}</td>
            <td><span class="badge ${badgeClass}">${badgeLabel}</span></td>
            <td>${esc(item.in_count)} / ${esc(item.instance_total)}</td>
            <td>${esc(inIds)}</td>
            <td>${esc(outIds)}</td>
            <td>${esc(item.last_action)}</td>
            <td>${esc(item.last_person)}</td>
            <td>${esc(item.last_timestamp)}</td>
            <td><button type="button" class="link-btn" onclick="openDetail('${encodedKey}')">查看链路</button></td>
          </tr>
        `;
      }).join("");
    }

    function renderRecentEvents() {
      const list = document.getElementById("event-list");
      if (!state.recentEvents.length) {
        list.innerHTML = `<li class="empty">暂无记录</li>`;
        return;
      }

      list.innerHTML = state.recentEvents.map((event) => {
        return `
          <li>
            <div class="event-title">${esc(event.timestamp)} · ${esc(event.action)} · ${esc(event.person)}</div>
            <div>${esc(event.material_preview)}</div>
          </li>
        `;
      }).join("");
    }

    async function loadData() {
      try {
        const payload = await fetchSummary();
        state.materials = payload.materials;
        state.recentEvents = payload.recent_events;
        renderStats(payload);
        renderTable();
        renderRecentEvents();
      } catch (err) {
        const tbody = document.querySelector("#material-table tbody");
        tbody.innerHTML = `<tr><td colspan="9" class="empty">${esc(err.message)}</td></tr>`;
      }
    }

    async function openDetail(materialKey) {
      const panel = document.getElementById("detail-panel");
      const instanceList = document.getElementById("instance-list");
      const timeline = document.getElementById("timeline");
      instanceList.innerHTML = `<li class="empty">正在加载个体状态...</li>`;
      timeline.innerHTML = `<li class="empty">正在加载链路...</li>`;
      panel.classList.add("open");

      try {
        const res = await fetch(`/api/material/${materialKey}`, { cache: "no-store" });
        if (!res.ok) {
          throw new Error(`无法加载链路详情: ${res.status}`);
        }
        const payload = await res.json();
        const summary = payload.summary;

        document.getElementById("detail-title").textContent = `${summary.material_name}`;
        document.getElementById("detail-subtitle").textContent = `在库个体: ${summary.in_count} | 已出库个体: ${summary.out_count} | 最近操作人: ${summary.last_person}`;

        if (!summary.instances.length) {
          instanceList.innerHTML = `<li class="empty">暂无个体数据</li>`;
        } else {
          instanceList.innerHTML = summary.instances.map((entry) => {
            const entryClass = entry.in_stock ? "ok" : "warn";
            const entryLabel = entry.in_stock ? "在库" : "已出库";
            return `
              <li class="timeline-item">
                <div class="timeline-main">
                  <span class="badge ${entryClass}">ID ${esc(entry.instance_id)} · ${entryLabel}</span>
                  <span class="muted">净库存: ${esc(entry.balance)}</span>
                </div>
                <div class="timeline-meta">最近操作: ${esc(entry.last_action)} · ${esc(entry.last_person)}</div>
                <div class="timeline-note">最近时间: ${esc(entry.last_timestamp)}</div>
              </li>
            `;
          }).join("");
        }

        if (!payload.chain.length) {
          timeline.innerHTML = `<li class="empty">暂无可展示链路</li>`;
          return;
        }

        timeline.innerHTML = payload.chain.map((step) => {
          const actionClass = step.delta >= 0 ? "ok" : "warn";
          const actionLabel = `${step.action} · ID ${step.instance_id} (${formatDelta(step.delta)})`;
          return `
            <li class="timeline-item">
              <div class="timeline-main">
                <span class="badge ${actionClass}">${esc(actionLabel)}</span>
                <span class="muted">记录 #${esc(step.record_id)} · ${esc(step.timestamp)}</span>
              </div>
              <div class="timeline-meta">操作人: ${esc(step.person)} | 该个体操作后净库存: ${esc(step.instance_balance_after)}</div>
              <div class="timeline-note">原始记录: ${esc(step.raw_material)}</div>
            </li>
          `;
        }).join("");
      } catch (err) {
        instanceList.innerHTML = `<li class="empty">${esc(err.message)}</li>`;
        timeline.innerHTML = `<li class="empty">${esc(err.message)}</li>`;
      }
    }

    function closeDetail() {
      document.getElementById("instance-list").innerHTML = "";
      document.getElementById("timeline").innerHTML = "";
      document.getElementById("detail-panel").classList.remove("open");
    }

    document.getElementById("keyword").addEventListener("input", (event) => {
      state.keyword = event.target.value;
      renderTable();
    });

    document.getElementById("stock-filter").addEventListener("change", (event) => {
      state.stockFilter = event.target.value;
      renderTable();
    });

    document.getElementById("reload-btn").addEventListener("click", loadData);
    document.getElementById("close-detail").addEventListener("click", closeDetail);
    window.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        closeDetail();
      }
    });

    loadData();
    setInterval(loadData, 30000);
  </script>
</body>
</html>
"""


def normalize_action(raw_action: str) -> str:
    value = (raw_action or "").strip()
    lowered = value.lower()

    if lowered in INBOUND_ALIASES or "入" in value:
        return "inbound"
    if lowered in OUTBOUND_ALIASES or "出" in value:
        return "outbound"
    return "unknown"


def parse_timestamp(value: str) -> datetime | None:
    raw = (value or "").strip()
    if not raw:
        return None

    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
    ]

    for item in formats:
        try:
            return datetime.strptime(raw, item)
        except ValueError:
            continue

    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def parse_material_fragment(fragment: str) -> dict[str, str] | None:
    content = (fragment or "").strip()
    if not content:
        return None

    name_match = NAME_PATTERN.search(content)
    id_match = ID_PATTERN.search(content)

    material_name = name_match.group(1).strip() if name_match else ""
    material_id = id_match.group(1).strip() if id_match else ""

    if not material_name and not material_id:
        material_name = content
        material_id = content
    elif material_name and not material_id:
        material_id = material_name.replace(" ", "_")
    elif material_id and not material_name:
        material_name = material_id

    return {
        "id": material_id,
        "name": material_name,
        "raw": content,
    }


def parse_material_list(raw_material_info: str) -> list[dict[str, str]]:
    content = (raw_material_info or "").strip()
    if not content:
        return []

    parsed_items = []
    for fragment in content.split("|"):
        parsed = parse_material_fragment(fragment)
        if parsed:
            parsed_items.append(parsed)

    if parsed_items:
        return parsed_items

    fallback = parse_material_fragment(content)
    return [fallback] if fallback else []


def load_events(log_file: str) -> list[dict[str, Any]]:
    if not os.path.isfile(log_file):
        return []

    events = []
    with open(log_file, mode="r", encoding="utf-8", newline="") as csvfile:
        reader = csv.DictReader(csvfile)
        for record_id, row in enumerate(reader, start=1):
            timestamp = (row.get("Timestamp") or "").strip()
            person = (row.get("Person") or "未知").strip() or "未知"
            raw_action = (row.get("Action") or "").strip()
            action_code = normalize_action(raw_action)
            action_label = ACTION_PROFILE[action_code]["label"]
            material_info = (row.get("Material Info") or "").strip()

            events.append(
                {
                    "record_id": record_id,
                    "timestamp": timestamp,
                    "parsed_timestamp": parse_timestamp(timestamp),
                    "person": person,
                    "raw_action": raw_action,
                    "action_code": action_code,
                    "action_label": action_label,
                    "material_info": material_info,
                    "materials": parse_material_list(material_info),
                }
            )

    return sorted(
        events,
        key=lambda event: (
            event["parsed_timestamp"] is None,
            event["parsed_timestamp"] or datetime.min,
            event["record_id"],
        ),
    )


def natural_sort_key(value: str) -> tuple[Any, ...]:
    chunks = re.findall(r"\d+|\D+", str(value))
    key: list[tuple[int, Any]] = []
    for chunk in chunks:
        if chunk.isdigit():
            key.append((0, int(chunk)))
        else:
            key.append((1, chunk.lower()))
    return tuple(key)


def build_material_key(material_name: str, material_id: str) -> str:
    normalized_name = (material_name or "").strip().lower()
    if normalized_name:
        return normalized_name

    fallback_id = (material_id or "").strip().lower()
    if fallback_id:
        return f"id::{fallback_id}"
    return "unknown"


def build_dashboard_data(log_file: str) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    events = load_events(log_file)

    materials_map: dict[str, dict[str, Any]] = {}
    details_map: dict[str, dict[str, Any]] = {}

    for event in events:
        delta = ACTION_PROFILE[event["action_code"]]["delta"]
        for material in event["materials"]:
            instance_id = (material["id"] or "UNKNOWN").strip() or "UNKNOWN"
            material_name = (material["name"] or "").strip()
            if not material_name:
                material_name = f"未命名类型({instance_id})"

            material_key = build_material_key(material_name, instance_id)

            if material_key not in materials_map:
                materials_map[material_key] = {
                    "material_key": material_key,
                    "material_name": material_name,
                    "instances": {},
                    "last_action": "-",
                    "last_person": "-",
                    "last_timestamp": "-",
                }
                details_map[material_key] = {"chain": [], "instances": []}

            material_state = materials_map[material_key]
            if material_name and not material_state["material_name"].startswith("未命名类型"):
                material_state["material_name"] = material_name

            instance_map = material_state["instances"]
            if instance_id not in instance_map:
                instance_map[instance_id] = {
                    "instance_id": instance_id,
                    "balance": 0,
                    "last_action": "-",
                    "last_person": "-",
                    "last_timestamp": "-",
                }

            instance_state = instance_map[instance_id]
            new_balance = instance_state["balance"] + delta
            instance_state["balance"] = new_balance
            instance_state["last_action"] = event["action_label"]
            instance_state["last_person"] = event["person"]
            instance_state["last_timestamp"] = event["timestamp"] or "-"

            material_state["last_action"] = event["action_label"]
            material_state["last_person"] = event["person"]
            material_state["last_timestamp"] = event["timestamp"] or "-"

            details_map[material_key]["chain"].append(
                {
                    "record_id": event["record_id"],
                    "timestamp": event["timestamp"] or "-",
                    "person": event["person"],
                    "action": event["action_label"],
                    "delta": delta,
                    "instance_id": instance_id,
                    "instance_balance_after": new_balance,
                    "raw_material": material["raw"],
                }
            )

    materials: list[dict[str, Any]] = []
    in_stock_instances = 0
    out_stock_instances = 0
    in_stock_types = 0
    out_stock_types = 0
    partial_stock_types = 0

    for material_key, material_state in materials_map.items():
        instances = list(material_state["instances"].values())
        instances.sort(key=lambda item: natural_sort_key(item["instance_id"]))

        in_ids = [item["instance_id"] for item in instances if item["balance"] > 0]
        out_ids = [item["instance_id"] for item in instances if item["balance"] <= 0]

        for item in instances:
            item["in_stock"] = item["balance"] > 0

        instance_total = len(instances)
        in_count = len(in_ids)
        out_count = len(out_ids)

        in_stock_instances += in_count
        out_stock_instances += out_count

        if in_count == instance_total and instance_total > 0:
            stock_state = "all_in"
            stock_text = "全部在库"
            in_stock_types += 1
        elif in_count == 0:
            stock_state = "all_out"
            stock_text = "全部已出库"
            out_stock_types += 1
        else:
            stock_state = "partial"
            stock_text = "部分在库"
            partial_stock_types += 1

        summary = {
            "material_key": material_key,
            "material_name": material_state["material_name"],
            "stock_state": stock_state,
            "stock_text": stock_text,
            "instance_total": instance_total,
            "in_count": in_count,
            "out_count": out_count,
            "in_instance_ids": in_ids,
            "out_instance_ids": out_ids,
            "last_action": material_state["last_action"],
            "last_person": material_state["last_person"],
            "last_timestamp": material_state["last_timestamp"],
            "chain_count": len(details_map[material_key]["chain"]),
        }
        materials.append(summary)
        details_map[material_key]["instances"] = instances

    materials.sort(
        key=lambda item: (
            0 if item["stock_state"] != "all_out" else 1,
            natural_sort_key(item["material_name"]),
        )
    )

    recent_events = []
    for event in sorted(
        events,
        key=lambda item: (
            item["parsed_timestamp"] is None,
            item["parsed_timestamp"] or datetime.min,
            item["record_id"],
        ),
        reverse=True,
    )[:10]:
        labels = []
        for entry in event["materials"]:
            entry_name = entry["name"] or "未命名"
            entry_id = entry["id"] or "?"
            labels.append(f"{entry_name}(ID:{entry_id})")

        preview = "、".join(labels[:3])
        if len(labels) > 3:
            preview = f"{preview} 等{len(labels)}项"

        recent_events.append(
            {
                "record_id": event["record_id"],
                "timestamp": event["timestamp"] or "-",
                "person": event["person"],
                "action": event["action_label"],
                "material_preview": preview or "无物资信息",
            }
        )

    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "stats": {
            "material_types": len(materials),
            "total_instances": in_stock_instances + out_stock_instances,
            "in_stock_instances": in_stock_instances,
            "out_stock_instances": out_stock_instances,
            "in_stock_types": in_stock_types,
            "out_stock_types": out_stock_types,
            "partial_stock_types": partial_stock_types,
            "total_records": len(events),
        },
        "materials": materials,
        "recent_events": recent_events,
    }

    return payload, details_map


def ensure_log_file_exists(log_file: str) -> None:
    if os.path.isfile(log_file):
        return

    base_dir = os.path.dirname(log_file)
    if base_dir:
        os.makedirs(base_dir, exist_ok=True)

    with open(log_file, mode="w", encoding="utf-8", newline="") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["Timestamp", "Person", "Action", "Material Info"])


class DashboardHandler(BaseHTTPRequestHandler):
    log_file = "material_log.csv"

    def _send_json(self, payload: dict[str, Any], status_code: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html_text: str) -> None:
        body = html_text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_not_found(self, message: str = "Not Found") -> None:
        self._send_json({"error": message}, status_code=404)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path

        if path in {"/", "/index.html"}:
            self._send_html(HTML_PAGE)
            return

        payload, details_map = build_dashboard_data(self.log_file)

        if path == "/api/summary":
            self._send_json(payload)
            return

        if path.startswith("/api/material/"):
            material_key = unquote(path.replace("/api/material/", "", 1)).strip()
            if not material_key:
                self._send_not_found("material key is required")
                return

            summary = next(
                (item for item in payload["materials"] if item["material_key"] == material_key),
                None,
            )
            if not summary:
                self._send_not_found(f"material '{material_key}' not found")
                return

            detail = details_map.get(material_key, {"instances": [], "chain": []})
            detail_summary = {
                **summary,
                "instances": detail.get("instances", []),
            }
            self._send_json({"summary": detail_summary, "chain": detail.get("chain", [])})
            return

        self._send_not_found()

    def log_message(self, format: str, *args: Any) -> None:
        return


def run_server(host: str, port: int, log_file: str) -> None:
    ensure_log_file_exists(log_file)
    DashboardHandler.log_file = log_file
    server = ThreadingHTTPServer((host, port), DashboardHandler)
    print(f"Dashboard ready at http://{host}:{port}")
    print(f"Using log file: {log_file}")
    print("Press Ctrl+C to stop.")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        server.server_close()


def main() -> None:
    default_log_file = os.path.join(os.path.dirname(__file__), "material_log.csv")

    parser = argparse.ArgumentParser(description="Material log web dashboard")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8080, help="Port to bind (default: 8080)")
    parser.add_argument(
        "--log-file",
        default=default_log_file,
        help=f"Path to material log csv (default: {default_log_file})",
    )

    args = parser.parse_args()
    run_server(host=args.host, port=args.port, log_file=args.log_file)


if __name__ == "__main__":
    main()
