/** Batch Report page: manual entry, Excel import/export, and report rendering. */

import { downloadBlob, filenameFromResponse, postJson, responseError } from "../lib/api.js";
import {
  buildRequestPayload,
  createBlankLine,
  isSupportedWorkbook,
  mergeUploadedLines,
  openWorkbookPicker,
  reportHasDuplicateWarnings,
  suggestionListForField,
} from "./model.js";

const XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";

const state = {
  meta: null,
  year: 2026,
  lines: [createBlankLine(1)],
  report: null,
  importIssues: [],
  busy: false,
};

const elements = {
  yearButtons: document.querySelector("#batch-year-buttons"),
  inputCard: document.querySelector("#batch-input-card"),
  inputRows: document.querySelector("#batch-input-rows"),
  fileInput: document.querySelector("#batch-file-input"),
  uploadWorkbook: document.querySelector("#upload-workbook"),
  codeOptions: document.querySelector("#batch-code-options"),
  countryOptions: document.querySelector("#batch-country-options"),
  status: document.querySelector("#batch-status"),
  issues: document.querySelector("#batch-issues"),
  duplicateWarning: document.querySelector("#duplicate-warning"),
  results: document.querySelector("#batch-results"),
  resultsBody: document.querySelector("#batch-results-body"),
  resultsEmpty: document.querySelector("#results-empty"),
  reportSummary: document.querySelector("#report-summary"),
  addRow: document.querySelector("#add-row"),
  downloadTemplate: document.querySelector("#download-template"),
  generateReport: document.querySelector("#generate-report"),
  exportReport: document.querySelector("#export-report"),
  reportSection: document.querySelector("#report-section"),
};

/* ---------- formatting ---------- */

const formatNumber = (value, maximumFractionDigits = 4) =>
  new Intl.NumberFormat("en-IE", {
    minimumFractionDigits: 0,
    maximumFractionDigits,
  }).format(Number(value));

const formatEmissions = (value) =>
  value === null || value === undefined ? "—" : `${Number(value).toFixed(4)} tCO₂`;

const formatMoney = (value) =>
  value === null || value === undefined
    ? "—"
    : new Intl.NumberFormat("en-IE", {
        style: "currency",
        currency: "EUR",
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      }).format(Number(value));

/* ---------- status and busy state ---------- */

function setStatus(message = "", tone = "") {
  elements.status.textContent = message;
  elements.status.className = `status-region${tone ? ` ${tone}` : ""}`;
}

function setBusy(busy, message = "") {
  state.busy = busy;
  if (message) setStatus(message);
  for (const control of document.querySelectorAll("button, input")) {
    if (control === elements.exportReport && !state.report) continue;
    control.disabled = busy;
  }
  elements.exportReport.disabled = busy || !state.report;
}

function invalidateReport() {
  state.report = null;
  elements.exportReport.disabled = true;
}

/* ---------- input table ---------- */

function makeInput(line, index, field, label, options = {}) {
  const input = document.createElement("input");
  input.className = "input-control";
  input.value = line[field] ?? "";
  input.dataset.index = String(index);
  input.dataset.field = field;
  input.setAttribute("aria-label", `${label}, line ${index + 1}`);
  input.autocomplete = "off";
  if (options.list) input.setAttribute("list", options.list);
  if (options.type) input.type = options.type;
  if (options.min !== undefined) input.min = String(options.min);
  if (options.step) input.step = options.step;
  if (options.placeholder) input.placeholder = options.placeholder;
  if (line.issue) input.setAttribute("aria-invalid", "true");
  return input;
}

function appendCell(row, child) {
  const cell = document.createElement("td");
  cell.append(child);
  row.append(cell);
}

