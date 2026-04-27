from __future__ import annotations

import html


HTML_PAGE = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>__BOARD_TITLE__</title>
  <style>
    :root {
      --bg-top: #f5f0e8;
      --bg-bottom: #edf7f5;
      --surface: rgba(255, 255, 255, 0.82);
      --surface-strong: rgba(255, 255, 255, 0.94);
      --line: rgba(39, 83, 77, 0.12);
      --text: #1f2b2a;
      --muted: #5d7371;
      --accent: #0f766e;
      --accent-deep: #115e59;
      --warm: #c96d32;
      --shadow: 0 18px 48px rgba(38, 68, 63, 0.12);
      --good-bg: #e7f6ef;
      --good-text: #14532d;
      --steady-bg: #edf5ff;
      --steady-text: #1d4ed8;
      --low-bg: #fff5e8;
      --low-text: #b45309;
      --empty-bg: #fdecec;
      --empty-text: #b91c1c;
    }

    * {
      box-sizing: border-box;
    }

    body {
      margin: 0;
      min-height: 100vh;
      color: var(--text);
      font-family: "Source Han Sans SC", "PingFang SC", "Microsoft YaHei", sans-serif;
      background:
        radial-gradient(900px 360px at 8% -4%, rgba(242, 205, 147, 0.42), transparent 60%),
        radial-gradient(860px 300px at 96% 0%, rgba(150, 214, 203, 0.38), transparent 55%),
        linear-gradient(160deg, var(--bg-top) 0%, var(--bg-bottom) 100%);
      padding: 24px;
    }

    .shell {
      max-width: 1380px;
      margin: 0 auto;
      display: grid;
      gap: 18px;
    }

    .panel {
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 24px;
      box-shadow: var(--shadow);
      backdrop-filter: blur(12px);
    }

    .hero {
      padding: 26px 28px 22px;
      display: grid;
      gap: 18px;
    }

    .hero-top {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 18px;
      flex-wrap: wrap;
    }

    .hero h1 {
      margin: 0;
      font-size: clamp(30px, 4vw, 44px);
      font-family: "STKaiti", "KaiTi", serif;
      font-weight: 700;
      letter-spacing: 0.6px;
    }

    .hero p {
      margin: 8px 0 0;
      color: var(--muted);
      font-size: 15px;
      line-height: 1.7;
      max-width: 760px;
    }

    .hero-meta {
      display: grid;
      gap: 10px;
      min-width: 280px;
    }

    .status-chip {
      display: inline-flex;
      align-items: center;
      gap: 10px;
      width: fit-content;
      padding: 10px 14px;
      border-radius: 999px;
      background: rgba(255, 255, 255, 0.78);
      border: 1px solid rgba(15, 118, 110, 0.12);
      color: var(--accent-deep);
      font-size: 14px;
      font-weight: 600;
    }

    .status-dot {
      width: 10px;
      height: 10px;
      border-radius: 50%;
      background: #94a3b8;
      box-shadow: 0 0 0 6px rgba(148, 163, 184, 0.14);
      transition: background .24s ease, box-shadow .24s ease;
    }

    .status-chip.live .status-dot {
      background: #16a34a;
      box-shadow: 0 0 0 6px rgba(22, 163, 74, 0.14);
    }

    .status-chip.lag .status-dot {
      background: #f59e0b;
      box-shadow: 0 0 0 6px rgba(245, 158, 11, 0.14);
    }

    .hero-note {
      font-size: 13px;
      color: var(--muted);
      line-height: 1.6;
      text-align: right;
    }

    .stats {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 14px;
    }

    .stat-card {
      padding: 18px;
      border-radius: 18px;
      background: linear-gradient(180deg, rgba(255, 255, 255, 0.86) 0%, rgba(248, 251, 250, 0.96) 100%);
      border: 1px solid rgba(39, 83, 77, 0.1);
      display: grid;
      gap: 8px;
      min-height: 112px;
      animation: fade-up .38s ease both;
    }

    .stat-name {
      font-size: 13px;
      color: var(--muted);
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }

    .stat-value {
      font-size: 31px;
      line-height: 1;
      font-weight: 700;
      color: var(--accent-deep);
    }

    .stat-desc {
      font-size: 13px;
      color: var(--muted);
    }

    .content {
      display: grid;
      grid-template-columns: minmax(0, 2fr) minmax(280px, 0.92fr);
      gap: 18px;
    }

    .section-head {
      padding: 20px 22px 0;
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      flex-wrap: wrap;
    }

    .section-head h2 {
      margin: 0;
      font-size: 20px;
      font-weight: 700;
    }

    .section-head p {
      margin: 6px 0 0;
      color: var(--muted);
      font-size: 14px;
    }

    .toolbar {
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
    }

    .input,
    .btn {
      height: 42px;
      border-radius: 14px;
      border: 1px solid rgba(39, 83, 77, 0.12);
      background: rgba(255, 255, 255, 0.92);
      color: var(--text);
      padding: 0 14px;
      font-size: 14px;
    }

    .input {
      min-width: 240px;
    }

    .btn {
      cursor: pointer;
      font-weight: 600;
      background: linear-gradient(180deg, rgba(255, 255, 255, 0.94) 0%, rgba(240, 248, 245, 0.96) 100%);
      transition: transform .16s ease, border-color .2s ease, box-shadow .2s ease;
    }

    .btn:hover {
      transform: translateY(-1px);
      border-color: rgba(15, 118, 110, 0.28);
      box-shadow: 0 10px 22px rgba(15, 118, 110, 0.1);
    }

    .table-wrap {
      padding: 18px 20px 20px;
      overflow-x: auto;
    }

    table {
      width: 100%;
      border-collapse: collapse;
      min-width: 860px;
    }

    th,
    td {
      padding: 14px 10px;
      text-align: left;
      border-bottom: 1px solid rgba(39, 83, 77, 0.08);
      font-size: 14px;
      vertical-align: middle;
    }

    th {
      font-size: 13px;
      color: var(--muted);
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      background: rgba(250, 252, 251, 0.92);
      position: sticky;
      top: 0;
      z-index: 1;
    }

    tr:last-child td {
      border-bottom: none;
    }

    .name-cell {
      display: grid;
      gap: 4px;
    }

    .name-cell strong {
      font-size: 15px;
      font-weight: 700;
    }

    .name-meta {
      color: var(--muted);
      font-size: 12px;
    }

    .badge {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 64px;
      padding: 5px 10px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 700;
    }

    .badge.good {
      background: var(--good-bg);
      color: var(--good-text);
    }

    .badge.steady {
      background: var(--steady-bg);
      color: var(--steady-text);
    }

    .badge.low {
      background: var(--low-bg);
      color: var(--low-text);
    }

    .badge.empty {
      background: var(--empty-bg);
      color: var(--empty-text);
    }

    .delta {
      font-weight: 700;
    }

    .delta.in {
      color: var(--accent-deep);
    }

    .delta.out {
      color: var(--warm);
    }

    .table-link {
      border: none;
      background: none;
      color: var(--accent);
      cursor: pointer;
      font-size: 14px;
      font-weight: 700;
      padding: 0;
    }

    .table-link:hover {
      color: var(--accent-deep);
    }

    .empty {
      padding: 30px 12px !important;
      text-align: center;
      color: var(--muted);
    }

    .feed {
      padding: 18px 20px 20px;
      display: grid;
      gap: 12px;
    }

    .feed-item {
      padding: 15px 16px;
      border-radius: 16px;
      background: rgba(255, 255, 255, 0.78);
      border: 1px solid rgba(39, 83, 77, 0.08);
      display: grid;
      gap: 6px;
      animation: fade-up .32s ease both;
    }

    .feed-top {
      display: flex;
      justify-content: space-between;
      gap: 10px;
      align-items: center;
      font-size: 13px;
      color: var(--muted);
    }

    .feed-title {
      font-size: 15px;
      font-weight: 700;
    }

    .feed-desc {
      color: var(--muted);
      font-size: 13px;
    }

    .feed-empty {
      padding: 30px 8px;
      color: var(--muted);
      text-align: center;
    }

    .drawer {
      position: fixed;
      top: 0;
      right: 0;
      width: min(520px, 100vw);
      height: 100vh;
      background: rgba(249, 252, 251, 0.98);
      border-left: 1px solid rgba(39, 83, 77, 0.08);
      box-shadow: -24px 0 56px rgba(31, 43, 42, 0.16);
      transform: translateX(104%);
      transition: transform .28s ease;
      z-index: 30;
      display: grid;
      grid-template-rows: auto 1fr;
    }

    .drawer.open {
      transform: translateX(0);
    }

    .drawer-head {
      padding: 22px 22px 18px;
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 12px;
      border-bottom: 1px solid rgba(39, 83, 77, 0.08);
      background: rgba(255, 255, 255, 0.92);
    }

    .drawer-head h3 {
      margin: 0;
      font-size: 24px;
      font-family: "STKaiti", "KaiTi", serif;
    }

    .drawer-subtitle {
      margin-top: 8px;
      color: var(--muted);
      line-height: 1.6;
      font-size: 14px;
    }

    .drawer-body {
      overflow: auto;
      padding: 18px 22px 24px;
      display: grid;
      gap: 18px;
    }

    .detail-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }

    .detail-card {
      background: var(--surface-strong);
      border: 1px solid rgba(39, 83, 77, 0.08);
      border-radius: 16px;
      padding: 14px 15px;
      display: grid;
      gap: 6px;
    }

    .detail-card .label {
      font-size: 12px;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }

    .detail-card .value {
      font-size: 24px;
      font-weight: 700;
      color: var(--accent-deep);
    }

    .detail-card .meta {
      color: var(--muted);
      font-size: 13px;
    }

    .timeline {
      display: grid;
      gap: 12px;
    }

    .timeline-item {
      padding: 14px 15px;
      border-radius: 16px;
      background: rgba(255, 255, 255, 0.9);
      border: 1px solid rgba(39, 83, 77, 0.08);
      display: grid;
      gap: 8px;
    }

    .timeline-top {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
      flex-wrap: wrap;
    }

    .timeline-title {
      font-size: 15px;
      font-weight: 700;
    }

    .timeline-meta {
      font-size: 13px;
      color: var(--muted);
    }

    .overlay {
      position: fixed;
      inset: 0;
      background: rgba(15, 23, 42, 0.12);
      opacity: 0;
      pointer-events: none;
      transition: opacity .24s ease;
      z-index: 20;
    }

    .overlay.open {
      opacity: 1;
      pointer-events: auto;
    }

    @keyframes fade-up {
      from {
        opacity: 0;
        transform: translateY(8px);
      }
      to {
        opacity: 1;
        transform: translateY(0);
      }
    }

    @media (max-width: 1100px) {
      .stats,
      .detail-grid {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }

      .content {
        grid-template-columns: 1fr;
      }
    }

    @media (max-width: 720px) {
      body {
        padding: 14px;
      }

      .hero,
      .section-head,
      .table-wrap,
      .feed {
        padding-left: 16px;
        padding-right: 16px;
      }

      .stats,
      .detail-grid {
        grid-template-columns: 1fr;
      }

      .input {
        min-width: 0;
        width: 100%;
      }

      .toolbar {
        width: 100%;
      }

      .toolbar .btn {
        flex: 1;
      }
    }
  </style>
