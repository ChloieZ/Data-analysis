/* 图表工坊：内置指标 + 拖拽生成图表 */

const TYPE_LABEL = { bar: "柱状", line: "折线", pie: "饼图", table: "表格" };
const PALETTE = ["#4f8cff", "#22c3a6", "#ffb84d", "#ff6b6b", "#a97bff",
                 "#3ad0ff", "#f7d94c", "#7bff9e", "#ff9ecd", "#8b98ad"];

/* 内置指标：点一下 / 拖一下即可出图 */
const METRICS = [
  { id: "m_year", name: "年度支出对比", desc: "各年总支出（不选年份=全部）", kind: "simple", chart: "bar", dimension: "year", measure: "total_amount" },
  { id: "m_trend", name: "月度支出趋势", desc: "各月总支出走势", kind: "simple", chart: "line", dimension: "month", measure: "total_amount" },
  { id: "m_count", name: "月度消费笔数", desc: "各月有效记录数", kind: "simple", chart: "bar", dimension: "month", measure: "order_count" },
  { id: "m_avg", name: "笔均支出趋势", desc: "各月平均每笔支出", kind: "simple", chart: "line", dimension: "month", measure: "avg_amount" },
  { id: "m_pie", name: "分类占比", desc: "各类别金额占比", kind: "simple", chart: "pie", dimension: "category", measure: "total_amount" },
  { id: "m_cat", name: "分类支出对比", desc: "各类别总支出", kind: "simple", chart: "bar", dimension: "category", measure: "total_amount" },
  { id: "m_cat_cnt", name: "分类消费笔数", desc: "各类别记录数", kind: "simple", chart: "bar", dimension: "category", measure: "order_count" },
  { id: "m_wd", name: "星期支出分布", desc: "各星期支出金额", kind: "simple", chart: "bar", dimension: "weekday", measure: "total_amount" },
  { id: "m_wd_cnt", name: "星期消费笔数", desc: "各星期消费笔数", kind: "simple", chart: "bar", dimension: "weekday", measure: "order_count" },
  { id: "m_note", name: "备注支出排行", desc: "按备注聚合的支出", kind: "simple", chart: "bar", dimension: "note", measure: "total_amount" },
  { id: "m_month_cat", name: "分类 × 月份对比", desc: "多月份各分类并排对比", kind: "crosstab", chart: "bar", dimension: "category", measure: "total_amount" },
];
const DEFAULT_CARDS = ["m_trend", "m_pie", "m_cat"];

let meta = null;
let cards = [];
let uid = 0;
let custom = { dim: null, meas: null, type: "bar" };
const pickedYears = new Set();        // 空集合 = 全部年份
const instances = new Map();          // uid -> echarts 实例

/* 年份开关标签：点一下选中、再点取消；全不选 = 全部年份 */
function renderYearChips() {
  document.getElementById("fYears").innerHTML = (meta.years || []).map(y =>
    `<span class="chip${pickedYears.has(y) ? " on" : ""}" data-year="${y}">${y}</span>`).join("")
    || `<span class="muted" style="font-size:12px">库内暂无数据</span>`;
  document.querySelectorAll("#fYears .chip").forEach(el => {
    el.addEventListener("click", () => {
      const y = el.dataset.year;
      pickedYears.has(y) ? pickedYears.delete(y) : pickedYears.add(y);
      renderYearChips();
      renderAll();                    // 立即刷新画布
    });
  });
}

/* ---------------- 基础 ---------------- */
const filters = () => {
  const months = selectedValues(document.getElementById("fMonths"));
  const cats = selectedValues(document.getElementById("fCats"));
  const note = document.getElementById("fNote").value.trim();
  const min = document.getElementById("fMin").value;
  return { years: pickedYears.size ? [...pickedYears] : null,
           months: months.length ? months : null,
           categories: cats.length ? cats : null,
           note: note || null, min_amount: min === "" ? null : Number(min) };
};
const labelOf = (type, key) => {
  const list = type === "dim" ? meta.dimensions : meta.measures;
  const hit = list.find(x => x.key === key);
  return hit ? hit.label : key;
};