function renderRows() {
  const fragment = document.createDocumentFragment();
  state.lines.forEach((line, index) => {
    const row = document.createElement("tr");
    appendCell(
      row,
      makeInput(line, index, "cnCode", "CN code", {
        list: suggestionListForField("cnCode", line.cnCode),
      }),
    );
    appendCell(
      row,
      makeInput(line, index, "country", "Country", {
        list: suggestionListForField("country", line.country),
      }),
    );
    appendCell(
      row,
      makeInput(line, index, "weightTonnes", "Weight in tonnes", {
        type: "number",
        min: 0.000001,
        step: "any",
        placeholder: "1.00",
      }),
    );
    appendCell(
      row,
      makeInput(line, index, "co2Price", "CO2 price", {
        type: "number",
        min: 0,
        step: "any",
        placeholder: "Optional",
      }),
    );
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "remove-row";
    remove.dataset.removeIndex = String(index);
    remove.setAttribute("aria-label", `Remove input line ${index + 1}`);
    remove.textContent = "×";
    appendCell(row, remove);
    fragment.append(row);

    if (line.issue) {
      const issueRow = document.createElement("tr");
      const issueCell = document.createElement("td");
      issueCell.colSpan = 5;
      const issue = document.createElement("p");
      issue.className = "row-issue";
      issue.textContent = `Line ${index + 1}: ${line.issue}`;
      issueCell.append(issue);
      issueRow.append(issueCell);
      fragment.append(issueRow);
    }
  });
  elements.inputRows.replaceChildren(fragment);
  for (const control of elements.inputRows.querySelectorAll("input, button")) {
    control.disabled = state.busy;
  }
}

function renderYearButtons() {
  const fragment = document.createDocumentFragment();
  for (const year of state.meta?.years ?? [2026, 2027]) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `batch-year-button${year === state.year ? " active" : ""}`;
    button.dataset.year = String(year);
    button.setAttribute("aria-pressed", String(year === state.year));
    button.textContent = String(year);
    button.disabled = state.busy;
    fragment.append(button);
  }
  elements.yearButtons.replaceChildren(fragment);
}

function renderOptions(target, values) {
  const fragment = document.createDocumentFragment();
  for (const value of values) {
    const option = document.createElement("option");
    option.value = String(value);
    fragment.append(option);
  }
  target.replaceChildren(fragment);
}

/* ---------- report rendering ---------- */

function renderIssues(issues, title = "Some lines need attention") {
  elements.issues.replaceChildren();
  if (!issues?.length) {
    elements.issues.classList.add("hidden");
    return;
  }
  const heading = document.createElement("strong");
  heading.textContent = title;
  const list = document.createElement("ul");
  list.className = "issues-list";
  for (const issue of issues) {
    const item = document.createElement("li");
    item.textContent = `Line ${issue.inputLine}: ${issue.error}`;
    list.append(item);
  }
  elements.issues.append(heading, list);
  elements.issues.classList.remove("hidden");
}

function showEmpty(message, detail) {
  elements.resultsEmpty.querySelector("h3").textContent = message;
  elements.resultsEmpty.querySelector("p").textContent = detail;
  elements.resultsEmpty.classList.remove("hidden");
  elements.results.classList.add("hidden");
}

function resultCell(row, value, className = "") {
  const cell = document.createElement("td");
  cell.textContent = value;
  if (className) cell.className = className;
  row.append(cell);
}

function renderSummary(results, year) {
  const uniqueLines = new Set(results.map((item) => item.inputLine)).size;
  const summary = [
    ["Stored records", formatNumber(results.length, 0)],
    ["Matched input lines", formatNumber(uniqueLines, 0)],
    ["Reporting year", String(year)],
  ];
  const fragment = document.createDocumentFragment();
  for (const [label, value] of summary) {
    const card = document.createElement("div");
    card.className = "summary-item";
    const labelElement = document.createElement("span");
    labelElement.className = "summary-label";
    labelElement.textContent = label;
    const valueElement = document.createElement("span");
    valueElement.className = "summary-value";
    valueElement.textContent = value;
    card.append(labelElement, valueElement);
    fragment.append(card);
  }
  elements.reportSummary.replaceChildren(fragment);
  elements.reportSummary.classList.remove("hidden");
}

