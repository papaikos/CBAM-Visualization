/** Map Explorer page: Leaflet choropleth, tooltip, search, and country detail. */

import { fetchJson } from "../lib/api.js";
import { getColor, toGray } from "./color-scale.js";
import {
  canonicalCountryName,
  getCountryDataOverride,
  getDataLookupCanonical,
} from "./country-names.js";
import { initCnCodePicker } from "./cn-code-picker.js";
import { formatRouteLabel, getRouteExplanation } from "./routes.js";
import { initToolbarInteractions } from "./toolbar.js";

const WORLD_BOUNDS = [
  [-85, -180],
  [85, 180],
];

const GEOMETRY_URL = "/countries.topojson";
const DEFAULT_UNIT = "ton";

const state = {
  meta: null,
  map: null,
  geojson: null,
  geojsonLayer: null,
  countryRenderer: null,
  hoveredLayer: null,
  selectedCode: "",
  selectedYear: 2026,
  co2Price: "",
  mapData: null,
  selectedCountry: null,
  countryDetail: null,
  hoveredCountry: null,
  mouse: { x: 0, y: 0 },
  countrySearch: "",
  tooltipRenderQueued: false,
  suppressMapClickUntil: 0,
  selectionRequestId: 0,
};

const elements = {
  cnCodeInput: document.getElementById("cn-code-input"),
  cnCodeOptions: document.getElementById("cn-code-options"),
  co2PriceInput: document.getElementById("co2-price-input"),
  yearButtons: document.getElementById("year-buttons"),
  detailCard: document.getElementById("country-detail-card"),
  countrySearchInput: document.getElementById("country-search-input"),
  countrySearchClear: document.getElementById("country-search-clear"),
  countrySearchResults: document.getElementById("country-search-results"),
  legendMin: document.getElementById("legend-min"),
  legendMax: document.getElementById("legend-max"),
  legendUnit: document.getElementById("legend-unit"),
  hoverTooltip: document.getElementById("hover-tooltip"),
  disclaimerOpen: document.getElementById("disclaimer-open"),
  disclaimerDialog: document.getElementById("disclaimer-dialog"),
  disclaimerClose: document.getElementById("disclaimer-close"),
};

/* ---------- formatting ---------- */

/** Quantity unit of the selected CN code: "ton" for goods, "MWh" for electricity. */
function currentUnit() {
  return state.mapData?.unit || DEFAULT_UNIT;
}

function formatEmissions(value) {
  if (value === null || value === undefined) {
    return "No data";
  }
  return `${Number(value).toFixed(2)} tCO2/${currentUnit()}`;
}

function formatCurrency(value) {
  if (value === null || value === undefined || state.co2Price === "") {
    return null;
  }
  const co2Price = Number(state.co2Price);
  if (Number.isNaN(co2Price)) {
    return null;
  }
  return `${(Number(value) * co2Price).toFixed(2)} EUR/${currentUnit()}`;
}

/* ---------- map data lookups ---------- */

function valueColor(value) {
  return getColor(value, state.mapData?.maxValue || 0);
}

function getMapEntry(country) {
  if (!state.mapData) {
    return null;
  }
  return state.mapData.mapValuesByCanonical?.[getDataLookupCanonical(country)] ?? null;
}

function getMapValue(country) {
  return getMapEntry(country)?.paidEmissions ?? null;
}

function resolveApiCountryName(country) {
  if (!state.mapData) {
    return country;
  }
  return state.mapData.countryNameByCanonical?.[canonicalCountryName(country)] || country;
}

function countryHasAnyData(country) {
  return state.mapData?.countriesCanonical?.has(getDataLookupCanonical(country)) || false;
}

/* ---------- map setup ---------- */

function getResponsiveMinZoom() {
  const mapElement = document.getElementById("map");
  const mapWidth = mapElement?.clientWidth || window.innerWidth || 1024;
  const zoomNeededToFillWidth = Math.ceil(Math.log2(mapWidth / 256));
  return Math.max(2, Math.min(4, zoomNeededToFillWidth));
}

function syncMapViewport() {
  if (!state.map) {
    return;
  }

  const minZoom = getResponsiveMinZoom();
  if (state.map.getMinZoom() !== minZoom) {
    state.map.setMinZoom(minZoom);
  }
  if (state.map.getZoom() < minZoom) {
    state.map.setZoom(minZoom, { animate: false });
  }
  state.map.setMaxBounds(WORLD_BOUNDS);
  state.map.panInsideBounds(WORLD_BOUNDS, { animate: false });
}

