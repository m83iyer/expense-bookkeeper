const $ = selector => document.querySelector(selector);
const $$ = selector => [...document.querySelectorAll(selector)];
const escapeHtml = value => String(value ?? "").replace(/[&<>"']/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
const locales = {USD:"en-US", INR:"en-IN", GBP:"en-GB", EUR:"de-DE", AED:"en-AE"};
const viewCopy = {
  overview:["Where did spending change?", "Compare selected spending with a complete observed baseline, then trace the difference to ledger rows."],
  drivers:["What caused the movement?", "Move from category to merchant, then inspect the confirmed transactions behind the change."],
  commitments:["What is already committed?", "See the recurring run rate before it becomes another month of recorded spending."],
  ledger:["Which entries support the analysis?", "Every chart and finding resolves to these confirmed ledger rows."],
};
const palette = ["#248789", "#3973b8", "#d59a3b", "#805e9d", "#ca4b2c", "#2d7d5b", "#56738f", "#a65d78"];
const initial = new URLSearchParams(location.search);
const state = {
  view: viewCopy[initial.get("view")] ? initial.get("view") : "overview",
  month: initial.get("month") || "",
  range: initial.get("range") || "3",
  category: initial.get("category") || "",
  subcategory: initial.get("subcategory") || "",
  merchant: initial.get("merchant") || "",
  comparison: initial.get("comparison") || "previous",
  currency: initial.get("currency") || "USD",
  data: null,
  commitments: null,
  selectedDriver: null,
  expandedDrivers: new Set(),
};

function money(value, exact = false) {
  const currency = state.data?.meta?.currency || state.commitments?.currency || state.currency || "USD";
  return new Intl.NumberFormat(locales[currency] || "en-US", {
    style: "currency", currency,
    minimumFractionDigits: exact ? 2 : 0,
    maximumFractionDigits: exact ? 2 : 0,
  }).format(Number(value) || 0);
}

function compactMoney(value) {
  const currency = state.data?.meta?.currency || state.currency || "USD";
  return new Intl.NumberFormat(locales[currency] || "en-US", {
    style: "currency", currency, notation: "compact", maximumFractionDigits: 1,
  }).format(Number(value) || 0);
}

function formatDate(value) {
  if (!value) return "Date unavailable";
  return new Date(`${value}T12:00:00`).toLocaleDateString("en-GB", {day:"2-digit", month:"short", year:"numeric"});
}

function formatSync(value) {
  const parsed = new Date(value);
  if (!value || Number.isNaN(parsed.getTime())) return "Ledger not yet synced";
  return `Updated ${new Intl.DateTimeFormat("en-GB", {
    day:"2-digit", month:"short", year:"numeric", hour:"2-digit", minute:"2-digit",
  }).format(parsed)}`;
}

function syncUrl() {
  const params = new URLSearchParams();
  params.set("view", state.view);
  params.set("currency", state.currency);
  if (state.month) params.set("month", state.month);
  params.set("range", state.range);
  if (state.category) params.set("category", state.category);
  if (state.subcategory) params.set("subcategory", state.subcategory);
  if (state.merchant) params.set("merchant", state.merchant);
  if (state.comparison !== "previous") params.set("comparison", state.comparison);
  history.replaceState(null, "", `${location.pathname}?${params}`);
}

function setView(view) {
  state.view = viewCopy[view] ? view : "overview";
  $$('[data-view-panel]').forEach(panel => {
    const active = panel.dataset.viewPanel === state.view;
    panel.hidden = !active;
    panel.classList.toggle("active", active);
  });
  $$("[data-view]").forEach(button => {
    const active = button.dataset.view === state.view;
    button.classList.toggle("active", active);
    button.setAttribute("aria-current", active ? "page" : "false");
  });
  $("#viewQuestion").textContent = viewCopy[state.view][0];
  $("#viewAnswer").textContent = viewCopy[state.view][1];
  syncUrl();
  const scrollBehavior = window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";
  window.scrollTo({top:0, behavior:scrollBehavior});
}

async function getJSON(url, options) {
  const response = await fetch(url, {cache:"no-store", ...options});
  let payload = {};
  try { payload = await response.json(); } catch { payload = {}; }
  if (!response.ok) throw new Error(payload.message || `Request failed with status ${response.status}.`);
  return payload;
}

function syncOptions(select, values, placeholder, selected) {
  const safeValues = values || [];
  const signature = `${placeholder}|${safeValues.join("|")}`;
  if (select.dataset.signature !== signature) {
    select.innerHTML = `${placeholder ? `<option value="">${escapeHtml(placeholder)}</option>` : ""}${safeValues.map(value => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`).join("")}`;
    select.dataset.signature = signature;
  }
  select.value = selected || "";
}

function selectedValues(value) {
  return new Set(String(value || "").split("|").map(item => item.trim()).filter(Boolean));
}

function syncMultiSlicer(root, values, selected, placeholder, onApply) {
  const safeValues = [...new Set(values || [])];
  const selectedSet = selectedValues(selected);
  const allSelected = selectedSet.size === 0 || safeValues.every(value => selectedSet.has(value));
  const checked = allSelected ? new Set(safeValues) : selectedSet;
  const summary = allSelected
    ? placeholder
    : checked.size === 1
      ? [...checked][0]
      : `${checked.size} selected`;
  root.innerHTML = `
    <span class="slicer-label">${escapeHtml(root.dataset.label || "Filter")}</span>
    <details>
      <summary><b>${escapeHtml(summary)}</b><span aria-hidden="true">⌄</span></summary>
      <div class="slicer-popover">
        <div class="slicer-actions">
          <button type="button" data-slicer-action="all">Select all</button>
          <button type="button" data-slicer-action="clear">Clear all</button>
        </div>
        <div class="slicer-options">
          ${safeValues.map(value => `<label><input type="checkbox" value="${escapeHtml(value)}" ${checked.has(value) ? "checked" : ""}><span>${escapeHtml(value)}</span></label>`).join("") || `<p class="slicer-empty">No choices in this scope</p>`}
        </div>
        <p class="slicer-message" aria-live="polite"></p>
        <button class="slicer-apply" type="button">Apply</button>
      </div>
    </details>`;
  const boxes = [...root.querySelectorAll('input[type="checkbox"]')];
  root.querySelector('[data-slicer-action="all"]').addEventListener("click", () => boxes.forEach(box => { box.checked = true; }));
  root.querySelector('[data-slicer-action="clear"]').addEventListener("click", () => boxes.forEach(box => { box.checked = false; }));
  root.querySelector(".slicer-apply").addEventListener("click", () => {
    const chosen = boxes.filter(box => box.checked).map(box => box.value);
    if (safeValues.length && !chosen.length) {
      root.querySelector(".slicer-message").textContent = "Choose at least one item, or use Select all.";
      return;
    }
    root.querySelector("details").open = false;
    onApply(chosen.length === safeValues.length ? "" : chosen.join("|"));
  });
}

function changeText(change, previous, label) {
  if (change === null || change === undefined) return {text:"Baseline incomplete", className:""};
  const direction = change > 0 ? "higher" : change < 0 ? "lower" : "unchanged";
  return {
    text: `${Math.abs(change).toFixed(1)}% ${direction} than ${label} (${money(previous)})`,
    className: change > 10 ? "attention" : change < 0 ? "positive" : "",
  };
}

function updateFilters(meta) {
  syncOptions($("#monthFilter"), meta.months, "Latest month", meta.selected_month);
  syncMultiSlicer($("#categoryFilter"), meta.categories, meta.category, "All categories",
    value => updateFilter("category", value, ["subcategory", "merchant"]));
  syncMultiSlicer($("#subcategoryFilter"), meta.subcategories, meta.subcategory, "All subcategories",
    value => updateFilter("subcategory", value, ["merchant"]));
  syncMultiSlicer($("#merchantFilter"), meta.merchants, meta.merchant, "All merchants",
    value => updateFilter("merchant", value));
  syncOptions($("#cashCategory"), meta.categories, "Auto-classify", $("#cashCategory").value);
  const cashCategory = $("#cashCategory").value;
  const taxonomy = meta.taxonomy || {};
  syncOptions($("#cashSubcategory"), cashCategory ? (taxonomy[cashCategory] || []) : meta.subcategories,
    "Auto-classify", $("#cashSubcategory").value);
  $("#rangeFilter").value = String(meta.range_months);
  $("#comparisonFilter").value = meta.comparison;
  state.month = meta.selected_month;
  state.category = meta.category;
  state.subcategory = meta.subcategory;
  state.merchant = meta.merchant;
  state.comparison = meta.comparison;
  state.currency = meta.currency;
  renderCurrencyToggle(meta);
}

function renderCurrencyToggle(meta) {
  const all = ["USD", "INR", "GBP", "EUR", "AED"];
  const available = new Set(meta.available_currencies || [meta.base_currency]);
  $("#currencyToggle").innerHTML = all.map(code => `<button type="button" data-currency="${code}" aria-pressed="${code === meta.currency}" ${available.has(code) ? "" : "disabled"}>${code}</button>`).join("");
  $$("#currencyToggle button:not(:disabled)").forEach(button => button.addEventListener("click", () => {
    if (button.dataset.currency === state.currency) return;
    state.currency = button.dataset.currency;
    loadAll();
  }));
  if (meta.fx_mode === "synthetic") {
    $("#fxDisclosure").textContent = `Demo display conversion: synthetic ${meta.base_currency} reference rates.`;
  } else if (meta.fx_as_of) {
    $("#fxDisclosure").textContent = `Display conversion: ${meta.base_currency} to ${meta.currency}, rates dated ${meta.fx_as_of}.`;
  } else {
    $("#fxDisclosure").textContent = `Base currency only. Run dashboard-fx-refresh to enable all five currencies.`;
  }
}

function renderMetrics(data) {
  const {kpis, meta} = data;
  $("#periodLabel").textContent = meta.period_label;
  $("#scopeLabel").textContent = meta.scope_label;
  $("#freshness").textContent = formatSync(meta.last_updated);
  $("#periodSpend").textContent = money(kpis.period.value);
  const periodChange = changeText(kpis.period.change_pct, kpis.period.previous, meta.comparison_label.toLowerCase());
  $("#periodChange").textContent = periodChange.text;
  $("#periodChange").className = periodChange.className;
  $("#monthlyAverage").textContent = money(kpis.monthly_average.value);
  $("#monthlyChange").textContent = `${meta.range_months}-month average; ${money(kpis.monthly_average.previous)} in comparison`;
  $("#transactionCount").textContent = Number(kpis.transactions).toLocaleString();
  $("#dailyAverage").textContent = `${money(kpis.daily_average)} per spending day`;
  $("#yearChange").textContent = kpis.year.change_pct === null ? "No baseline" : `${kpis.year.change_pct >= 0 ? "+" : ""}${kpis.year.change_pct.toFixed(1)}%`;
  $("#yearChange").className = kpis.year.change_pct > 10 ? "attention" : kpis.year.change_pct < 0 ? "positive" : "";
  $("#yearBaseline").textContent = kpis.year.change_pct === null ? "Full prior-year window unavailable" : `${money(kpis.year.previous)} same period last year`;
  $("#cashPanel").hidden = !meta.cash_entry_enabled;
  $("#demoBadge").hidden = !meta.demo_mode;
}

function renderInsights(items) {
  $("#insightBrief").innerHTML = (items || []).map((item, index) => `
    <article class="insight-line ${escapeHtml(item.tone)}">
      <span class="insight-index">${String(index + 1).padStart(2, "0")}</span>
      <div><b>${escapeHtml(item.title)}</b><p>${escapeHtml(item.body)}</p></div>
    </article>`).join("") || `<div class="empty">No finding is available for the selected scope.</div>`;
}

function drawTrend(items) {
  const svg = $("#trendChart");
  if (!items.length) { svg.innerHTML = ""; $("#trendReadout").innerHTML = `<div class="empty">No trend data.</div>`; return; }
  const width = 960, height = 360, left = 74, right = 28, top = 42, bottom = 58;
  const allValues = items.flatMap(item => [item.amount, item.comparison_amount].filter(value => value !== null && value !== undefined));
  const maximum = Math.max(...allValues, 1) * 1.18;
  const x = index => left + index * (width - left - right) / Math.max(1, items.length - 1);
  const y = value => top + (maximum - value) / maximum * (height - top - bottom);
  const line = items.map((item, index) => `${index ? "L" : "M"}${x(index)},${y(item.amount)}`).join(" ");
  const compareParts = [];
  let segment = [];
  items.forEach((item, index) => {
    if (item.comparison_amount === null || item.comparison_amount === undefined) {
      if (segment.length) {
        compareParts.push(segment);
      }
      segment = [];
    } else segment.push({index, value:item.comparison_amount});
  });
  if (segment.length) compareParts.push(segment);
  const compare = compareParts.map(points => `<path d="${points.map((point, index) => `${index ? "L" : "M"}${x(point.index)},${y(point.value)}`).join(" ")}" class="chart-compare"/>`).join("");
  const grid = [0, .25, .5, .75, 1].map(ratio => {
    const gy = top + ratio * (height - top - bottom);
    return `<line x1="${left}" y1="${gy}" x2="${width - right}" y2="${gy}" class="chart-grid"/><text x="${left - 12}" y="${gy + 4}" text-anchor="end" class="chart-axis">${escapeHtml(compactMoney(maximum * (1 - ratio)))}</text>`;
  }).join("");
  const points = items.map((item, index) => {
    const px = x(index), py = y(item.amount);
    const labelY = py < top + 28 ? py + 29 : py - 13;
    return `<g><circle cx="${px}" cy="${py}" r="14" class="chart-hit"><title>${escapeHtml(item.month)}: ${escapeHtml(money(item.amount))}, ${item.transactions} transactions</title></circle><circle cx="${px}" cy="${py}" r="5" class="chart-dot"/><text x="${px}" y="${labelY}" text-anchor="middle" class="chart-value">${escapeHtml(compactMoney(item.amount))}</text></g>`;
  }).join("");
  const labels = items.map((item, index) => `<text x="${x(index)}" y="${height - 23}" text-anchor="middle" class="chart-axis">${escapeHtml(item.month.replace("-", " "))}</text>`).join("");
  svg.innerHTML = `${grid}<path d="${line} L${x(items.length - 1)},${height - bottom} L${left},${height - bottom}Z" class="chart-area"/><path d="${line}" class="chart-line"/>${compare}${points}${labels}`;
  const average = items.reduce((sum, item) => sum + item.amount, 0) / items.length;
  const peak = items.reduce((best, item) => !best || item.amount > best.amount ? item : best, null);
  const changes = items.slice(1).map((item, index) => ({month:item.month, delta:item.amount - items[index].amount}));
  const biggest = changes.reduce((best, item) => !best || Math.abs(item.delta) > Math.abs(best.delta) ? item : best, null);
  $("#trendReadout").innerHTML = `
    <span><small>12-MONTH AVERAGE</small><b>${money(average)}</b></span>
    <span><small>PEAK MONTH</small><b>${escapeHtml(peak.month)} · ${money(peak.amount)}</b></span>
    <span><small>LARGEST MONTHLY MOVE</small><b>${biggest ? `${escapeHtml(biggest.month)} · ${biggest.delta >= 0 ? "+" : ""}${money(biggest.delta)}` : "No movement"}</b></span>`;
}

function renderComposition(nodes) {
  const visible = (nodes || []).filter(node => node.current > 0).slice(0, 7);
  const maximum = Math.max(...visible.map(node => node.current), 1);
  $("#compositionChart").innerHTML = visible.map(node => `
    <div class="composition-row">
      <button type="button" data-driver="${escapeHtml(node.id)}">${escapeHtml(node.name)}</button>
      <strong>${money(node.current)}</strong>
      <div class="composition-track"><i style="width:${Math.max(1, node.current / maximum * 100)}%"></i></div>
      <small>${node.share.toFixed(1)}% of selected spend</small>
    </div>`).join("") || `<div class="empty">No categories in this period.</div>`;
  const namedShare = visible.reduce((sum, node) => sum + node.share, 0);
  $("#compositionNote").textContent = `${visible.length} visible categories reconcile ${namedShare.toFixed(1)}% of selected spend. Open Drivers for the full path.`;
  $$("#compositionChart [data-driver]").forEach(button => button.addEventListener("click", () => {
    state.selectedDriver = button.dataset.driver;
    setView("drivers");
    renderDrivers(state.data);
  }));
}

function allDriverNodes(nodes) {
  return (nodes || []).flatMap(node => [node, ...allDriverNodes(node.children)]);
}

function driverNode(id) {
  return allDriverNodes(state.data?.driver_rows).find(node => node.id === id) || null;
}

function chooseDefaultDriver(data) {
  const candidates = data.driver_rows || [];
  return candidates.reduce((best, node) => !best || Math.abs(node.delta) > Math.abs(best.delta) ? node : best, null);
}

function selectDriver(id) {
  const node = driverNode(id);
  if (!node) return;
  state.selectedDriver = id;
  if (node.children?.length) {
    if (state.expandedDrivers.has(id)) state.expandedDrivers.delete(id); else state.expandedDrivers.add(id);
  }
  renderDrivers(state.data);
}

function renderDrivers(data) {
  const summary = data.driver_summary;
  const selected = driverNode(state.selectedDriver) || chooseDefaultDriver(data);
  if (selected) state.selectedDriver = selected.id;
  $("#driverComparisonLabel").textContent = data.meta.baseline_complete ? data.meta.comparison_label : "Comparison incomplete";
  $("#driverDelta").textContent = `${summary.delta >= 0 ? "+" : ""}${money(summary.delta)}`;
  $("#driverDelta").className = summary.delta > 0 ? "attention" : summary.delta < 0 ? "positive" : "";
  $("#driverDeltaPct").textContent = summary.pct === null ? "No reliable percentage" : `${summary.pct >= 0 ? "+" : ""}${summary.pct.toFixed(1)}% across ${summary.transactions} transactions`;
  renderDeltaChart(data.driver_rows || [], selected);
  renderDriverMap(data.driver_rows || [], selected);
  renderDriverMatrix(data.driver_rows || [], selected);
  renderDriverEvidence(selected, data.transactions || []);
}

function renderDeltaChart(nodes, selected) {
  const visible = [...nodes].sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta)).slice(0, 8);
  const maximum = Math.max(...visible.map(node => Math.abs(node.delta)), 1);
  $("#deltaChart").innerHTML = visible.map(node => {
    const width = Math.max(1, Math.abs(node.delta) / maximum * 100);
    const positive = node.delta >= 0;
    return `<button class="delta-row${selected?.id === node.id ? " selected" : ""}" data-driver="${escapeHtml(node.id)}" type="button">
      <span class="delta-name"><b>${escapeHtml(node.name)}</b><small>${node.transactions} transactions</small></span>
      <span class="delta-bars"><span>${positive ? "" : `<i class="decrease" style="width:${width}%"></i>`}</span><span>${positive ? `<i class="increase" style="width:${width}%"></i>` : ""}</span></span>
      <strong class="${positive ? "attention" : "positive"}">${positive ? "+" : ""}${money(node.delta)}</strong>
    </button>`;
  }).join("") || `<div class="empty">No driver comparison is available.</div>`;
  $$("#deltaChart [data-driver]").forEach(button => button.addEventListener("click", () => selectDriver(button.dataset.driver)));
}

function renderDriverMap(nodes, selected) {
  const visible = nodes.filter(node => node.current > 0).slice(0, 8);
  $("#driverMap").innerHTML = visible.map((node, index) => `
    <button class="driver-tile${selected?.id === node.id ? " selected" : ""}" data-driver="${escapeHtml(node.id)}" type="button" style="--weight:${Math.max(1, Math.round(node.share / 8))};--tile:${palette[index % palette.length]}">
      <b>${escapeHtml(node.name)}</b><strong>${money(node.current)}</strong><small>${node.share.toFixed(1)}% · ${node.transactions} transactions</small>
    </button>`).join("") || `<div class="empty">No current-period footprint.</div>`;
  $$("#driverMap [data-driver]").forEach(button => button.addEventListener("click", () => selectDriver(button.dataset.driver)));
}

function visibleMatrixRows(nodes, depth = 0) {
  const rows = [];
  nodes.forEach(node => {
    rows.push({node, depth});
    if (state.expandedDrivers.has(node.id)) rows.push(...visibleMatrixRows(node.children || [], depth + 1));
  });
  return rows;
}

function renderDriverMatrix(nodes, selected) {
  $("#driverMatrix").innerHTML = visibleMatrixRows(nodes).map(({node, depth}) => `
    <button class="matrix-row${selected?.id === node.id ? " selected" : ""}" data-driver="${escapeHtml(node.id)}" type="button" style="--depth:${depth}">
      <span class="driver-name"><i>${node.children?.length ? state.expandedDrivers.has(node.id) ? "⌄" : "›" : "•"}</i><b>${escapeHtml(node.name)}</b><small>${escapeHtml(node.level)}</small></span>
      <span>${money(node.current)}</span><span>${money(node.previous)}</span>
      <span class="${node.delta > 0 ? "attention" : node.delta < 0 ? "positive" : ""}">${node.delta >= 0 ? "+" : ""}${money(node.delta)}</span>
      <span>${node.share.toFixed(1)}%</span><span>${node.transactions.toLocaleString()}</span>
    </button>`).join("") || `<div class="empty">No driver rows.</div>`;
  $$("#driverMatrix [data-driver]").forEach(button => button.addEventListener("click", () => selectDriver(button.dataset.driver)));
}

function matchesPath(item, path) {
  return (!path[0] || item.category === path[0]) && (!path[1] || item.subcategory === path[1]) && (!path[2] || item.merchant_clean === path[2]);
}

function renderDriverEvidence(selected, transactions) {
  if (!selected) {
    $("#driverEvidenceTitle").textContent = "No driver selected";
    $("#driverEvidence").innerHTML = `<div class="empty">Select a category to reveal evidence.</div>`;
    return;
  }
  const evidence = transactions.filter(item => matchesPath(item, selected.path));
  $("#driverEvidenceTitle").textContent = selected.name;
  $("#driverEvidenceScope").textContent = `${selected.path.join(" → ")} · ${evidence.length} confirmed transactions in the selected period`;
  $("#driverEvidence").innerHTML = evidence.slice(0, 8).map(item => `
    <article class="evidence-row">
      <time>${escapeHtml(formatDate(item.date))}</time>
      <span><b>${escapeHtml(item.merchant_clean)}</b><small>${escapeHtml(item.subcategory)}</small></span>
      <span><b>${escapeHtml(item.card_used || item.source || "Ledger")}</b><small>${escapeHtml(item.notes || "Confirmed expense")}</small></span>
      <strong>${money(item.amount, true)}</strong>
    </article>`).join("") || `<div class="empty">No matching transaction is present in this selected period.</div>`;
}

function renderCommitments(data) {
  state.commitments = data;
  $("#annualCommitment").textContent = money(data.annual_total);
  $("#monthlyCommitment").textContent = `${money(data.monthly_equivalent)} monthly equivalent`;
  const categoryTotals = {};
  (data.commitments || []).forEach(item => { categoryTotals[item.category] = (categoryTotals[item.category] || 0) + item.annual_amount; });
  const categories = Object.entries(categoryTotals).sort((a, b) => b[1] - a[1]);
  const maximum = Math.max(...categories.map(([, value]) => value), 1);
  $("#commitmentChart").innerHTML = categories.map(([name, value]) => `
    <div class="commitment-bar"><b>${escapeHtml(name)}</b><span class="commitment-track"><i style="width:${Math.max(1, value / maximum * 100)}%"></i></span><strong>${money(value)}</strong></div>
  `).join("") || `<div class="empty">No recurring commitments found.</div>`;
  $("#upcomingTimeline").innerHTML = (data.upcoming || []).slice(0, 7).map(item => `
    <article class="timeline-row"><time>${escapeHtml(formatDate(item.due_date))}</time><i class="timeline-dot" aria-hidden="true"></i><span><b>${escapeHtml(item.name)}</b><small>${escapeHtml(item.category)} · ${escapeHtml(item.cadence)}</small></span><strong>${money(item.amount, true)}</strong></article>
  `).join("") || `<div class="empty">No upcoming payments.</div>`;
  $("#commitmentRegister").innerHTML = (data.commitments || []).map(item => `
    <article class="commitment-register-row"><span><b>${escapeHtml(item.name)}</b><small>${escapeHtml(item.cadence)}</small></span><span>${escapeHtml(item.category)} / ${escapeHtml(item.subcategory)}</span><span>${money(item.monthly_amount)}<small>monthly</small></span><span>${money(item.annual_amount)}<small>annual</small></span></article>
  `).join("") || `<div class="empty">No recurring services.</div>`;
}

function renderTransactions(items, query = "") {
  const term = query.trim().toLowerCase();
  const shown = (items || []).filter(item => !term || [item.merchant_clean, item.category, item.subcategory, item.source, item.notes].some(value => String(value || "").toLowerCase().includes(term)));
  $("#transactionTable").innerHTML = shown.map(item => `
    <tr><td>${escapeHtml(formatDate(item.date))}</td><td><b>${escapeHtml(item.merchant_clean)}</b></td><td class="category-path">${escapeHtml(item.category)} → ${escapeHtml(item.subcategory)}</td><td>${escapeHtml(item.card_used || item.source || "Ledger")}</td><td class="number"><b>${money(item.amount, true)}</b></td></tr>
  `).join("");
  $("#mobileTransactions").innerHTML = shown.map(item => `
    <article class="mobile-transaction"><div><b>${escapeHtml(item.merchant_clean)}</b><strong>${money(item.amount, true)}</strong></div><p>${escapeHtml(item.category)} → ${escapeHtml(item.subcategory)}</p><small>${escapeHtml(formatDate(item.date))} · ${escapeHtml(item.card_used || item.source || "Ledger")}</small></article>
  `).join("") || `<div class="empty">No matching transactions.</div>`;
}

function renderEvidenceSummary(data) {
  const merchantTotals = {};
  (data.transactions || []).forEach(item => {
    merchantTotals[item.merchant_clean] = (merchantTotals[item.merchant_clean] || 0) + Number(item.amount || 0);
  });
  const leading = Object.entries(merchantTotals).sort((a, b) => b[1] - a[1])[0] || ["No merchant", 0];
  $("#evidenceSpend").textContent = money(data.kpis.period.value);
  $("#evidenceScopeSummary").textContent = data.meta.scope_label;
  $("#evidenceRows").textContent = Number(data.kpis.transactions).toLocaleString();
  $("#evidenceMerchant").textContent = leading[0];
  $("#evidenceMerchantSpend").textContent = `${money(leading[1])} in selected spending`;
}

function renderAll(data) {
  state.data = data;
  updateFilters(data.meta);
  renderMetrics(data);
  renderInsights(data.insights);
  drawTrend(data.trend || []);
  renderComposition(data.driver_rows || []);
  renderDrivers(data);
  renderEvidenceSummary(data);
  renderTransactions(data.transactions || [], $("#transactionSearch").value);
  $("#trendCaption").textContent = `${data.trend.length} months through ${data.meta.selected_month}; dashed line is ${data.meta.comparison_label.toLowerCase()}.`;
  $("#driverSubtitle").textContent = data.meta.baseline_complete
    ? `${data.meta.period_label} versus ${data.meta.previous_period_label}. Every row resolves to transaction evidence.`
    : `Comparison held back because ${data.meta.missing_baseline_months.join(", ")} is unobserved.`;
  $("#systemStatus").textContent = "Local and private";
  $("#systemDetail").textContent = `${Number(data.kpis.transactions).toLocaleString()} selected transactions`;
  document.body.classList.add("ready");
  syncUrl();
}

async function loadAll() {
  document.body.classList.remove("ready");
  $("#errorState").hidden = true;
  const params = new URLSearchParams({
    month: state.month,
    range: state.range,
    category: state.category,
    subcategory: state.subcategory,
    merchant: state.merchant,
    comparison: state.comparison,
    currency: state.currency,
  });
  try {
    const [analytics, commitments] = await Promise.all([
      getJSON(`/api/analytics?${params}`),
      getJSON(`/api/commitments?currency=${encodeURIComponent(state.currency)}`),
    ]);
    renderAll(analytics);
    renderCommitments(commitments);
  } catch (error) {
    $("#errorState").textContent = error.message;
    $("#errorState").hidden = false;
    $("#systemStatus").textContent = "Data unavailable";
    $("#systemDetail").textContent = "Check dashboard sync";
  } finally {
    document.body.classList.add("ready");
  }
}

function updateFilter(key, value, reset = []) {
  state[key] = value;
  reset.forEach(name => { state[name] = ""; });
  state.selectedDriver = null;
  state.expandedDrivers.clear();
  loadAll();
}

$$("[data-view]").forEach(button => button.addEventListener("click", () => setView(button.dataset.view)));
$("#monthFilter").addEventListener("change", event => updateFilter("month", event.target.value));
$("#rangeFilter").addEventListener("change", event => updateFilter("range", event.target.value));
$("#comparisonFilter").addEventListener("change", event => updateFilter("comparison", event.target.value));
$("#cashCategory").addEventListener("change", event => {
  const taxonomy = state.data?.meta?.taxonomy || {};
  syncOptions($("#cashSubcategory"), event.target.value ? (taxonomy[event.target.value] || []) : (state.data?.meta?.subcategories || []),
    "Auto-classify", "");
});
$("#resetFilters").addEventListener("click", () => {
  Object.assign(state, {month:"", range:"3", category:"", subcategory:"", merchant:"", comparison:"previous", selectedDriver:null});
  state.expandedDrivers.clear();
  loadAll();
});
$("#refreshData").addEventListener("click", loadAll);
$("#clearDriver").addEventListener("click", () => {
  state.selectedDriver = null;
  state.expandedDrivers.clear();
  renderDrivers(state.data);
});
$("#openLedger").addEventListener("click", () => {
  const selected = driverNode(state.selectedDriver);
  $("#transactionSearch").value = selected?.path?.at(-1) || "";
  renderTransactions(state.data?.transactions || [], $("#transactionSearch").value);
  setView("ledger");
});
$("#transactionSearch").addEventListener("input", event => renderTransactions(state.data?.transactions || [], event.target.value));
$("#cashDate").value = new Date().toISOString().slice(0, 10);
$("#cashForm").addEventListener("submit", async event => {
  event.preventDefault();
  const form = event.currentTarget;
  const values = Object.fromEntries(new FormData(form).entries());
  const token = values.token;
  delete values.token;
  const button = form.querySelector("button[type=submit]");
  button.disabled = true;
  $("#cashStatus").textContent = "Writing to the local ledger…";
  try {
    const result = await getJSON("/api/cash", {method:"POST", headers:{"Content-Type":"application/json", "X-Expense-Write-Token":token}, body:JSON.stringify(values)});
    $("#cashStatus").textContent = result.review ? "Added to the review queue; no category was guessed." : "Expense added to the ledger.";
    form.reset();
    $("#cashDate").value = new Date().toISOString().slice(0, 10);
  } catch (error) {
    $("#cashStatus").textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

setView(state.view);
loadAll();