function renderReport(report) {
  const hasDuplicates = reportHasDuplicateWarnings(report);
  elements.duplicateWarning.replaceChildren();
  elements.duplicateWarning.classList.toggle("hidden", !hasDuplicates);
  if (hasDuplicates) {
    const heading = document.createElement("strong");
    heading.textContent = "Potential duplicate source records";
    const copy = document.createElement("span");
    copy.textContent = report.duplicateWarnings[0].message;
    elements.duplicateWarning.append(heading, copy);
  }

  renderIssues(report.issues);
  const results = report.results ?? [];
  elements.resultsBody.replaceChildren();
  if (!results.length) {
    elements.reportSummary.classList.add("hidden");
    showEmpty("No matching records", "Review the input issues above or try another year.");
    return;
  }

  const fragment = document.createDocumentFragment();
  for (const item of results) {
    const row = document.createElement("tr");
    resultCell(row, String(item.inputLine));
    resultCell(row, item.cnCode, "strong-cell");
    resultCell(row, item.country, "strong-cell");
    const routeCell = document.createElement("td");
    const route = document.createElement("span");
    route.className = "route-pill";
    route.textContent = item.productionRouteLabel;
    routeCell.append(route);
    row.append(routeCell);
    resultCell(row, `${formatNumber(item.weightTonnes, 4)} t`);
    resultCell(row, `${Number(item.emissionsPerTonne).toFixed(4)} tCO₂/t`);
    resultCell(row, formatEmissions(item.totalEmissions));
    resultCell(row, formatMoney(item.co2Price));
    resultCell(row, formatMoney(item.costPerTonne));
    resultCell(row, formatMoney(item.totalCbamCost), "strong-cell");
    fragment.append(row);
  }
  elements.resultsBody.append(fragment);
  elements.resultsEmpty.classList.add("hidden");
  elements.results.classList.remove("hidden");
  renderSummary(results, report.year);
}

/* ---------- data loading and actions ---------- */

async function loadMeta() {
  try {
    const response = await fetch("/api/batch-meta");
    if (!response.ok) throw new Error(await responseError(response));
    state.meta = await response.json();
    if (!state.meta.years.includes(state.year)) {
      state.year = state.meta.years[0];
    }
    renderOptions(elements.codeOptions, state.meta.codes);
    renderOptions(elements.countryOptions, state.meta.countries);
  } catch (error) {
    setStatus(error.message, "error");
  } finally {
    renderYearButtons();
    renderRows();
  }
}

async function importWorkbook(file) {
  if (!isSupportedWorkbook(file)) {
    setStatus("Choose a standard .xlsx workbook. Other Excel formats are not supported.", "error");
    return;
  }
  setBusy(true, `Reading ${file.name}…`);
  try {
    const response = await fetch("/api/batch-import", {
      method: "POST",
      headers: { "Content-Type": XLSX_MIME },
      body: file,
    });
    if (!response.ok) throw new Error(await responseError(response));
    const parsed = await response.json();
    state.lines = mergeUploadedLines(state.lines, parsed.lines);
    if (!state.lines.length) state.lines = [createBlankLine(1)];
    state.importIssues = parsed.issues ?? [];
    state.report = null;
    renderRows();
    renderIssues(state.importIssues, "Excel import issues");
    const message = `${parsed.lines.length} row${parsed.lines.length === 1 ? "" : "s"} imported from ${file.name}.`;
    setStatus(message, parsed.issues?.length ? "" : "success");
  } catch (error) {
    setStatus(error.message, "error");
  } finally {
    setBusy(false);
    renderRows();
    renderYearButtons();
  }
}

async function generateReport() {
  const built = buildRequestPayload(state.year, state.lines, state.importIssues);
  const issueByLine = new Map(built.issues.map((issue) => [issue.inputLine, issue.error]));
  state.lines = state.lines.map((line) => ({
    ...line,
    issue: issueByLine.get(line.inputLine) || "",
  }));
  renderRows();
  if (!built.payload.lines.length) {
    renderIssues(built.issues);
    setStatus("Add at least one complete, valid input row.", "error");
    return;
  }

  setBusy(true, "Generating the report…");
  try {
    const response = await postJson("/api/batch-report", built.payload);
    state.report = await response.json();
    renderReport(state.report);
    setStatus(
      `${state.report.results.length} stored record${state.report.results.length === 1 ? "" : "s"} returned.`,
      "success",
    );
    elements.exportReport.disabled = false;
    elements.reportSection.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    invalidateReport();
    setStatus(error.message, "error");
  } finally {
    setBusy(false);
    renderRows();
    renderYearButtons();
  }
}