function initializeMap() {
  state.countryRenderer = L.svg({ padding: 1.6 });

  state.map = L.map("map", {
    center: [20, 0],
    zoom: getResponsiveMinZoom(),
    minZoom: getResponsiveMinZoom(),
    maxZoom: 6,
    zoomControl: true,
    worldCopyJump: false,
    maxBounds: WORLD_BOUNDS,
    maxBoundsViscosity: 1,
  });

  L.tileLayer("https://{s}.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}{r}.png?key=cb1_3061_1_ce706d68d7c37fb4e7727576", {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a> | By Athanasios Papazikos',
    bounds: WORLD_BOUNDS,
    keepBuffer: 8,
    noWrap: true,
  }).addTo(state.map);

  state.map.on("click", () => {
    if (Date.now() < state.suppressMapClickUntil) {
      return;
    }
    clearSelectedCountry();
  });

  state.map.on("resize", syncMapViewport);
  syncMapViewport();
}

function getFeatureName(feature) {
  return feature?.properties?.ADMIN || feature?.properties?.name || "";
}

/** Country-name normalization is done once per feature, not on every restyle. */
const featureLookupKeys = new WeakMap();

function getFeatureLookupKey(feature) {
  let key = featureLookupKeys.get(feature);
  if (key === undefined) {
    key = getDataLookupCanonical(getFeatureName(feature));
    featureLookupKeys.set(feature, key);
  }
  return key;
}

function getFeatureStyle(feature) {
  const entry = state.mapData?.mapValuesByCanonical?.[getFeatureLookupKey(feature)];
  const color = valueColor(entry?.paidEmissions ?? null);
  const isHovered = state.hoveredLayer?.feature === feature;

  return {
    className: "country-path",
    fillColor: isHovered ? toGray(color) : color,
    fillOpacity: isHovered ? 0.92 : 0.86,
    weight: isHovered ? 1.8 : 1,
    color: "#ffffff",
    opacity: 1,
  };
}

function applyLayerStyle(layer) {
  if (!layer) {
    return;
  }
  layer.setStyle(getFeatureStyle(layer.feature));
}

function refreshLayerStyles() {
  state.geojsonLayer?.eachLayer((layer) => {
    layer.setStyle(getFeatureStyle(layer.feature));
  });
}

function stopMapClick(event) {
  state.suppressMapClickUntil = Date.now() + 350;
  if (event.originalEvent) {
    L.DomEvent.stop(event.originalEvent);
  }
}

function buildGeoJsonLayer() {
  state.geojsonLayer = L.geoJSON(state.geojson, {
    bubblingMouseEvents: false,
    interactive: true,
    renderer: state.countryRenderer,
    smoothFactor: 0.8,
    style: (feature) => getFeatureStyle(feature),
    onEachFeature: (feature, layer) => {
      layer.on({
        mouseover: (event) => {
          const previousLayer = state.hoveredLayer;
          state.hoveredCountry = getFeatureName(event.target.feature);
          state.hoveredLayer = event.target;
          if (previousLayer && previousLayer !== event.target) {
            applyLayerStyle(previousLayer);
          }
          state.mouse = {
            x: event.originalEvent.clientX,
            y: event.originalEvent.clientY,
          };
          renderTooltip();
          applyLayerStyle(event.target);
        },
        mouseout: (event) => {
          state.hoveredCountry = null;
          if (state.hoveredLayer === event.target) {
            state.hoveredLayer = null;
          }
          renderTooltip();
          applyLayerStyle(event.target);
        },
        mousemove: (event) => {
          state.mouse = {
            x: event.originalEvent.clientX,
            y: event.originalEvent.clientY,
          };
          queueTooltipMove();
        },
        click: async (event) => {
          stopMapClick(event);
          await selectCountry(getFeatureName(event.target.feature));
        },
      });
    },
  }).addTo(state.map);
}

/* ---------- data refresh ---------- */

async function refreshMapData() {
  if (!state.selectedCode) {
    return;
  }

  state.mapData = await fetchJson("/api/map-data", {
    cn_code: state.selectedCode,
    year: state.selectedYear,
  });

  state.mapData.mapValuesByCanonical = Object.fromEntries(
    state.mapData.mapValues.map((item) => [
      canonicalCountryName(item.country),
      { ...item, paidEmissions: Number(item.paidEmissions) },
    ]),
  );
  state.mapData.countriesCanonical = new Set(state.mapData.countries.map(canonicalCountryName));
  state.mapData.countryNameByCanonical = Object.fromEntries(
    state.mapData.countries.map((country) => [canonicalCountryName(country), country]),
  );

  state.selectedCountry = null;
  state.countryDetail = null;
  state.hoveredCountry = null;
  state.hoveredLayer = null;

  updateLegend();
  renderCountrySearchResults();
  renderCountryDetail();
  renderTooltip();
  refreshLayerStyles();
}

