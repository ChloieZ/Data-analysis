/* 数据管理页：文件接入 + SQL 工作台 */

/* ==================== 子标签 ==================== */
let currentTab = "files";
let TABLE_NAMES = [];   // 当前库内表名（用于「保存为表」重名确认）

/* 读取初始标签：优先 URL hash(#sql) → ?tab=sql → 记住的上次选择 → 默认 files */
function initialTab() {
  const byHash = (location.hash || "").replace("#", "");
  if (byHash === "files" || byHash === "sql") return byHash;
  const byQuery = new URLSearchParams(location.search).get("tab");
  if (byQuery === "files" || byQuery === "sql") return byQuery;
  try {
    const saved = localStorage.getItem("sourceTab");
    if (saved === "files" || saved === "sql") return saved;
  } catch (e) { /* 隐私模式忽略 */ }
  return "files";
}

function switchTab(name) {
  if (name !== "files" && name !== "sql") name = "files";
  currentTab = name;
  document.querySelectorAll(".tabs .tab").forEach(t =>
    t.classList.toggle("active", t.dataset.tab === name));
  document.getElementById("tab-files").style.display = name === "files" ? "flex" : "none";
  document.getElementById("tab-sql").style.display = name === "sql" ? "block" : "none";
  try { localStorage.setItem("sourceTab", name); } catch (e) { /* ignore */ }
  // 写进 URL（replaceState 不产生历史记录），刷新/收藏都能回到同一标签
  if (location.hash !== "#" + name) history.replaceState(null, "", "#" + name);
  return refreshTab();
}

// 浏览器前进/后退切换标签
window.addEventListener("hashchange", () => {
  const h = (location.hash || "").replace("#", "");
  if ((h === "files" || h === "sql") && h !== currentTab) switchTab(h);
});

function refreshTab() {
  return currentTab === "files" ? loadFilesTab() : loadSqlTab();
}

/* ==================== 文件接入 ==================== */
const LAYERS = [
  ["raw_spending", "原始层"],
  ["dwd_spending", "明细层"],
  ["dws_monthly_category", "汇总层"],
];

async function loadLayers() {
  const h = await api("/api/health");
  document.getElementById("layerCards").innerHTML = LAYERS.map(([t, label]) =>
    `<div class="card"><div class="label">${label}</div>
     <div class="value">${fi(h.tables[t])} <small>行</small></div>
     <div class="muted" style="font-size:11.5px;margin-top:4px">${t}</div></div>`).join("")
    + `<div class="card"><div class="label">源文件</div>
       <div class="value" id="fileStat">- <small>个</small></div>
       <div class="muted" style="font-size:11.5px;margin-top:4px">data/input</div></div>`;
}

async function loadFiles() {
  const { files } = await api("/api/sources");
  document.getElementById("fileCount").textContent = `${files.length} 个文件`;
  const stat = document.getElementById("fileStat");
  if (stat) stat.innerHTML = `${files.length} <small>个</small>`;

  const box = document.getElementById("fileList");
  if (!files.length) {
    box.innerHTML = `<div class="empty">还没有上传任何表格<br/>把花销表拖到上面的虚线区即可</div>`;
    return;
  }
  const rows = files.map(f => `<tr>
      <td class="wrap-cell">${esc(f.name)}</td>
      <td>${f.rows == null ? '<span class="up">解析失败</span>' : fi(f.rows)}</td>
      <td>${bytes(f.size)}</td>
      <td>${esc(f.mtime)}</td>
      <td>
        <button class="btn sm" onclick="previewFile('${encodeURIComponent(f.name)}')">预览</button>
        <button class="btn sm" onclick="parseFile('${encodeURIComponent(f.name)}')">解析</button>
        <button class="btn sm danger" onclick="deleteFile('${encodeURIComponent(f.name)}')">删除</button>
      </td></tr>`).join("");
  box.innerHTML = `<table><thead><tr><th>文件名</th><th>行数</th><th>大小</th><th>修改时间</th><th>操作</th></tr></thead><tbody>${rows}</tbody></table>`;
}

async function previewFile(name) {
  try {
    const d = await postJSON("/api/sources/preview", { name: decodeURIComponent(name), limit: 50 });
    const sheets = d.sheets && d.sheets.length > 1 ? ` · ${d.sheets.length} 个 Sheet` : "";
    document.getElementById("previewTag").textContent =
      `${d.name}${sheets} · 原样前 ${d.rows.length} 行`;
    document.getElementById("previewBox").innerHTML = renderTable(d.columns, d.rows);
  } catch (e) { toast("预览失败：" + e.message, true); }
}