async function exportReport() {
  const built = buildRequestPayload(state.year, state.lines, state.importIssues);
  if (!built.payload.lines.length) {
    setStatus("There are no valid rows to export.", "error");
    return;
  }
  setBusy(true, "Building the Excel report…");
  try {
    const response = await postJson("/api/batch-export", built.payload);
    downloadBlob(
      await response.blob(),
      filenameFromResponse(response, `CBAM_Batch_Report_${state.year}.xlsx`),
    );
    setStatus("Excel report downloaded.", "success");
  } catch (error) {
    setStatus(error.message, "error");
  } finally {
    setBusy(false);
    renderRows();
    renderYearButtons();
  }
}

async function downloadTemplate() {
  setBusy(true, "Preparing the Excel template…");
  try {
    const response = await fetch("/api/batch-template");
    if (!response.ok) throw new Error(await responseError(response));
    downloadBlob(
      await response.blob(),
      filenameFromResponse(response, "CBAM_Batch_Input_Template.xlsx"),
    );
    setStatus("Excel template downloaded.", "success");
  } catch (error) {
    setStatus(error.message, "error");
  } finally {
    setBusy(false);
    renderRows();
    renderYearButtons();
  }
}

/* ---------- events ---------- */

function bindEvents() {
  elements.inputRows.addEventListener("input", (event) => {
    const input = event.target.closest("input[data-field]");
    if (!input) return;
    const index = Number(input.dataset.index);
    state.lines[index][input.dataset.field] = input.value;
    if (input.dataset.field === "cnCode") {
      const suggestionList = suggestionListForField("cnCode", input.value);
      if (suggestionList) input.setAttribute("list", suggestionList);
      else input.removeAttribute("list");
    }
    state.lines[index].issue = "";
    invalidateReport();
    input.removeAttribute("aria-invalid");
  });

  elements.inputRows.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-remove-index]");
    if (!button) return;
    const index = Number(button.dataset.removeIndex);
    state.lines.splice(index, 1);
    if (!state.lines.length) state.lines.push(createBlankLine(1));
    state.lines = state.lines.map((line, lineIndex) => ({
      ...line,
      inputLine: lineIndex + 1,
    }));
    invalidateReport();
    renderRows();
  });

  elements.yearButtons.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-year]");
    if (!button) return;
    state.year = Number(button.dataset.year);
    invalidateReport();
    renderYearButtons();
  });

  elements.addRow.addEventListener("click", () => {
    state.lines.push(createBlankLine(state.lines.length + 1));
    renderRows();
    elements.inputRows.querySelector("tr:last-of-type input")?.focus();
  });

  elements.downloadTemplate.addEventListener("click", downloadTemplate);
  elements.generateReport.addEventListener("click", generateReport);
  elements.exportReport.addEventListener("click", exportReport);

  elements.uploadWorkbook.addEventListener("click", () => {
    openWorkbookPicker(elements.fileInput);
  });

  elements.fileInput.addEventListener("change", async () => {
    const [file] = elements.fileInput.files;
    elements.fileInput.value = "";
    if (!file) return;
    await importWorkbook(file);
  });

  let dragDepth = 0;
  elements.inputCard.addEventListener("dragenter", (event) => {
    event.preventDefault();
    if (state.busy) return;
    dragDepth += 1;
    elements.inputCard.classList.add("drag-active");
  });

  elements.inputCard.addEventListener("dragover", (event) => {
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = state.busy ? "none" : "copy";
  });

  elements.inputCard.addEventListener("dragleave", () => {
    dragDepth = Math.max(0, dragDepth - 1);
    if (!dragDepth) elements.inputCard.classList.remove("drag-active");
  });

  elements.inputCard.addEventListener("drop", async (event) => {
    event.preventDefault();
    dragDepth = 0;
    elements.inputCard.classList.remove("drag-active");
    if (state.busy) return;
    const files = Array.from(event.dataTransfer?.files ?? []);
    if (files.length !== 1) {
      setStatus("Drop one .xlsx workbook at a time.", "error");
      return;
    }
    await importWorkbook(files[0]);
  });
}

/* ---------- bootstrap ---------- */

bindEvents();
renderRows();
renderYearButtons();
loadMeta();
