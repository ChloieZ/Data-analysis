/* 数据大屏 */
const state = { dimension: "category", measure: "total_amount", chartType: "table" };
let metaData = null, chart = null;

const labelOf = (type, key) => {
  const list = type === "dim" ? metaData.dimensions : metaData.measures;
  const hit = list.find(x => x.key === key);
  return hit ? hit.label : key;
};

async function loadMeta() {
  metaData = await api("/api/meta");
  document.getElementById("dimChips").innerHTML = metaData.dimensions
    .map(d => `<span class="chip" draggable="true" data-type="dim" data-key="${d.key}">${d.label}</span>`).join("");
  document.getElementById("measChips").innerHTML = metaData.measures
    .map(m => `<span class="chip" draggable="true" data-type="meas" data-key="${m.key}">${m.label}</span>`).join("");
  bindChips();

  const monthOpts = metaData.months.map(m => `<option value="${m}">${m}</option>`).join("");
  const catOpts = metaData.categories.map(c => `<option value="${c}">${c}</option>`).join("");
  const monthSel = document.getElementById("monthSel");
  monthSel.innerHTML = monthOpts;
  if (metaData.months.length) monthSel.value = metaData.months[metaData.months.length - 1];
  document.getElementById("fMonths").innerHTML = monthOpts;
  document.getElementById("fCats").innerHTML = catOpts;
  document.getElementById("dMonths").innerHTML = monthOpts;
  document.getElementById("dCats").innerHTML = catOpts;
  renderZones();
}

function bindChips() {
  document.querySelectorAll(".chip").forEach(ch => {
    ch.addEventListener("dragstart", e =>
      e.dataTransfer.setData("text/plain", JSON.stringify({ type: ch.dataset.type, key: ch.dataset.key })));
    ch.addEventListener("click", () => selectItem(ch.dataset.type, ch.dataset.key));
  });
}
function selectItem(type, key) {
  if (type === "dim") state.dimension = key; else state.measure = key;
  renderZones();
}
function renderZones() {
  document.getElementById("dimZone").innerHTML =
    `维度放置区：<span class="pill">${labelOf("dim", state.dimension)}</span>`;
  document.getElementById("measZone").innerHTML =
    `度量放置区：<span class="pill meas">${labelOf("meas", state.measure)}</span>`;
}
["dimZone", "measZone"].forEach(id => {
  const el = document.getElementById(id);
  el.addEventListener("dragover", e => { e.preventDefault(); el.classList.add("over"); });
  el.addEventListener("dragleave", () => el.classList.remove("over"));
  el.addEventListener("drop", e => {
    e.preventDefault(); el.classList.remove("over");
    try {
      const data = JSON.parse(e.dataTransfer.getData("text/plain"));
      const expect = id === "dimZone" ? "dim" : "meas";
      if (data.type !== expect) { toast("维度拖到维度区、度量拖到度量区", true); return; }
      selectItem(data.type, data.key);
      runQuery();
    } catch (_) { /* 忽略非法拖拽 */ }
  });
});
document.getElementById("chartTypes").addEventListener("click", e => {
  const btn = e.target.closest("button[data-type]");
  if (!btn) return;
  state.chartType = btn.dataset.type;
  document.querySelectorAll("#chartTypes .btn").forEach(b => b.classList.toggle("active", b === btn));
  runQuery();
});

