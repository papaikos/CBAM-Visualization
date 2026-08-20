import assert from "node:assert/strict";
import test from "node:test";

import {
  buildRequestPayload,
  createBlankLine,
  isSupportedWorkbook,
  mergeUploadedLines,
  openWorkbookPicker,
  reportHasDuplicateWarnings,
  suggestionListForField,
} from "../public/js/batch/model.js";


test("blank rows use string inputs so CN codes are never coerced", () => {
  assert.deepEqual(createBlankLine(4), {
    inputLine: 4,
    cnCode: "",
    country: "",
    weightTonnes: "1",
    co2Price: "",
    issue: "",
  });
});

test("CN suggestions start at four digits while country suggestions stay available", () => {
  assert.equal(suggestionListForField("cnCode", "760"), null);
  assert.equal(suggestionListForField("cnCode", "7601"), "batch-code-options");
  assert.equal(suggestionListForField("cnCode", "76A1"), null);
  assert.equal(suggestionListForField("country", ""), "batch-country-options");
});

test("request payload validates rows and converts only valid numeric fields", () => {
  const built = buildRequestPayload(2026, [
    {
      inputLine: 1,
      cnCode: "076011010",
      country: "Türkiye",
      weightTonnes: "100",
      co2Price: "65.50",
    },
    {
      inputLine: 2,
      cnCode: "25231000",
      country: "Egypt",
      weightTonnes: "",
      co2Price: "",
    },
  ]);
  assert.deepEqual(built.issues, []);
  assert.deepEqual(built.payload, {
    year: 2026,
    lines: [
      {
        inputLine: 1,
        cnCode: "076011010",
        country: "Türkiye",
        weightTonnes: 100,
        co2Price: 65.5,
      },
      {
        inputLine: 2,
        cnCode: "25231000",
        country: "Egypt",
        weightTonnes: 1,
        co2Price: null,
      },
    ],
  });
});

test("request payload ignores empty rows and reports partial or invalid rows", () => {
  const built = buildRequestPayload(2027, [
    { inputLine: 1, cnCode: "", country: "", weightTonnes: "1", co2Price: "" },
    { inputLine: 2, cnCode: "76011010", country: "", weightTonnes: "1", co2Price: "" },
    { inputLine: 3, cnCode: "76011010", country: "Egypt", weightTonnes: "0", co2Price: "" },
    { inputLine: 4, cnCode: "76011010", country: "Egypt", weightTonnes: "1", co2Price: "-2" },
  ]);
  assert.deepEqual(built.payload.lines, []);
  assert.deepEqual(
    built.issues.map((issue) => issue.error),
    [
      "Country is required.",
      "Weight must be a number greater than zero.",
      "CO₂ price must be a number greater than or equal to zero.",
    ],
  );
});

test("request payload carries Excel import issues into report and export requests", () => {
  const importIssues = [
    {
      inputLine: 4,
      cnCode: "76011010",
      country: "Egypt",
      weightTonnes: "=1+1",
      co2Price: 65,
      error: "Excel formulas are not supported. Paste calculated values instead.",
    },
  ];
  const built = buildRequestPayload(
    2026,
    [{ inputLine: 1, cnCode: "76011010", country: "Egypt", weightTonnes: "1", co2Price: "" }],
    importIssues,
  );
  assert.deepEqual(built.payload.inputIssues, importIssues);
});

test("request payload also carries invalid manual rows when valid rows can continue", () => {
  const built = buildRequestPayload(2026, [
    { inputLine: 1, cnCode: "76011010", country: "Egypt", weightTonnes: "1", co2Price: "" },
    { inputLine: 2, cnCode: "76011010", country: "", weightTonnes: "1", co2Price: "" },
  ]);
  assert.deepEqual(built.payload.inputIssues, [
    { inputLine: 2, error: "Country is required." },
  ]);
});

test("uploaded rows replace only the untouched default row and otherwise append after manual rows", () => {
  const uploaded = [
    { inputLine: 2, cnCode: "76011010", country: "Türkiye", weightTonnes: 1, co2Price: null },
  ];
  assert.deepEqual(mergeUploadedLines([createBlankLine(1)], uploaded), [
    {
      inputLine: 1,
      cnCode: "76011010",
      country: "Türkiye",
      weightTonnes: "1",
      co2Price: "",
      issue: "",
    },
  ]);

  const existing = [
    {
      inputLine: 1,
      cnCode: "25231000",
      country: "Egypt",
      weightTonnes: "3",
      co2Price: "65",
      issue: "",
    },
  ];
  assert.deepEqual(mergeUploadedLines(existing, uploaded), [
    existing[0],
    {
      inputLine: 2,
      cnCode: "76011010",
      country: "Türkiye",
      weightTonnes: "1",
      co2Price: "",
      issue: "",
    },
  ]);
});

test("workbook picker opens on the first click and drop validation accepts only xlsx", () => {
  let clicks = 0;
  openWorkbookPicker({ disabled: false, click: () => { clicks += 1; } });
  assert.equal(clicks, 1);
  assert.equal(isSupportedWorkbook({ name: "inputs.xlsx" }), true);
  assert.equal(isSupportedWorkbook({ name: "inputs.XLSX" }), true);
  assert.equal(isSupportedWorkbook({ name: "inputs.xls" }), false);
  assert.equal(isSupportedWorkbook({ name: "inputs.csv" }), false);
});

test("duplicate banner state depends only on server warnings", () => {
  assert.equal(reportHasDuplicateWarnings({ results: [{ duplicateGroupSize: 9 }], duplicateWarnings: [] }), false);
  assert.equal(reportHasDuplicateWarnings({ results: [], duplicateWarnings: [{ inputLine: 1 }] }), true);
});