function updateLegend() {
  if (!state.mapData) {
    return;
  }
  if (elements.legendMin) {
    elements.legendMin.textContent = Number(state.mapData.minValue || 0).toFixed(2);
  }
  if (elements.legendMax) {
    elements.legendMax.textContent = Number(state.mapData.maxValue || 0).toFixed(2);
  }
  if (elements.legendUnit) {
    elements.legendUnit.textContent = `tCO2/${currentUnit()}`;
  }
}

/* ---------- country selection ---------- */

async function selectCountry(country) {
  const override = getCountryDataOverride(country);
  const requestedCountry = override?.sourceCountry || country;
  const apiCountry = resolveApiCountryName(requestedCountry);
  if (!countryHasAnyData(requestedCountry)) {
    return;
  }

  const requestId = ++state.selectionRequestId;
  const countryDetail = await fetchJson("/api/country", {
    cn_code: state.selectedCode,
    year: state.selectedYear,
    country: apiCountry,
  });

  if (requestId !== state.selectionRequestId) {
    return;
  }

  if (override) {
    countryDetail.country = override.displayCountry;
    countryDetail.mirroredFrom = null;
  }

  state.selectedCountry = override?.displayCountry || apiCountry;
  state.countryDetail = countryDetail;
  renderCountryDetail();
}

function clearSelectedCountry() {
  if (!state.selectedCountry && !state.countryDetail) {
    return;
  }
  state.selectionRequestId += 1;
  state.selectedCountry = null;
  state.countryDetail = null;
  renderCountryDetail();
}

/* ---------- search ---------- */

function getFilteredCountries() {
  const countries = state.mapData?.countries || [];
  if (!state.countrySearch) {
    return countries.slice(0, 8);
  }
  const term = state.countrySearch.toLowerCase();
  return countries.filter((country) => country.toLowerCase().includes(term)).slice(0, 8);
}

function renderCountrySearchResults() {
  const results = getFilteredCountries();
  const hasSearch = state.countrySearch.length > 0;
  if (!hasSearch || results.length === 0) {
    elements.countrySearchResults.classList.add("hidden");
    elements.countrySearchResults.replaceChildren();
    return;
  }

  const fragment = document.createDocumentFragment();
  for (const country of results) {
    const mapValue = getMapValue(country);
    const button = document.createElement("button");
    button.type = "button";
    button.className = "search-result";
    button.dataset.country = country;

    const name = document.createElement("span");
    name.textContent = country;
    const value = document.createElement("small");
    value.textContent = mapValue === null ? "No map value" : formatEmissions(mapValue);
    button.append(name, value);

    button.addEventListener("click", async () => {
      await selectCountry(country);
      elements.countrySearchResults.classList.add("hidden");
    });
    fragment.append(button);
  }

  elements.countrySearchResults.replaceChildren(fragment);
  elements.countrySearchResults.classList.remove("hidden");
}

/* ---------- tooltip ---------- */

/** Mouse moves only reposition the tooltip; its content changes on hover or price changes. */
function queueTooltipMove() {
  if (state.tooltipRenderQueued) {
    return;
  }
  state.tooltipRenderQueued = true;
  window.requestAnimationFrame(() => {
    state.tooltipRenderQueued = false;
    positionTooltip();
  });
}

function positionTooltip() {
  elements.hoverTooltip.style.left = `${state.mouse.x + 16}px`;
  elements.hoverTooltip.style.top = `${state.mouse.y - 18}px`;
}

function tooltipRow(...children) {
  const row = document.createElement("div");
  row.className = "tooltip-row";
  row.append(...children);
  return row;
}