/* ---------- 看板 ---------- */
async function loadDashboard(month) {
  month = month || document.getElementById("monthSel").value;
  const d = await api("/api/dashboard" + (month ? `?month=${encodeURIComponent(month)}` : ""));
  renderCards(d); renderPie(d); renderTrend(d); renderMom(d);
  if (d.month) document.getElementById("monthSel").value = d.month;
}
function renderCards(d) {
  const box = document.getElementById("cards");
  if (d.empty) {
    box.innerHTML = `<div class="card"><div class="label">暂无数据</div>
      <div class="value">请先导入</div>
      <div class="muted" style="font-size:12px;margin-top:6px">到「源数据」页上传花销表</div></div>`;
    return;
  }
  const c = d.cards, mom = c.mom, cls = mom && mom.delta > 0 ? "up" : "down";
  box.innerHTML = `
    <div class="card"><div class="label">月总支出 · ${c.month}</div><div class="value">¥${fm(c.monthly_total)}</div></div>
    <div class="card"><div class="label">有效笔数</div><div class="value">${fi(c.order_count)} <small>笔</small></div></div>
    <div class="card"><div class="label">笔均支出</div><div class="value">¥${fm(c.avg_per_order)}</div></div>
    <div class="card"><div class="label">环比变化 (较 ${mom ? mom.prev_month : "-"})</div>
      <div class="value ${cls}">${mom ? (mom.delta > 0 ? "▲" : "▼") + "¥" + fm(Math.abs(mom.delta)) : "-"}</div>
      <div class="muted" style="font-size:12px;margin-top:4px">${mom ? pct(mom.pct) : ""}</div></div>
    <div class="card"><div class="label">涉及类别</div><div class="value">${c.category_count} <small>类</small></div></div>`;
}
function renderPie(d) {
  document.getElementById("pieMonthTag").textContent = d.month || "";
  const box = document.getElementById("pieBox");
  if (!d.category_share || !d.category_share.length) { box.innerHTML = `<div class="empty">暂无数据</div>`; return; }
  echarts.init(box).setOption({
    tooltip: { trigger: "item", formatter: p => `${p.name}<br/>¥${fm(p.value)} (${p.percent}%)` },
    legend: { bottom: 0, type: "scroll", textStyle: { color: "#8b98ad" } },
    series: [{ type: "pie", radius: ["40%", "64%"], center: ["50%", "44%"],
      itemStyle: { borderColor: "#171e2e", borderWidth: 2 },
      label: { color: "#e6ebf5", formatter: "{b}\n{d}%" },
      data: d.category_share.map(r => ({ name: r.category, value: r.total_amount })) }],
  });
}
function renderTrend(d) {
  echarts.init(document.getElementById("trendBox")).setOption({
    tooltip: { trigger: "axis", formatter: p => `${p[0].axisValue}<br/>¥${fm(p[0].value)}` },
    grid: { left: 66, right: 20, top: 20, bottom: 30 },
    xAxis: { type: "category", data: d.trend.map(r => r.month), axisLine: { lineStyle: { color: "#2a3446" } }, axisLabel: { color: "#8b98ad" } },
    yAxis: { type: "value", splitLine: { lineStyle: { color: "#232c3c" } }, axisLabel: { color: "#8b98ad" } },
    series: [{ type: "line", smooth: true, symbolSize: 7, data: d.trend.map(r => r.total_amount),
      lineStyle: { color: "#4f8cff", width: 3 }, itemStyle: { color: "#4f8cff" },
      areaStyle: { color: { type: "linear", x: 0, y: 0, x2: 0, y2: 1,
        colorStops: [{ offset: 0, color: "rgba(79,140,255,.35)" }, { offset: 1, color: "rgba(79,140,255,0)" }] } } }],
  });
}
function renderMom(d) {
  const box = document.getElementById("momBox");
  document.getElementById("momTag").textContent = d.category_mom ? `${d.category_mom.month} vs ${d.category_mom.prev_month}` : "";
  if (!d.category_mom) { box.innerHTML = ""; return; }
  const rows = d.category_mom.rows.map(r => {
    const cls = r.delta > 0 ? "up" : (r.delta < 0 ? "down" : "");
    return `<tr><td>${esc(r.category)}</td><td>¥${fm(r.prev_amount)}</td><td>¥${fm(r.current_amount)}</td>
      <td class="${cls}">${r.delta > 0 ? "+" : ""}${fm(r.delta)}</td>
      <td class="${cls}">${pct(r.pct)}</td></tr>`;
  }).join("");
  box.innerHTML = `<table><thead><tr><th>类别</th><th>上月</th><th>本月</th><th>变化额</th><th>变化率</th></tr></thead><tbody>${rows}</tbody></table>`;
}