/* 一键清空所有筛选（含年份标签） */
function clearFilters() {
  pickedYears.clear();
  ["fMonths", "fCats"].forEach(id => {
    const sel = document.getElementById(id);
    Array.from(sel.options).forEach(o => { o.selected = false; });
  });
  document.getElementById("fNote").value = "";
  document.getElementById("fMin").value = "";
  renderYearChips();
  renderAll();
}

/* ---------------- 画布 ---------------- */
function cardHtml(card) {
  const types = ["bar", "line", "pie", "table"];
  return `<div class="chart-card">
    <div class="hd">
      <span class="t" title="${esc(card.title)}">${esc(card.title)}</span>
      <div class="seg">${types.map(t =>
        `<button class="btn sm ${card.chart === t ? "active" : ""}" onclick="setChart(${card.uid},'${t}')">${TYPE_LABEL[t]}</button>`).join("")}</div>
      <button class="btn sm danger" onclick="removeCard(${card.uid})" title="移除">✕</button>
    </div>
    <div class="box ${card.chart === "table" ? "tbl" : ""}" id="box-${card.uid}"></div>
  </div>`;
}

function renderAll() {
  instances.forEach(el => el.dispose());
  instances.clear();
  const canvas = document.getElementById("canvas");
  canvas.innerHTML = cards.map(cardHtml).join("");
  document.getElementById("canvasEmpty").style.display = cards.length ? "none" : "block";
  document.getElementById("canvasTag").textContent =
    cards.length ? `共 ${cards.length} 张图 · 可切换图形类型` : "把左侧「内置指标」拖到这里，或直接点击";
  cards.forEach(renderCard);
}

async function renderCard(card) {
  const box = document.getElementById("box-" + card.uid);
  if (!box) return;
  const f = filters();
  try {
    if (card.kind === "crosstab") {
      drawCrosstab(box, card, await postJSON("/api/crosstab",
        { years: f.years, months: f.months, categories: f.categories, note: f.note, measure: card.measure }));
    } else {
      drawSimple(box, card, await postJSON("/api/chart",
        { ...f, dimension: card.dimension, measure: card.measure, limit: 100 }));
    }
  } catch (e) { box.innerHTML = `<div class="empty">加载失败：${esc(e.message)}</div>`; }
}

function axisOption(names, series, extra = {}) {
  return {
    tooltip: { trigger: "axis" },
    grid: { left: 66, right: 22, top: 24, bottom: 52 },
    color: PALETTE,
    xAxis: { type: "category", data: names,
             axisLine: { lineStyle: { color: "#2a3446" } },
             axisLabel: { color: "#8b98ad", interval: 0, rotate: names.length > 6 ? 25 : 0 } },
    yAxis: { type: "value", splitLine: { lineStyle: { color: "#232c3c" } },
             axisLabel: { color: "#8b98ad" } },
    series, ...extra,
  };
}

function drawSimple(box, card, d) {
  if (card.chart === "table") {
    box.innerHTML = renderTable([d.dimension_label, d.measure_label],
      d.rows.map(r => [r.dimension, fm(r.measure)]),
      { note: `合计 ${fm(d.total)} ${d.unit}` });
    return;
  }
  if (!d.rows.length) { box.innerHTML = `<div class="empty">没有数据</div>`; return; }
  const el = echarts.init(box);
  instances.set(card.uid, el);
  const names = d.rows.map(r => r.dimension), vals = d.rows.map(r => r.measure);

  if (card.chart === "pie") {
    el.setOption({
      tooltip: { trigger: "item", formatter: p => `${p.name}<br/>${fm(p.value)} (${p.percent}%)` },
      legend: { bottom: 0, type: "scroll", textStyle: { color: "#8b98ad" } },
      color: PALETTE,
      series: [{ type: "pie", radius: ["38%", "62%"], center: ["50%", "46%"],
        itemStyle: { borderColor: "#171e2e", borderWidth: 2 },
        label: { color: "#e6ebf5", formatter: "{b}\n{d}%" },
        data: d.rows.map(r => ({ name: r.dimension, value: r.measure })) }],
    });
    return;
  }
  el.setOption(axisOption(names, [{
    type: card.chart === "line" ? "line" : "bar", data: vals, smooth: true,
    itemStyle: { color: "#4f8cff", borderRadius: [6, 6, 0, 0] },
    lineStyle: { color: "#4f8cff", width: 3 },
    areaStyle: card.chart === "line" ? { opacity: .18 } : undefined,
  }], { tooltip: { trigger: "axis", formatter: p => `${p[0].axisValue}<br/>${fm(p[0].value)} ${d.unit}` } }));
}