/* 解析：把文件按平台口径转成规范四列（宽表自动 melt），并支持导出为数据文件 */
async function parseFile(name) {
  try {
    const d = await postJSON("/api/sources/parse", { name: decodeURIComponent(name), limit: 200 });
    document.getElementById("previewTag").textContent =
      `${d.name} · 解析为规范四列 · 共 ${fi(d.total)} 行 / ${d.months} 个月 / 合计 ¥${fm(d.amount_total)}`;
    document.getElementById("previewBox").innerHTML =
      renderTable(d.columns, d.rows,
        { note: `仅预览前 ${d.rows.length} 行；点下方按钮导出完整数据文件（CSV）。` }) +
      `<div style="margin-top:10px">
         <button class="btn sm primary" onclick="exportParsed('${name}')">⬇ 导出解析结果 CSV</button>
       </div>`;
  } catch (e) { toast("解析失败：" + e.message, true); }
}

async function exportParsed(name) {
  const n = decodeURIComponent(name);
  try {
    const resp = await fetch("/api/sources/parse/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: n }),
    });
    if (!resp.ok) {
      const e = await resp.json().catch(() => ({ detail: resp.statusText }));
      throw new Error(e.detail || "导出失败");
    }
    const url = URL.createObjectURL(await resp.blob());
    const a = document.createElement("a");
    a.href = url;
    a.download = n.replace(/\.[^.]+$/, "") + ".parsed.csv";
    document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(url);
    toast("已导出解析后的数据文件");
  } catch (e) { toast("导出失败：" + e.message, true); }
}

async function deleteFile(name) {
  const n = decodeURIComponent(name);
  if (!confirm(`确定删除源文件「${n}」？\n（已导入到数据库的数据不会被删除）`)) return;
  try {
    await api("/api/sources?name=" + encodeURIComponent(n), { method: "DELETE" });
    toast("已删除：" + n);
    document.getElementById("previewBox").innerHTML = "";
    document.getElementById("previewTag").textContent = "点击左侧文件查看前 50 行";
    await loadFiles();
  } catch (e) { toast("删除失败：" + e.message, true); }
}

async function uploadFile(picked) {
  const f = picked || document.getElementById("fileInput").files[0];
  if (!f) { toast("请先选择文件", true); return; }
  const fd = new FormData();
  fd.append("file", f);
  fd.append("mode", document.getElementById("ingestMode").value);
  const btn = document.getElementById("uploadBtn");
  btn.disabled = true; btn.textContent = "导入中...";
  try {
    const r = await api("/api/ingest", { method: "POST", body: fd });
    toast(`导入完成：读取 ${r.ingest.total_read} 行，写入 ${r.ingest.inserted} 行，跳过 ${r.ingest.skipped} 行；ETL 明细 ${r.etl.dwd_count} 行`);
    document.getElementById("fileInput").value = "";
    await loadLayers(); await loadFiles();
  } catch (e) { toast("导入失败：" + e.message, true); }
  finally { btn.disabled = false; btn.textContent = "上传并导入"; }
}

async function triggerEtl() {
  try {
    const r = await api("/api/etl", { method: "POST" });
    toast(`ETL 完成：原始 ${r.raw_total} → 明细 ${r.dwd_count} → 汇总 ${r.dws_count} 行`);
    await loadLayers(); await loadTables();
  } catch (e) { toast("ETL 失败：" + e.message, true); }
}

/* ---------- SQL 追加 ---------- */
const APPEND_EXAMPLES = [
  `-- 查询写法：补录 2025-09 的几笔（列名用 日期/类别/金额/备注）
SELECT * FROM (VALUES
    ('2025-09-01', '餐饮', 38.50, '午餐'),
    ('2025-09-02', '交通', 12.00, '地铁'),
    ('2025-09-03', '购物', 268.00, '日用品')
) AS t(日期, 类别, 金额, 备注);`,
  `-- 写入写法：直接往原始层插一条（无需勾选去重，重复与否由你自己控制）
INSERT INTO raw_spending ("日期", "类别", "金额", "备注")
VALUES ('2025-09-05', '餐饮', 42.00, '外卖');`,
];

