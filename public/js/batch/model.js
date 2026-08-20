/** Pure batch-report input logic (kept free of DOM access so it is unit-testable). */

export const createBlankLine = (inputLine) => ({
  inputLine,
  cnCode: "",
  country: "",
  weightTonnes: "1",
  co2Price: "",
  issue: "",
});

export const isBlank = (value) =>
  value === null || value === undefined || String(value).trim() === "";

export function buildRequestPayload(year, lines, inputIssues = []) {
  const normalized = [];
  const issues = [];

  lines.forEach((line, index) => {
    const inputLine = Number.isInteger(line.inputLine) ? line.inputLine : index + 1;
    const cnCode = String(line.cnCode ?? "").trim();
    const country = String(line.country ?? "").trim();
    const rawWeight = line.weightTonnes;
    const rawPrice = line.co2Price;

    const hasOnlyDefaultWeight =
      isBlank(cnCode) &&
      isBlank(country) &&
      isBlank(rawPrice) &&
      (isBlank(rawWeight) || Number(rawWeight) === 1);
    if (hasOnlyDefaultWeight) return;
    if (!cnCode) {
      issues.push({ inputLine, error: "CN code is required." });
      return;
    }
    if (!country) {
      issues.push({ inputLine, error: "Country is required." });
      return;
    }

    const weightTonnes = isBlank(rawWeight) ? 1 : Number(rawWeight);
    if (!Number.isFinite(weightTonnes) || weightTonnes <= 0) {
      issues.push({ inputLine, error: "Weight must be a number greater than zero." });
      return;
    }

    const co2Price = isBlank(rawPrice) ? null : Number(rawPrice);
    if (co2Price !== null && (!Number.isFinite(co2Price) || co2Price < 0)) {
      issues.push({
        inputLine,
        error: "CO₂ price must be a number greater than or equal to zero.",
      });
      return;
    }

    normalized.push({ inputLine, cnCode, country, weightTonnes, co2Price });
  });

  const payload = { year, lines: normalized };
  const carriedIssues = [...inputIssues, ...issues];
  if (carriedIssues.length) payload.inputIssues = carriedIssues;
  return { payload, issues };
}

export function isUntouchedDefault(lines) {
  if (lines.length !== 1) return false;
  const [line] = lines;
  return (
    isBlank(line.cnCode) &&
    isBlank(line.country) &&
    (isBlank(line.weightTonnes) || String(line.weightTonnes).trim() === "1") &&
    isBlank(line.co2Price)
  );
}

export function mergeUploadedLines(currentLines, uploadedLines) {
  const mapped = uploadedLines.map((line) => ({
    inputLine: 0,
    cnCode: String(line.cnCode ?? ""),
    country: String(line.country ?? ""),
    weightTonnes: isBlank(line.weightTonnes) ? "1" : String(line.weightTonnes),
    co2Price: isBlank(line.co2Price) ? "" : String(line.co2Price),
    issue: "",
  }));
  const combined = isUntouchedDefault(currentLines) ? mapped : [...currentLines, ...mapped];
  return combined.map((line, index) => ({ ...line, inputLine: index + 1 }));
}

export const reportHasDuplicateWarnings = (report) =>
  Array.isArray(report?.duplicateWarnings) && report.duplicateWarnings.length > 0;

export const isSupportedWorkbook = (file) =>
  Boolean(file?.name && String(file.name).toLowerCase().endsWith(".xlsx"));

export function openWorkbookPicker(fileInput) {
  if (!fileInput?.disabled) fileInput?.click();
}

export function suggestionListForField(field, value) {
  if (field === "country") return "batch-country-options";
  if (field === "cnCode" && /^\d{4,}$/.test(String(value ?? "").trim())) {
    return "batch-code-options";
  }
  return null;
}