function drawCrosstab(box, card, d) {
  if (!d.rows.length) { box.innerHTML = `<div class="empty">没有数据</div>`; return; }
  if (card.chart === "table") {
    box.innerHTML = renderTable(["月份", ...d.columns, "合计"],
      d.rows.map(r => [r.month, ...d.columns.map(c => fm(r[c])), fm(r._total)]));
    return;
  }
  const el = echarts.init(box);
  instances.set(card.uid, el);
  if (card.chart === "pie") {              // 饼图不适合多序列，退化为合计占比
    const totals = d.columns.map(c => d.rows.reduce((s, r) => s + (r[c] || 0), 0));
    el.setOption({
      tooltip: { trigger: "item", formatter: p => `${p.name}<br/>${fm(p.value)} (${p.percent}%)` },
      legend: { bottom: 0, type: "scroll", textStyle: { color: "#8b98ad" } },
      color: PALETTE,
      series: [{ type: "pie", radius: ["38%", "62%"], center: ["50%", "46%"],
        itemStyle: { borderColor: "#171e2e", borderWidth: 2 },
        label: { color: "#e6ebf5", formatter: "{b}\n{d}%" },
        data: d.columns.map((c, i) => ({ name: c, value: totals[i] })) }],
    });
    return;
  }
  el.setOption(axisOption(d.columns, d.rows.map(r => ({
    name: r.month, type: card.chart === "line" ? "line" : "bar",
    data: d.columns.map(c => r[c]),
  })), { legend: { bottom: 0, type: "scroll", textStyle: { color: "#8b98ad" } },
         grid: { left: 66, right: 22, top: 24, bottom: 58 } }));
}

/* ---------------- 卡片操作 ---------------- */
function addCard(spec) {
  cards.push({ uid: ++uid, chart: "bar", ...spec });
  renderAll();
}
function addMetric(id) {
  const m = METRICS.find(x => x.id === id);
  if (!m) return;
  addCard({ title: m.name, kind: m.kind, dimension: m.dimension, measure: m.measure, chart: m.chart });
}
function setChart(u, type) {
  const c = cards.find(x => x.uid === u);
  if (c) { c.chart = type; renderAll(); }
}
function removeCard(u) {
  cards = cards.filter(x => x.uid !== u);
  renderAll();
}
function clearCanvas() {
  if (cards.length && !confirm("确定清空画布上的所有图表？")) return;
  cards = []; renderAll();
}
function addCustomChart() {
  if (!custom.dim || !custom.meas) { toast("请先选择维度和度量", true); return; }
  addCard({
    title: `${labelOf("dim", custom.dim)} × ${labelOf("meas", custom.meas)}`,
    kind: "simple", dimension: custom.dim, measure: custom.meas, chart: custom.type,
  });
}

/* ---------------- 指标库 / 拖拽 ---------------- */
function buildMetricLib() {
  document.getElementById("metricLib").innerHTML = METRICS.map(m =>
    `<div class="metric-card" draggable="true" data-id="${m.id}">
       <div class="n">${esc(m.name)}</div><div class="d">${esc(m.desc)}</div>
     </div>`).join("");
  document.querySelectorAll(".metric-card").forEach(el => {
    el.addEventListener("dragstart", e =>
      e.dataTransfer.setData("text/plain", JSON.stringify({ type: "metric", id: el.dataset.id })));
    el.addEventListener("click", () => addMetric(el.dataset.id));
  });
}