function renderTooltip() {
  if (!state.hoveredCountry) {
    elements.hoverTooltip.classList.add("hidden");
    elements.hoverTooltip.replaceChildren();
    return;
  }

  const mapEntry = getMapEntry(state.hoveredCountry);
  const mapValue = mapEntry?.paidEmissions ?? null;
  const cost = formatCurrency(mapValue);

  const title = document.createElement("h3");
  title.textContent = state.hoveredCountry;

  const dot = document.createElement("span");
  dot.className = "tooltip-dot";
  dot.style.background = valueColor(mapValue);
  const valueText = document.createElement("span");
  valueText.textContent = mapValue === null ? "No map value" : formatEmissions(mapValue);

  const children = [title, tooltipRow(dot, valueText)];
  if (mapEntry) {
    const route = document.createElement("span");
    route.textContent = `Production Route: ${mapEntry.sourceLabel}`;
    children.push(tooltipRow(route));
  }
  if (cost) {
    const costText = document.createElement("span");
    costText.textContent = cost;
    children.push(tooltipRow(costText));
  }
  if (!countryHasAnyData(state.hoveredCountry)) {
    const noData = document.createElement("span");
    noData.textContent = "No country data exists for this code/year.";
    children.push(tooltipRow(noData));
  }

  elements.hoverTooltip.replaceChildren(...children);
  elements.hoverTooltip.classList.remove("hidden");
  positionTooltip();
}

/* ---------- country detail card ---------- */

function detailRouteRow(route, quantityUnit) {
  const row = document.createElement("div");
  row.className = "route-row";

  const name = document.createElement("div");
  name.className = "route-name";
  const label = document.createElement("span");
  label.textContent = formatRouteLabel(route.label);
  name.append(label);
  if (route.isDisplayedValue) {
    const badge = document.createElement("span");
    badge.className = "route-badge";
    badge.textContent = "Route";
    name.append(badge);
  }

  const description = document.createElement("div");
  description.className = "route-description";
  description.textContent =
    getRouteExplanation(route.value) ||
    (quantityUnit === "MWh" ? "Default CO2 emission factor of electricity" : "No description available");

  const metric = document.createElement("div");
  metric.className = "route-metric";
  const value = document.createElement("strong");
  value.textContent = Number(route.paidEmissions).toFixed(2);
  const unit = document.createElement("span");
  unit.textContent = `tCO2/${quantityUnit}`;
  metric.append(value, unit);

  row.append(name, description, metric);
  return row;
}

function renderCountryDetail() {
  if (!state.countryDetail) {
    elements.detailCard.classList.add("hidden");
    elements.detailCard.replaceChildren();
    return;
  }

  const detail = state.countryDetail;
  const heroValue = detail.displayValue ?? detail.routes[0]?.paidEmissions ?? null;
  const mapCost = formatCurrency(heroValue);

  const header = document.createElement("div");
  header.className = "detail-header";
  const close = document.createElement("button");
  close.type = "button";
  close.className = "detail-close";
  close.setAttribute("aria-label", "Close country detail");
  close.textContent = "x";
  close.addEventListener("click", clearSelectedCountry);
  const title = document.createElement("h2");
  title.textContent = detail.country;
  const subtitle = document.createElement("p");
  subtitle.className = "detail-subtitle";
  subtitle.textContent = `CN code ${detail.cnCode} · Year ${detail.year}`;
  header.append(close, title, subtitle);

  const body = document.createElement("div");
  body.className = "detail-body";

  const summary = document.createElement("div");
  summary.className = "detail-summary";
  const chip = document.createElement("div");
  chip.className = "value-chip";
  chip.style.background = valueColor(heroValue);
  chip.textContent = heroValue === null ? "N/A" : Number(heroValue).toFixed(2);
  const meta = document.createElement("div");
  meta.className = "value-meta";
  const metaValue = document.createElement("strong");
  metaValue.textContent = heroValue === null ? "No data" : Number(heroValue).toFixed(2);
  const metaCaption = document.createElement("p");
  metaCaption.textContent = `tCO2/${detail.unit || DEFAULT_UNIT} shown on the map for this country`;
  meta.append(metaValue, metaCaption);
  if (mapCost) {
    const metaCost = document.createElement("p");
    metaCost.textContent = mapCost;
    meta.append(metaCost);
  }
  summary.append(chip, meta);

  const note = document.createElement("p");
  note.className = "detail-note";
  if (detail.mirroredFrom) {
    const mirrorText = document.createElement("span");
    mirrorText.append("This country mirrors ");
    const source = document.createElement("strong");
    source.textContent = detail.mirroredFrom;
    mirrorText.append(source, " for map value and routes.");
    note.append(mirrorText, document.createElement("br"));
  }
  if (detail.displaySourceType === "average_routes") {
    note.append("This country has multiple production routes, so the map uses their average value.");
  }

  const routesTable = document.createElement("div");
  routesTable.className = "routes-table";
  routesTable.append(...detail.routes.map((route) => detailRouteRow(route, detail.unit || DEFAULT_UNIT)));

  body.append(summary, ...(note.childNodes.length ? [note] : []), routesTable);
  elements.detailCard.replaceChildren(header, body);
  elements.detailCard.classList.remove("hidden");
}