</head>
<body>
  <div class="shell">
    <section class="panel hero">
      <div class="hero-top">
        <div>
          <h1>__BOARD_TITLE__</h1>
          <p>实时读取本地 CSV，汇总当前库存、最后出入库人员与时间。点击任意物资，即可展开完整出入库轨迹。</p>
        </div>
        <div class="hero-meta">
          <div class="status-chip lag" id="connection-chip">
            <span class="status-dot"></span>
            <span id="connection-text">正在连接实时通道</span>
          </div>
          <div class="hero-note" id="hero-note">
            数据刷新时间: -
            <br />
            最近一笔记录: -
          </div>
        </div>
      </div>
      <div class="stats">
        <div class="stat-card">
          <div class="stat-name">Material Types</div>
          <div class="stat-value" id="stat-types">0</div>
          <div class="stat-desc">当前已纳入看板的物资种类</div>
        </div>
        <div class="stat-card">
          <div class="stat-name">Current Stock</div>
          <div class="stat-value" id="stat-quantity">0</div>
          <div class="stat-desc">汇总后的在库数量</div>
        </div>
        <div class="stat-card">
          <div class="stat-name">Active People</div>
          <div class="stat-value" id="stat-people">0</div>
          <div class="stat-desc">最近参与出入库的人员数</div>
        </div>
        <div class="stat-card">
          <div class="stat-name">Low Stock</div>
          <div class="stat-value" id="stat-low">0</div>
          <div class="stat-desc">库存小于等于 2 的物资类型</div>
        </div>
      </div>
    </section>

    <section class="content">
      <div class="panel">
        <div class="section-head">
          <div>
            <h2>库存总览</h2>
            <p id="table-caption">按物资名称聚合，最后更新时间与最近操作会自动刷新。</p>
          </div>
          <div class="toolbar">
            <input class="input" id="keyword" type="search" placeholder="搜索物资名称或人员" />
            <button class="btn" id="refresh-btn" type="button">手动刷新</button>
          </div>
        </div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>物资</th>
                <th>状态</th>
                <th>当前数量</th>
                <th>累计入库</th>
                <th>累计出库</th>
                <th>最后操作</th>
                <th>最后人员</th>
                <th>最后时间</th>
                <th>详情</th>
              </tr>
            </thead>
            <tbody id="table-body">
              <tr><td class="empty" colspan="9">正在加载库存数据...</td></tr>
            </tbody>
          </table>
        </div>
      </div>

      <aside class="panel">
        <div class="section-head">
          <div>
            <h2>最近动态</h2>
            <p>看板会随着 CSV 变化自动更新这组事件。</p>
          </div>
        </div>
        <div class="feed" id="feed-list">
          <div class="feed-empty">正在读取最近记录...</div>
        </div>
      </aside>
    </section>
  </div>

  <div class="overlay" id="overlay"></div>
  <aside class="drawer" id="drawer" aria-live="polite">
    <div class="drawer-head">
      <div>
        <h3 id="drawer-title">物资详情</h3>
        <div class="drawer-subtitle" id="drawer-subtitle">选择一项物资查看完整轨迹。</div>
      </div>
      <button class="btn" id="close-drawer" type="button">关闭</button>
    </div>
    <div class="drawer-body">
      <section>
        <div class="detail-grid" id="detail-grid">
          <div class="detail-card">
            <div class="label">Current Quantity</div>
            <div class="value">-</div>
            <div class="meta">等待选择物资</div>
          </div>
        </div>
      </section>
      <section>
        <div class="section-head" style="padding: 0;">
          <div>
            <h2 style="font-size: 18px;">出入库时间线</h2>
            <p style="margin-top: 4px;">按时间倒序展示该物资的所有变化。</p>
          </div>
        </div>
        <div class="timeline" id="timeline">
          <div class="feed-empty">暂无数据</div>
        </div>
      </section>
    </div>
  </aside>

  <script>
    const state = {
      materials: [],
      recentEvents: [],
      keyword: "",
      activeKey: null,
      stream: null,
      fallbackTimer: null,
    };

    function esc(value) {
      return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;");
    }

    function formatQuantity(value) {
      const num = Number(value);
      if (!Number.isFinite(num)) {
        return String(value ?? "-");
      }
      if (Number.isInteger(num)) {
        return String(num);
      }
      return num.toFixed(2).replace(/0+$/, "").replace(/[.]$/, "");
    }

    function formatDelta(value) {
      const num = Number(value);
      if (!Number.isFinite(num)) {
        return String(value ?? "-");
      }
      if (num > 0) {
        return `+${formatQuantity(num)}`;
      }
      return formatQuantity(num);
    }

    function toneClass(tone) {
      return ["good", "steady", "low", "empty"].includes(tone) ? tone : "steady";
    }

    function setConnectionStatus(isLive, text) {
      const chip = document.getElementById("connection-chip");
      chip.classList.toggle("live", isLive);
      chip.classList.toggle("lag", !isLive);
      document.getElementById("connection-text").textContent = text;
    }

    async function fetchSummary() {
      const response = await fetch("/api/summary", { cache: "no-store" });
      if (!response.ok) {
        throw new Error(`加载汇总失败: ${response.status}`);
      }
      return response.json();
    }

    async function fetchDetail(materialKey) {
      const response = await fetch(`/api/material/${encodeURIComponent(materialKey)}`, { cache: "no-store" });
      if (!response.ok) {
        throw new Error(`加载详情失败: ${response.status}`);
      }
      return response.json();
    }

    function renderHeader(payload) {
      const generatedAt = payload.generated_at || "-";
      const latestEventTime = payload.stats?.latest_event_time || "-";
      document.getElementById("hero-note").innerHTML = `数据刷新时间: ${esc(generatedAt)}<br />最近一笔记录: ${esc(latestEventTime)}`;
      document.getElementById("table-caption").textContent = `数据源: ${payload.source_csv} · 记录总数 ${payload.stats?.total_transactions ?? 0}`;
    }

    function renderStats(stats) {
      document.getElementById("stat-types").textContent = formatQuantity(stats.material_types ?? 0);
      document.getElementById("stat-quantity").textContent = formatQuantity(stats.total_quantity ?? 0);
      document.getElementById("stat-people").textContent = formatQuantity(stats.active_people ?? 0);
      document.getElementById("stat-low").textContent = formatQuantity(stats.low_stock_types ?? 0);
    }

    function filteredMaterials() {
      const keyword = state.keyword.trim().toLowerCase();
      if (!keyword) {
        return state.materials;
      }
      return state.materials.filter((item) => {
        const haystack = `${item.material_name} ${item.last_person} ${item.last_action}`.toLowerCase();
        return haystack.includes(keyword);
      });
    }

    function renderTable() {
      const rows = filteredMaterials();
      const tbody = document.getElementById("table-body");
      if (!rows.length) {
        tbody.innerHTML = `<tr><td class="empty" colspan="9">没有匹配到物资记录</td></tr>`;
        return;
      }

      tbody.innerHTML = rows.map((item) => {
        const deltaClass = item.last_action === "入库" ? "in" : "out";
        return `
          <tr>
            <td>
              <div class="name-cell">
                <strong>${esc(item.material_name)}</strong>
                <span class="name-meta">共 ${esc(item.transaction_count)} 笔记录</span>
              </div>
            </td>
            <td><span class="badge ${toneClass(item.status_tone)}">${esc(item.status_label)}</span></td>
            <td>${esc(formatQuantity(item.current_quantity))}</td>
            <td>${esc(formatQuantity(item.total_inbound))}</td>
            <td>${esc(formatQuantity(item.total_outbound))}</td>
            <td><span class="delta ${deltaClass}">${esc(item.last_action)}</span></td>
            <td>${esc(item.last_person)}</td>
            <td>${esc(item.last_time)}</td>
            <td><button class="table-link" type="button" data-key="${esc(item.material_key)}">查看详情</button></td>
          </tr>
        `;
      }).join("");

      tbody.querySelectorAll("[data-key]").forEach((button) => {
        button.addEventListener("click", () => {
          openDrawer(button.getAttribute("data-key"));
        });
      });
    }

    function renderFeed() {
      const feed = document.getElementById("feed-list");
      if (!state.recentEvents.length) {
        feed.innerHTML = `<div class="feed-empty">暂无最近动态</div>`;
        return;
      }

      feed.innerHTML = state.recentEvents.map((event) => {
        const directionClass = Number(event.delta) >= 0 ? "in" : "out";
        return `
          <div class="feed-item">
            <div class="feed-top">
              <span>${esc(event.display_time)}</span>
              <span class="delta ${directionClass}">${esc(event.action)} ${esc(formatDelta(event.delta))}</span>
            </div>
            <div class="feed-title">${esc(event.material_name)}</div>
            <div class="feed-desc">${esc(event.person)} · 请求 ${esc(event.request_id)}</div>
          </div>
        `;
      }).join("");
    }

    function renderDetail(summary, history) {
      document.getElementById("drawer-title").textContent = summary.material_name || "物资详情";
      document.getElementById("drawer-subtitle").textContent = `最后操作: ${summary.last_action || "-"} · ${summary.last_person || "-"} · ${summary.last_time || "-"}`;

      document.getElementById("detail-grid").innerHTML = `
        <div class="detail-card">
          <div class="label">Current Quantity</div>
          <div class="value">${esc(formatQuantity(summary.current_quantity))}</div>
          <div class="meta">${esc(summary.status_label || "-")}</div>
        </div>
        <div class="detail-card">
          <div class="label">Transactions</div>
          <div class="value">${esc(formatQuantity(summary.transaction_count || 0))}</div>
          <div class="meta">该物资累计记录数</div>
        </div>
        <div class="detail-card">
          <div class="label">Inbound Total</div>
          <div class="value">${esc(formatQuantity(summary.total_inbound || 0))}</div>
          <div class="meta">历史累计入库数量</div>
        </div>
        <div class="detail-card">
          <div class="label">Outbound Total</div>
          <div class="value">${esc(formatQuantity(summary.total_outbound || 0))}</div>
          <div class="meta">历史累计出库数量</div>
        </div>
      `;

      const timeline = document.getElementById("timeline");
      if (!history.length) {
        timeline.innerHTML = `<div class="feed-empty">暂无该物资的历史记录</div>`;
        return;
      }

      timeline.innerHTML = history.map((item) => {
        const directionClass = Number(item.delta) >= 0 ? "in" : "out";
        return `
          <div class="timeline-item">
            <div class="timeline-top">
              <div class="timeline-title">${esc(item.action)} ${esc(formatDelta(item.delta))}</div>
              <span class="badge ${Number(item.running_quantity_after) <= 2 ? "low" : "good"}">操作后库存 ${esc(formatQuantity(item.running_quantity_after))}</span>
            </div>
            <div class="timeline-meta">${esc(item.display_time)} · ${esc(item.person)} · 请求 ${esc(item.request_id)}</div>
            <div class="timeline-meta">本次数量 ${esc(formatQuantity(item.quantity))} · 数据写入 ${esc(item.received_at || "-")}</div>
          </div>
        `;
      }).join("");
    }

    async function applyPayload(payload) {
      state.materials = payload.materials || [];
      state.recentEvents = payload.recent_events || [];
      renderHeader(payload);
      renderStats(payload.stats || {});
      renderTable();
      renderFeed();
      if (state.activeKey) {
        try {
          const detail = await fetchDetail(state.activeKey);
          renderDetail(detail.summary || {}, detail.history || []);
        } catch (error) {
          console.error(error);
        }
      }
    }

    async function loadSummary() {
      const payload = await fetchSummary();
      await applyPayload(payload);
    }

    async function openDrawer(materialKey) {
      state.activeKey = materialKey;
      document.getElementById("drawer").classList.add("open");
      document.getElementById("overlay").classList.add("open");
      document.getElementById("timeline").innerHTML = `<div class="feed-empty">正在加载详情...</div>`;
      try {
        const detail = await fetchDetail(materialKey);
        renderDetail(detail.summary || {}, detail.history || []);
      } catch (error) {
        document.getElementById("timeline").innerHTML = `<div class="feed-empty">${esc(error.message)}</div>`;
      }
    }

    function closeDrawer() {
      state.activeKey = null;
      document.getElementById("drawer").classList.remove("open");
      document.getElementById("overlay").classList.remove("open");
    }

    function startFallbackPolling() {
      if (state.fallbackTimer) {
        return;
      }
      state.fallbackTimer = window.setInterval(() => {
        loadSummary().catch((error) => console.error(error));
      }, 15000);
    }

    function connectStream() {
      if (!("EventSource" in window)) {
        setConnectionStatus(false, "浏览器不支持实时通道，已切换轮询");
        startFallbackPolling();
        return;
      }

      const stream = new EventSource("/api/stream");
      state.stream = stream;

      stream.addEventListener("summary", async (event) => {
        setConnectionStatus(true, "实时同步中");
        await applyPayload(JSON.parse(event.data));
      });

      stream.onopen = () => {
        setConnectionStatus(true, "实时同步中");
      };

      stream.onerror = () => {
        setConnectionStatus(false, "实时通道波动，等待自动重连");
        startFallbackPolling();
      };
    }

    document.getElementById("keyword").addEventListener("input", (event) => {
      state.keyword = event.target.value;
      renderTable();
    });
    document.getElementById("refresh-btn").addEventListener("click", () => {
      loadSummary().catch((error) => console.error(error));
    });
    document.getElementById("close-drawer").addEventListener("click", closeDrawer);
    document.getElementById("overlay").addEventListener("click", closeDrawer);
    window.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        closeDrawer();
      }
    });

    loadSummary()
      .then(() => connectStream())
      .catch((error) => {
        setConnectionStatus(false, error.message);
        startFallbackPolling();
      });
  </script>
</body>
</html>
"""


def render_dashboard_page(board_title: str) -> str:
    escaped_title = html.escape(board_title or "物资看板")
    return HTML_PAGE.replace("__BOARD_TITLE__", escaped_title)