function setAppendExample(i) {
  document.getElementById("appendSql").value = APPEND_EXAMPLES[i];
  document.getElementById("appendSql").focus();
}

async function appendBySql() {
  const sql = document.getElementById("appendSql").value.trim();
  if (!sql) { toast("SQL 不能为空", true); return; }
  const btn = document.getElementById("appendBtn");
  btn.disabled = true; btn.textContent = "追加中...";
  try {
    const r = await postJSON("/api/append/sql",
      { sql, dedup: document.getElementById("appendDedup").checked });
    const a = r.append;
    const head = a.form === "select"
      ? `SQL 追加完成：结果 ${a.total_read} 行 → 写入 ${a.inserted} 行，跳过 ${a.skipped} 行`
      : `语句执行成功：影响 ${a.affected == null ? "?" : a.affected} 行（去重由语句负责）`;
    toast(`${head}；ETL 明细 ${r.etl.dwd_count} 行`);
    await loadLayers();
  } catch (e) { toast("追加失败：" + e.message, true); }
  finally { btn.disabled = false; btn.textContent = "执行追加"; }
}

/* 拖拽上传：整页接管「别打开文件」，拖到虚线区即导入 */
(function () {
  const input = document.getElementById("fileInput");
  const dz = document.getElementById("dropZone");
  ["dragover", "drop"].forEach(ev =>
    document.addEventListener(ev, e => e.preventDefault()));
  ["dragenter", "dragover"].forEach(ev => dz.addEventListener(ev, e => {
    e.preventDefault(); dz.classList.add("over");
  }));
  ["dragleave", "dragend"].forEach(ev => dz.addEventListener(ev, () => dz.classList.remove("over")));
  dz.addEventListener("drop", e => {
    e.preventDefault(); e.stopPropagation();
    dz.classList.remove("over");
    const f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
    if (!f) { toast("没有检测到文件", true); return; }
    try {                                    // 顺手回填到文件框（部分浏览器不支持构造 DataTransfer）
      const dt = new DataTransfer(); dt.items.add(f); input.files = dt.files;
    } catch (err) { /* 忽略：直接传文件对象给上传函数 */ }
    uploadFile(f);
  });
})();

async function loadFilesTab() {
  await loadLayers();
  await loadFiles();
}

/* ==================== SQL 工作台 ==================== */
const SQL_EXAMPLES = [
  `-- 建一张自己的月度汇总表（CREATE 建表）
CREATE OR REPLACE TABLE my_monthly AS
SELECT month,
       round(sum(total_amount), 2) AS total_amount,
       sum(order_count)            AS order_count
FROM dws_monthly_category
GROUP BY month
ORDER BY month;`,
  `-- 查询某月金额 Top 5 的类别
SELECT category,
       round(sum(amount), 2) AS total_amount,
       count(*)              AS order_count
FROM dwd_spending
WHERE month = '2025-08'
GROUP BY category
ORDER BY total_amount DESC
LIMIT 5;`,
  `-- 自定义指标：笔均支出与备注关键词
SELECT month,
       round(sum(amount), 2)           AS total_amount,
       count(*)                        AS cnt,
       round(sum(amount) / count(*), 2) AS avg_per_order
FROM dwd_spending
WHERE note ILIKE '%外卖%'
GROUP BY month
ORDER BY month;`,
];

async function loadTables() {
  const { tables } = await api("/api/tables");
  TABLE_NAMES = tables.map(t => t.name);
  document.getElementById("tableCount").textContent = `${tables.length} 张`;
  const box = document.getElementById("tableList");
  if (!tables.length) { box.innerHTML = `<div class="empty">还没有表</div>`; return; }
  box.innerHTML = tables.map(t =>
    `<div class="tableitem" onclick="previewTable('${encodeURIComponent(t.name)}')">
       <span>${esc(t.name)}</span><span class="cnt">${t.rows == null ? "?" : fi(t.rows)} 行</span>
     </div>`).join("");
}

async function previewTable(name) {
  try {
    const d = await postJSON("/api/table/preview", { name: decodeURIComponent(name), limit: 100 });
    document.getElementById("resultTag").textContent = `${d.name} · 前 ${d.rows.length} 行`;
    document.getElementById("resultBox").innerHTML = renderTable(d.columns, d.rows);
  } catch (e) { toast("预览失败：" + e.message, true); }
}