/* ---------- 自助分析 ---------- */
async function runQuery() {
  const body = {
    dimension: state.dimension, measure: state.measure,
    months: selectedValues(document.getElementById("fMonths")) || null,
    categories: selectedValues(document.getElementById("fCats")) || null,
    note: document.getElementById("fNote").value.trim() || null,
    min_amount: document.getElementById("fMin").value === "" ? null : Number(document.getElementById("fMin").value),
  };
  const data = await postJSON("/api/chart", body);
  const chartBox = document.getElementById("chartBox"), tableBox = document.getElementById("tableBox");

  if (state.chartType === "table") {
    chartBox.style.display = "none"; tableBox.style.display = "block";
    tableBox.innerHTML = renderTable([data.dimension_label, data.measure_label],
      data.rows.map(r => [r.dimension, fm(r.measure)]), { note: `合计：${fm(data.total)} ${data.unit}` });
    return;
  }
  tableBox.style.display = "none"; chartBox.style.display = "block";
  if (chart) chart.dispose();
  chart = echarts.init(chartBox);
  const names = data.rows.map(r => r.dimension), vals = data.rows.map(r => r.measure);
  const base = { tooltip: { trigger: state.chartType === "pie" ? "item" : "axis" },
    grid: { left: 66, right: 24, top: 24, bottom: 44 },
    color: ["#4f8cff", "#22c3a6", "#ffb84d", "#ff6b6b", "#a97bff", "#3ad0ff", "#f7d94c", "#7bff9e"] };
  let opt;
  if (state.chartType === "pie") {
    opt = { ...base, tooltip: { trigger: "item", formatter: p => `${p.name}<br/>${fm(p.value)} (${p.percent}%)` },
      legend: { bottom: 0, type: "scroll", textStyle: { color: "#8b98ad" } },
      series: [{ type: "pie", radius: ["40%", "64%"], center: ["50%", "46%"],
        itemStyle: { borderColor: "#171e2e", borderWidth: 2 }, label: { color: "#e6ebf5", formatter: "{b}\n{d}%" },
        data: data.rows.map(r => ({ name: r.dimension, value: r.measure })) }] };
  } else {
    opt = { ...base,
      xAxis: { type: "category", data: names, axisLine: { lineStyle: { color: "#2a3446" } },
        axisLabel: { color: "#8b98ad", interval: 0, rotate: names.length > 6 ? 25 : 0 } },
      yAxis: { type: "value", splitLine: { lineStyle: { color: "#232c3c" } }, axisLabel: { color: "#8b98ad" } },
      series: [{ type: state.chartType === "line" ? "line" : "bar", data: vals, smooth: true,
        itemStyle: { color: "#4f8cff", borderRadius: [6, 6, 0, 0] }, lineStyle: { color: "#4f8cff", width: 3 },
        areaStyle: state.chartType === "line" ? { opacity: .18 } : undefined }] };
  }
  chart.setOption(opt);
}

/* ---------- 明细 ---------- */
async function runDetail() {
  const data = await postJSON("/api/detail", {
    months: selectedValues(document.getElementById("dMonths")) || null,
    categories: selectedValues(document.getElementById("dCats")) || null,
    min_amount: document.getElementById("dMin").value === "" ? null : Number(document.getElementById("dMin").value),
    limit: 300,
  });
  document.getElementById("detailBox").innerHTML =
    `<div class="muted" style="margin-bottom:8px">共 ${data.count} 条</div>` +
    renderTable(["日期", "月份", "类别", "金额", "备注"],
      data.rows.map(r => [r.spend_date, r.month, r.category, "¥" + fm(r.amount), r.note]));
}

async function loadAll() {
  try { await loadDashboard(); await runQuery(); await runDetail(); }
  catch (e) { toast("加载失败：" + e.message, true); }
}

(async function () {
  try {
    await loadMeta();
    document.querySelector('#chartTypes .btn[data-type="table"]').classList.add("active");
    await loadAll();
  } catch (e) { toast("初始化失败：" + e.message, true); }
})();
