"use strict";

const form = document.querySelector("#simulation-form");
const runButton = document.querySelector("#run-button");
const monteCarloButton = document.querySelector("#run-monte-carlo");
const emptyState = document.querySelector("#empty-state");
const resultView = document.querySelector("#result-view");
const monteCarloView = document.querySelector("#mc-result");
const errorMessage = document.querySelector("#error-message");
let latestCounts = null;
let latestMonteCarlo = null;

const stateNames = {
  S0: "No detectada",
  S1: "Rastreada",
  S2: "Evaluada",
  S3: "Enganchada",
  S4: "Neutralizada",
  S5: "Impacto",
  S6: "Inocua",
};

const metricDefinitions = [
  ["spawned", "Amenazas", "integer"],
  ["detected", "Detecciones", "integer"],
  ["neutralized", "Neutralizadas", "integer"],
  ["impacts", "Impactos", "integer"],
  ["harmless", "Inocuas", "integer"],
  ["throughput_per_s", "Throughput / s", "decimal"],
  ["average_wait_time_s", "Espera media (s)", "decimal"],
  ["max_fire_queue", "Cola máxima", "integer"],
];

function readPayload() {
  const payload = {};
  const integerFields = new Set([
    "seed",
    "threat_count",
    "tracking_capacity",
    "interceptor_count",
  ]);
  for (const [name, value] of new FormData(form).entries()) {
    if (value === "") continue;
    if (name === "mode") {
      payload[name] = value;
    } else {
      payload[name] = integerFields.has(name) ? Number.parseInt(value, 10) : Number(value);
    }
  }
  return payload;
}

function formatNumber(value, digits = 2) {
  return new Intl.NumberFormat("es-ES", {
    maximumFractionDigits: digits,
  }).format(value);
}

function addMetric(container, label, value, accent = false) {
  const card = document.createElement("article");
  card.className = "metric-card";
  const title = document.createElement("span");
  title.className = "metric-label";
  title.textContent = label;
  const number = document.createElement("strong");
  number.className = accent ? "metric-value accent" : "metric-value";
  number.textContent = value;
  card.append(title, number);
  container.append(card);
}

function renderMetrics(result) {
  const container = document.querySelector("#metrics");
  container.replaceChildren();
  for (const [key, label, type] of metricDefinitions) {
    const raw = key === "throughput_per_s" || key === "average_wait_time_s"
      ? result[key]
      : result.counts[key];
    const value = type === "integer" ? formatNumber(raw, 0) : formatNumber(raw, 3);
    addMetric(container, label, value, key === "neutralized");
  }
  addMetric(
    container,
    "Interceptores restantes",
    formatNumber(result.counts.interceptors_remaining, 0),
  );
  addMetric(
    container,
    "Duración real (s)",
    formatNumber(result.simulation_time_s, 2),
  );
}

function renderEnvironment(environment) {
  const rows = [
    ["Viento", `${formatNumber(environment.wind_speed_mps)} m/s`],
    ["Dirección", `${formatNumber(environment.wind_direction_rad, 3)} rad`],
    ["Oleaje", `${formatNumber(environment.wave_height_m)} m`],
    ["Densidad del aire", `${formatNumber(environment.air_density_kg_m3, 3)} kg/m³`],
    ["Cabeceo del buque", `${formatNumber(environment.ship_pitch_rad, 3)} rad`],
  ];
  const list = document.querySelector("#environment");
  list.replaceChildren();
  for (const [label, value] of rows) {
    const term = document.createElement("dt");
    const description = document.createElement("dd");
    term.textContent = label;
    description.textContent = value;
    list.append(term, description);
  }
}

function renderThreats(threats) {
  const body = document.querySelector("#threat-rows");
  body.replaceChildren();
  document.querySelector("#table-count").textContent = `${threats.length} registros`;
  for (const threat of threats) {
    const row = document.createElement("tr");
    const impact = threat.impact_point_m
      ? threat.impact_point_m.map((value) => formatNumber(value, 0)).join(", ")
      : "—";
    const cells = [
      `A-${String(threat.id).padStart(2, "0")}`,
      threat.profile === "sea_skimming" ? "Rasante" : "Balístico",
      stateNames[threat.state] ?? threat.state,
      `${formatNumber(threat.position_m[2], 0)} m`,
      impact,
    ];
    for (const [index, value] of cells.entries()) {
      const cell = document.createElement("td");
      if (index === 2) {
        const badge = document.createElement("span");
        badge.className = `state-badge state-${threat.state}`;
        badge.textContent = `${threat.state} · ${value}`;
        cell.append(badge);
      } else {
        cell.textContent = value;
      }
      row.append(cell);
    }
    body.append(row);
  }
}

