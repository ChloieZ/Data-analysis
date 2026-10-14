/* 三个页面共用的工具函数 */

async function api(path, opts) {
  const res = await fetch(path, opts);
  if (!res.ok) {
    const e = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(e.detail || ("HTTP " + res.status));
  }
  return res.json();
}
const postJSON = (path, body) => api(path, {
  method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
});

/* 数字格式化 */
const fm = n => (n == null ? "-" : Number(n).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
const fi = n => (n == null ? "-" : Number(n).toLocaleString("zh-CN"));
const pct = v => (v == null ? "-" : (v > 0 ? "+" : "") + v + "%");
const bytes = n => (n == null ? "-" : n < 1024 ? n + " B" : n < 1048576 ? (n / 1024).toFixed(1) + " KB" : (n / 1048576).toFixed(1) + " MB");
const esc = s => String(s == null ? "" : s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

/* 提示条 */
function toast(msg, isErr) {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.className = "toast" + (isErr ? " err" : "");
  t.style.display = "block";
  clearTimeout(t._t);
  t._t = setTimeout(() => (t.style.display = "none"), isErr ? 6000 : 3600);
}

/* 通用：把 {columns, rows} 渲染成表格 */
function renderTable(columns, rows, opts = {}) {
  if (!rows || !rows.length) return `<div class="empty">没有数据</div>`;
  const head = columns.map(c => `<th>${esc(c)}</th>`).join("");
  const body = rows.map(r => "<tr>" + r.map(v =>
    `<td class="${String(v).length > 40 ? "wrap-cell" : ""}">${esc(v)}</td>`).join("") + "</tr>").join("");
  return `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>` +
         (opts.note ? `<div class="muted" style="margin-top:8px">${opts.note}</div>` : "");
}

const selectedValues = sel => Array.from(sel.selectedOptions).map(o => o.value);