function renderZones() {
  document.getElementById("dimZone").innerHTML =
    `维度放置区：<span class="pill">${labelOf("dim", custom.dim)}</span>`;
  document.getElementById("measZone").innerHTML =
    `度量放置区：<span class="pill meas">${labelOf("meas", custom.meas)}</span>`;
}

function pick(type, key) {
  if (type === "dim") custom.dim = key; else custom.meas = key;
  renderZones();
}
function bindChips() {
  document.querySelectorAll(".chip").forEach(ch => {
    ch.addEventListener("dragstart", e =>
      e.dataTransfer.setData("text/plain", JSON.stringify({ type: ch.dataset.type, key: ch.dataset.key })));
    ch.addEventListener("click", () => pick(ch.dataset.type, ch.dataset.key));
  });
}
["dimZone", "measZone"].forEach(id => {
  const el = document.getElementById(id);
  el.addEventListener("dragover", e => { e.preventDefault(); el.classList.add("over"); });
  el.addEventListener("dragleave", () => el.classList.remove("over"));
  el.addEventListener("drop", e => {
    e.preventDefault(); el.classList.remove("over");
    try {
      const p = JSON.parse(e.dataTransfer.getData("text/plain"));
      const want = id === "dimZone" ? "dim" : "meas";
      if (p.type !== want) { toast("维度请拖到维度区、度量请拖到度量区", true); return; }
      pick(p.type, p.key);
    } catch (_) { /* 忽略非法拖拽 */ }
  });
});
document.getElementById("chartTypes").addEventListener("click", e => {
  const btn = e.target.closest("button[data-type]");
  if (!btn) return;
  custom.type = btn.dataset.type;
  document.querySelectorAll("#chartTypes .btn").forEach(b => b.classList.toggle("active", b === btn));
});

/* 画布接收「内置指标」拖拽 */
(function () {
  const drop = document.getElementById("canvasDrop");
  ["dragenter", "dragover"].forEach(ev => drop.addEventListener(ev, e => {
    e.preventDefault(); drop.classList.add("over");
  }));
  ["dragleave", "dragend"].forEach(ev => drop.addEventListener(ev, () => drop.classList.remove("over")));
  drop.addEventListener("drop", e => {
    e.preventDefault(); drop.classList.remove("over");
    try {
      const p = JSON.parse(e.dataTransfer.getData("text/plain"));
      if (p.type === "metric") addMetric(p.id);
      else toast("把左侧「内置指标」拖进来即可生成图表", true);
    } catch (_) { /* 忽略 */ }
  });
})();

/* ---------------- 启动 ---------------- */
async function init() {
  meta = await api("/api/meta");
  const monthOpts = meta.months.map(m => `<option value="${m}">${m}</option>`).join("");
  document.getElementById("fMonths").innerHTML = monthOpts;
  renderYearChips();
  document.getElementById("fCats").innerHTML = meta.categories.map(c => `<option value="${c}">${c}</option>`).join("");
  document.getElementById("dimChips").innerHTML =
    meta.dimensions.map(d => `<span class="chip" draggable="true" data-type="dim" data-key="${d.key}">${d.label}</span>`).join("");
  document.getElementById("measChips").innerHTML =
    meta.measures.map(m => `<span class="chip" draggable="true" data-type="meas" data-key="${m.key}">${m.label}</span>`).join("");
  bindChips();
  buildMetricLib();
  custom.dim = "category"; custom.meas = "total_amount";
  renderZones();
  DEFAULT_CARDS.forEach(addMetric);
}

(async function () {
  try { await init(); }
  catch (e) { toast("初始化失败：" + e.message, true); }
})();