function drawOutcomes(counts) {
  const canvas = document.querySelector("#outcome-chart");
  const context = canvas.getContext("2d");
  const ratio = window.devicePixelRatio || 1;
  const bounds = canvas.getBoundingClientRect();
  canvas.width = Math.max(1, Math.floor(bounds.width * ratio));
  canvas.height = Math.max(1, Math.floor(bounds.height * ratio));
  context.scale(ratio, ratio);

  const values = [
    { label: "Neutralizadas", value: counts.neutralized, color: "#77e0bd" },
    { label: "Impactos", value: counts.impacts, color: "#ff8585" },
    { label: "Inocuas", value: counts.harmless, color: "#74a8ff" },
  ];
  const total = Math.max(1, ...values.map((entry) => entry.value));
  const left = 96;
  const right = Math.max(left + 30, bounds.width - 39);
  const barHeight = 17;
  const rows = [17, 56, 95];
  context.font = "10px DM Sans, sans-serif";
  context.textBaseline = "middle";

  for (const [index, entry] of values.entries()) {
    const y = rows[index];
    context.fillStyle = "#91a1af";
    context.textAlign = "right";
    context.fillText(entry.label, left - 12, y + barHeight / 2);
    context.fillStyle = "#253543";
    context.fillRect(left, y, right - left, barHeight);
    const width = (right - left) * (entry.value / total);
    context.fillStyle = entry.color;
    context.fillRect(left, y, width, barHeight);
    context.fillStyle = "#edf3f7";
    context.textAlign = "left";
    context.fillText(String(entry.value), Math.min(right + 8, left + width + 8), y + barHeight / 2);
  }
}

function renderResult(result) {
  emptyState.hidden = true;
  resultView.hidden = false;
  monteCarloView.hidden = true;
  latestMonteCarlo = null;
  latestCounts = result.counts;
  document.querySelector("#run-meta").textContent =
    `${result.mode.toUpperCase()} · semilla ${result.seed}`;
  renderMetrics(result);
  renderEnvironment(result.environment);
  renderThreats(result.threats);
  drawOutcomes(result.counts);
}

function drawMonteCarloChart(groups) {
  const canvas = document.querySelector("#mc-chart");
  const context = canvas.getContext("2d");
  const ratio = window.devicePixelRatio || 1;
  const bounds = canvas.getBoundingClientRect();
  canvas.width = Math.max(1, Math.floor(bounds.width * ratio));
  canvas.height = Math.max(1, Math.floor(bounds.height * ratio));
  context.scale(ratio, ratio);

  const width = bounds.width;
  const height = bounds.height;
  const plot = { left: 58, right: width - 18, top: 20, bottom: height - 46 };
  const plotHeight = plot.bottom - plot.top;
  const yForRate = (rate) => plot.bottom - rate * plotHeight;
  context.font = "10px DM Sans, sans-serif";
  context.textBaseline = "middle";

  for (let tick = 0; tick <= 4; tick += 1) {
    const rate = tick / 4;
    const y = yForRate(rate);
    context.strokeStyle = "#2a3a49";
    context.lineWidth = 1;
    context.beginPath();
    context.moveTo(plot.left, y);
    context.lineTo(plot.right, y);
    context.stroke();
    context.fillStyle = "#91a1af";
    context.textAlign = "right";
    context.fillText(`${tick * 25}%`, plot.left - 10, y);
  }

  const groupWidth = (plot.right - plot.left) / groups.length;
  const barWidth = Math.min(42, groupWidth * 0.38);
  const colors = ["#77e0bd", "#74a8ff", "#ffbd69"];
  for (const [index, group] of groups.entries()) {
    const centerX = plot.left + groupWidth * (index + 0.5);
    const rate = group.survival_rate;
    const low = group.confidence_interval_95.lower;
    const high = group.confidence_interval_95.upper;
    const rateY = yForRate(rate);
    const lowY = yForRate(low);
    const highY = yForRate(high);

    context.fillStyle = colors[index];
    context.fillRect(centerX - barWidth / 2, rateY, barWidth, plot.bottom - rateY);
    context.strokeStyle = "#edf3f7";
    context.lineWidth = 2;
    context.beginPath();
    context.moveTo(centerX, highY);
    context.lineTo(centerX, lowY);
    context.moveTo(centerX - 7, highY);
    context.lineTo(centerX + 7, highY);
    context.moveTo(centerX - 7, lowY);
    context.lineTo(centerX + 7, lowY);
    context.stroke();

    context.fillStyle = "#edf3f7";
    context.textAlign = "center";
    context.fillText(`${formatNumber(rate * 100, 1)}%`, centerX, Math.max(10, rateY - 10));
    context.fillStyle = "#c4d0d9";
    context.fillText(`${group.threat_count} amenazas`, centerX, height - 27);
    context.fillStyle = "#91a1af";
    context.fillText(`N=${group.runs}`, centerX, height - 10);
  }
}