function renderResult(data) {
  const parts = [];
  let n = 0;
  for (const r of data.results) {
    if (r.type === "query") {
      parts.push(`<div class="muted" style="margin:10px 0 6px">
        <b>结果 ${++n}</b> · ${r.row_count} 行${r.truncated ? "（已截断）" : ""}</div>`);
      parts.push(renderTable(r.columns, r.rows));
    } else {
      parts.push(`<div class="sqlstatus ok">✓ 语句执行成功${r.rowcount == null ? "" : " · 影响 " + fi(r.rowcount) + " 行"}
        <div class="muted" style="font-size:11.5px;margin-top:4px">${esc(r.sql)}</div></div>`);
    }
  }
  return parts.join("");
}

async function runSql() {
  const sql = document.getElementById("editor").value.trim();
  if (!sql) { toast("SQL 不能为空", true); return; }
  const btn = document.getElementById("runBtn");
  btn.disabled = true; btn.textContent = "执行中...";
  const hint = document.getElementById("sqlHint");
  try {
    const data = await postJSON("/api/sql", { sql, limit: 500 });
    document.getElementById("resultTag").textContent = `${data.statement_count} 条语句 · ${data.elapsed_ms} ms`;
    document.getElementById("resultBox").innerHTML = renderResult(data) || `<div class="empty">没有返回结果</div>`;
    hint.textContent = ""; hint.className = "muted";
    await loadTables();
  } catch (e) {
    document.getElementById("resultBox").innerHTML = "";
    hint.textContent = "执行失败"; hint.className = "sqlstatus err";
    document.getElementById("resultTag").textContent = "";
    toast("执行失败：" + e.message, true);
  } finally { btn.disabled = false; btn.textContent = "▶ 执行"; }
}

function setExample(i) {
  document.getElementById("editor").value = SQL_EXAMPLES[i];
  document.getElementById("editor").focus();
}

/* 保存为表：把当前 SELECT 结果落库成一张表（CREATE TABLE AS SELECT） */
async function saveAsTable() {
  const sql = document.getElementById("editor").value.trim();
  if (!sql) { toast("SQL 不能为空", true); return; }
  const name = (prompt("保存为表名（中英文/数字/下划线）：", "my_result") || "").trim();
  if (!name) return;
  if (TABLE_NAMES.includes(name) &&
      !confirm(`表「${name}」已存在，确定覆盖？`)) return;
  const btn = document.getElementById("saveBtn");
  btn.disabled = true; btn.textContent = "保存中...";
  try {
    const r = await postJSON("/api/sql/save", { sql, name, replace: true });
    toast(`已保存为表 ${r.name}（${fi(r.rows)} 行）`);
    await loadTables();
  } catch (e) { toast("保存失败：" + e.message, true); }
  finally { btn.disabled = false; btn.textContent = "💾 保存为表"; }
}

/* 导出当前查询结果为 CSV（后端仅允许 SELECT） */
async function exportSql() {
  const sql = document.getElementById("editor").value.trim();
  if (!sql) { toast("SQL 不能为空", true); return; }
  const btn = document.getElementById("exportBtn");
  btn.disabled = true; btn.textContent = "导出中...";
  try {
    const resp = await fetch("/api/sql/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sql, limit: 10000 }),
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: resp.statusText }));
      throw new Error(err.detail || "导出失败");
    }
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "query_export.csv";
    document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(url);
    toast("已导出 CSV");
  } catch (e) { toast("导出失败：" + e.message, true); }
  finally { btn.disabled = false; btn.textContent = "⬇ 导出 CSV"; }
}

function clearSql() {
  document.getElementById("editor").value = "";
  document.getElementById("resultTag").textContent = "";
  document.getElementById("resultBox").innerHTML = `<div class="empty">输入 SQL 后点击「执行」</div>`;
  document.getElementById("sqlHint").textContent = "";
}

document.getElementById("editor").addEventListener("keydown", e => {
  if (e.ctrlKey && e.key === "Enter") { e.preventDefault(); runSql(); }
});

async function loadSqlTab() {
  await loadTables();
  if (!document.getElementById("editor").value) setExample(1);
}

/* ==================== 启动 ==================== */
(async function () {
  try { await switchTab(initialTab()); }
  catch (e) { toast("加载失败：" + e.message, true); }
})();