/* ---------- toolbar controls ---------- */

function renderCodeOptions(codes) {
  const fragment = document.createDocumentFragment();
  for (const code of codes) {
    const option = document.createElement("option");
    option.value = code;
    fragment.append(option);
  }
  elements.cnCodeOptions.replaceChildren(fragment);
}

function renderYearButtons() {
  const years = state.meta?.years ?? [2026, 2027];
  const fragment = document.createDocumentFragment();
  for (const year of years) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `year-button${year === state.selectedYear ? " active" : ""}`;
    button.dataset.year = String(year);
    button.textContent = String(year);
    fragment.append(button);
  }
  elements.yearButtons.replaceChildren(fragment);
}

function bindEvents() {
  elements.cnCodeInput.addEventListener("change", async (event) => {
    const nextCode = event.target.value.trim();
    if (!state.meta?.codes.includes(nextCode)) {
      event.target.value = state.selectedCode;
      return;
    }
    if (nextCode === state.selectedCode) {
      return;
    }
    state.selectedCode = nextCode;
    await refreshMapData();
  });

  elements.co2PriceInput.addEventListener("input", (event) => {
    state.co2Price = event.target.value.trim();
    renderTooltip();
    renderCountryDetail();
  });

  elements.yearButtons.addEventListener("click", async (event) => {
    const button = event.target.closest(".year-button");
    if (!button) {
      return;
    }
    const nextYear = Number(button.dataset.year);
    if (nextYear === state.selectedYear) {
      return;
    }
    state.selectedYear = nextYear;
    renderYearButtons();
    await refreshMapData();
  });

  elements.countrySearchInput.addEventListener("input", () => {
    state.countrySearch = elements.countrySearchInput.value.trim();
    elements.countrySearchClear.classList.toggle("hidden", state.countrySearch === "");
    renderCountrySearchResults();
  });

  elements.countrySearchInput.addEventListener("keydown", async (event) => {
    if (event.key !== "Enter") {
      return;
    }
    const firstMatch = getFilteredCountries()[0];
    if (!firstMatch) {
      return;
    }
    event.preventDefault();
    await selectCountry(firstMatch);
  });

  elements.countrySearchClear.addEventListener("click", () => {
    state.countrySearch = "";
    elements.countrySearchInput.value = "";
    elements.countrySearchClear.classList.add("hidden");
    renderCountrySearchResults();
  });

  document.addEventListener("click", (event) => {
    if (!event.target.closest(".search-card")) {
      elements.countrySearchResults.classList.add("hidden");
    }
  });

  elements.disclaimerOpen.addEventListener("click", () => {
    elements.disclaimerDialog.showModal();
  });

  elements.disclaimerClose.addEventListener("click", () => {
    elements.disclaimerDialog.close();
  });

  elements.disclaimerDialog.addEventListener("click", (event) => {
    if (event.target === elements.disclaimerDialog) {
      elements.disclaimerDialog.close();
    }
  });
}

/* ---------- bootstrap ---------- */

async function loadCountryGeometry() {
  const response = await fetch(GEOMETRY_URL);
  if (!response.ok) {
    throw new Error(`Map geometry request failed: ${response.status}`);
  }
  const topology = await response.json();
  return topojson.feature(topology, topology.objects.countries);
}

async function init() {
  renderYearButtons();
  bindEvents();
  initializeMap();

  const [meta, geojson] = await Promise.all([fetchJson("/api/meta"), loadCountryGeometry()]);

  state.meta = meta;
  state.geojson = geojson;
  state.selectedCode = meta.defaultCode || meta.codes[0] || "";
  state.selectedYear = meta.defaultYear || 2026;
  elements.cnCodeInput.value = state.selectedCode;

  renderCodeOptions(meta.codes);
  buildGeoJsonLayer();
  await refreshMapData();
}

initCnCodePicker();
initToolbarInteractions();

// Module scripts run after the document is parsed, so start right away instead of
// waiting for the window "load" event (which also waits for images and tiles).
init().catch((error) => {
  console.error(error);
  if (elements.legendMin) {
    elements.legendMin.textContent = "!";
  }
  if (elements.legendMax) {
    elements.legendMax.textContent = "!";
  }
});