function renderMonteCarlo(result) {
  emptyState.hidden = true;
  resultView.hidden = true;
  monteCarloView.hidden = false;
  latestCounts = null;
  latestMonteCarlo = result.groups;
  document.querySelector("#mc-run-meta").textContent =
    `${result.mode.toUpperCase()} · semilla base ${result.base_seed} · horizonte ${formatNumber(result.duration_s)} s`;
  document.querySelector("#mc-total-runs").textContent =
    `${formatNumber(result.total_runs, 0)} corridas totales`;

  const rows = document.querySelector("#mc-rows");
  rows.replaceChildren();
  for (const group of result.groups) {
    const row = document.createElement("tr");
    const interval = group.confidence_interval_95_percent;
    const values = [
      group.threat_count,
      `${group.surviving_runs} / ${group.runs}`,
      `${formatNumber(group.survival_rate_percent, 1)}%`,
      `${formatNumber(interval.lower, 1)}% – ${formatNumber(interval.upper, 1)}%`,
      group.runs_with_impacts,
      group.total_impacts,
    ];
    for (const value of values) {
      const cell = document.createElement("td");
      cell.textContent = String(value);
      row.append(cell);
    }
    rows.append(row);
  }
  drawMonteCarloChart(result.groups);
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!form.reportValidity()) return;
  errorMessage.hidden = true;
  runButton.disabled = true;
  monteCarloButton.disabled = true;
  runButton.firstElementChild.textContent = "Simulando…";
  try {
    const response = await fetch("/api/simulate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(readPayload()),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error ?? "No se pudo ejecutar la simulación.");
    renderResult(result);
  } catch (error) {
    errorMessage.textContent = error instanceof Error ? error.message : "Error inesperado.";
    errorMessage.hidden = false;
  } finally {
    runButton.disabled = false;
    monteCarloButton.disabled = false;
    runButton.firstElementChild.textContent = "Ejecutar simulación";
  }
});

monteCarloButton.addEventListener("click", async () => {
  const runsInput = document.querySelector("#mc-runs");
  if (!form.reportValidity() || !runsInput.reportValidity()) return;
  errorMessage.hidden = true;
  runButton.disabled = true;
  monteCarloButton.disabled = true;
  const runs = Number.parseInt(runsInput.value, 10);
  monteCarloButton.textContent = `Ejecutando ${formatNumber(runs * 3, 0)} corridas…`;
  try {
    const payload = readPayload();
    payload.mode = "est";
    payload.runs = runs;
    const response = await fetch("/api/monte-carlo", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error ?? "No se pudo ejecutar Monte Carlo.");
    renderMonteCarlo(result);
  } catch (error) {
    errorMessage.textContent = error instanceof Error ? error.message : "Error inesperado.";
    errorMessage.hidden = false;
  } finally {
    runButton.disabled = false;
    monteCarloButton.disabled = false;
    monteCarloButton.textContent = "Ejecutar Monte Carlo";
  }
});

window.addEventListener("resize", () => {
  if (!resultView.hidden && latestCounts) drawOutcomes(latestCounts);
  if (!monteCarloView.hidden && latestMonteCarlo) {
    drawMonteCarloChart(latestMonteCarlo);
  }
});
