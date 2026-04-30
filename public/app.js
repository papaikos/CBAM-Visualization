const state = {
  meta: null,
  map: null,
  geojson: null,
  geojsonLayer: null,
  countryRenderer: null,
  featureLayers: new Map(),
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

const WORLD_BOUNDS = [
  [-85, -180],
  [85, 180],
];

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
  hoverTooltip: document.getElementById("hover-tooltip"),
};

const COUNTRY_ALIASES = {
  bahamas: "the bahamas",
  "bosnia and herz": "bosnia and herzegovina",
  "central african rep": "central african republic",
  congo: "republic of the congo",
  "cote d ivoire": "ivory coast",
  "czech republic": "czechia",
  "czech rep": "czechia",
  "dem rep congo": "democratic republic of the congo",
  "dominican rep": "dominican republic",
  "eq guinea": "equatorial guinea",
  eswatini: "swaziland",
  "falkland is": "falkland islands",
  "fr s antarctic lands": "french southern and antarctic lands",
  "hong kong": "hong kong s a r",
  "lao pdr": "laos",
  macedonia: "north macedonia",
  micronesia: "federated states of micronesia",
  "myanmar/burma": "myanmar",
  "north korea": "democratic people's republic of korea",
  "korea north": "democratic people's republic of korea",
  "dem rep korea": "democratic people's republic of korea",
  serbia: "republic of serbia",
  "s sudan": "south sudan",
  "sao tome and principe": "sao tome and principe",
  "solomon is": "solomon islands",
  tanzania: "united republic of tanzania",
  "timor leste": "east timor",
  turkey: "turkiye",
  "united states of america": "united states",
  "w sahara": "western sahara",
};

const COUNTRY_DATA_OVERRIDES = {
  "northern cyprus": {
    sourceCountry: "Turkey",
    displayCountry: "Northern Cyprus",
  },
};

function normalizeCountryName(value) {
  return (value || "")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/&/g, "and")
    .replace(/[().,'`’/-]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function canonicalCountryName(value) {
  const normalized = normalizeCountryName(value);
  return COUNTRY_ALIASES[normalized] || normalized;
}

function getCountryDataOverride(country) {
  const normalized = normalizeCountryName(country);
  const canonical = canonicalCountryName(country);
  return COUNTRY_DATA_OVERRIDES[normalized] || COUNTRY_DATA_OVERRIDES[canonical] || null;
}

function getDataLookupCanonical(country) {
  const override = getCountryDataOverride(country);
  return canonicalCountryName(override?.sourceCountry || country);
}

function formatRouteLabel(route) {
  return route || "Unspecified";
}

function normalizeRouteCode(route) {
  const normalized = (route || "")
    .replace(/[()]/g, "")
    .trim()
    .toUpperCase();
  if (!normalized) {
    return "";
  }
  const letterMatch = normalized.match(/^[A-Z]+/);
  return letterMatch ? letterMatch[0] : normalized;
}

function getRouteExplanation(route) {
  const explanations = {
    A: "grey clinker / cement",
    B: "white clinker / cement",
    C: "Carbon Steel based on BF/BOF",
    D: "Carbon Steel based on DRI/EAF",
    E: "Carbon Steel based on Scrap/EAF",
    F: "Low alloy Steel based on BF/BOF",
    G: "Low alloy Steel based on DRI/EAF",
    H: "Low alloy Steel based on scrap/EAF",
    J: "High alloy Steel (based on EAF)",
    K: "primary Aluminium",
    L: "secondary Aluminium",
  };

  const normalizedCode = normalizeRouteCode(route);
  return explanations[normalizedCode] || null;
}

function formatEmissions(value) {
  if (value === null || value === undefined) {
    return "No data";
  }
  return `${Number(value).toFixed(2)} tCO2/ton`;
}

function formatCurrency(value) {
  if (value === null || value === undefined || state.co2Price === "") {
    return null;
  }
  const co2Price = Number(state.co2Price);
  if (Number.isNaN(co2Price)) {
    return null;
  }
  return `${(Number(value) * co2Price).toFixed(2)} EUR/ton`;
}

function getColor(value) {
  const max = state.mapData?.maxValue || 0;
  if (value === null || value === undefined) {
    return "#e2e8f0";
  }
  if (max <= 0) {
    return "rgb(0, 128, 68)";
  }
  const ratio = Math.min(value / max, 1);
  if (ratio <= 0.33) {
    const blend = ratio / 0.33;
    const red = Math.round(255 * blend);
    const green = Math.round(128 + 127 * blend);
    return `rgb(${red}, ${green}, 68)`;
  }
  if (ratio <= 0.66) {
    const blend = (ratio - 0.33) / 0.33;
    const green = Math.round(255 - 100 * blend);
    return `rgb(255, ${green}, 68)`;
  }
  const blend = (ratio - 0.66) / 0.34;
  const red = Math.round(255 - 40 * blend);
  const green = Math.round(155 - 115 * blend);
  const blue = Math.round(68 - 28 * blend);
  return `rgb(${red}, ${green}, ${blue})`;
}

function toGray(rgbColor) {
  const match = rgbColor.match(/rgb\((\d+),\s*(\d+),\s*(\d+)\)/);
  if (!match) {
    return rgbColor;
  }
  const [red, green, blue] = match.slice(1).map(Number);
  const gray = Math.round(0.299 * red + 0.587 * green + 0.114 * blue);
  return `rgb(${gray}, ${gray}, ${gray})`;
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
  return state.mapData?.countriesCanonical?.includes(getDataLookupCanonical(country)) || false;
}

function createApiUrl(path, params = {}) {
  const url = new URL(path, window.location.origin);
  Object.entries(params).forEach(([key, value]) => {
    if (value !== null && value !== undefined && value !== "") {
      url.searchParams.set(key, value);
    }
  });
  return url.toString();
}

async function fetchJson(path, params = {}) {
  const response = await fetch(createApiUrl(path, params));
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.message || `Request failed: ${response.status}`);
  }
  return response.json();
}

async function init() {
  renderYearButtons();
  bindEvents();
  initializeMap();

  const [meta, geojson] = await Promise.all([
    fetchJson("/api/meta"),
    fetch("/countries.geojson").then((response) => response.json()),
  ]);

  state.meta = meta;
  state.geojson = geojson;
  state.selectedCode = meta.defaultCode || meta.codes[0] || "";
  state.selectedYear = meta.defaultYear || 2026;
  elements.cnCodeInput.value = state.selectedCode;

  renderCodeOptions(meta.codes);
  buildGeoJsonLayer();
  await refreshMapData();
}

function initializeMap() {
  const initialMinZoom = getResponsiveMinZoom();

  state.countryRenderer = L.svg({
    padding: 1.6,
  });

  state.map = L.map("map", {
    center: [20, 0],
    zoom: initialMinZoom,
    minZoom: initialMinZoom,
    maxZoom: 6,
    zoomControl: true,
    worldCopyJump: false,
    maxBounds: WORLD_BOUNDS,
    maxBoundsViscosity: 1,
  });

  L.tileLayer("https://{s}.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}{r}.png", {
    attribution: '&copy; <a href="https://carto.com/">CARTO</a> | By Athanasios Papazikos',
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

function renderCodeOptions(codes) {
  elements.cnCodeOptions.innerHTML = codes
    .map((code) => `<option value="${code}"></option>`)
    .join("");
}

function renderYearButtons() {
  elements.yearButtons.innerHTML = [2026, 2027]
    .map(
      (year) => `
        <button type="button" class="year-button${year === state.selectedYear ? " active" : ""}" data-year="${year}">
          ${year}
        </button>
      `
    )
    .join("");
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
}

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
      {
        ...item,
        paidEmissions: Number(item.paidEmissions),
      },
    ])
  );
  state.mapData.countriesCanonical = state.mapData.countries.map(canonicalCountryName);
  state.mapData.countryNameByCanonical = Object.fromEntries(
    state.mapData.countries.map((country) => [canonicalCountryName(country), country])
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
}

function buildGeoJsonLayer() {
  state.geojsonLayer = L.geoJSON(state.geojson, {
    bubblingMouseEvents: false,
    interactive: true,
    renderer: state.countryRenderer,
    smoothFactor: 0.8,
    style: (feature) => getFeatureStyle(feature),
    onEachFeature: (feature, layer) => {
      const featureName = getFeatureName(feature);
      state.featureLayers.set(canonicalCountryName(featureName), layer);
      layer.on({
        mouseover: (event) => {
          if (state.hoveredLayer && state.hoveredLayer !== event.target) {
            applyLayerStyle(state.hoveredLayer);
          }
          state.hoveredCountry = getFeatureName(event.target.feature);
          state.hoveredLayer = event.target;
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
          queueTooltipRender();
        },
        click: async (event) => {
          stopMapClick(event);
          await selectCountry(getFeatureName(event.target.feature));
        },
      });
    },
  }).addTo(state.map);
}

function stopMapClick(event) {
  state.suppressMapClickUntil = Date.now() + 350;
  if (!event.originalEvent) {
    return;
  }
  L.DomEvent.stop(event.originalEvent);
}

function getFeatureName(feature) {
  return feature?.properties?.ADMIN || feature?.properties?.name || "";
}

function getFeatureStyle(feature) {
  const country = getFeatureName(feature);
  const canonical = canonicalCountryName(country);
  const value = getMapValue(country);
  const color = getColor(value);
  const isHovered = state.hoveredCountry && canonicalCountryName(state.hoveredCountry) === canonical;

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
  if (!state.geojsonLayer) {
    return;
  }
  state.geojsonLayer.eachLayer((layer) => {
    layer.setStyle(getFeatureStyle(layer.feature));
  });
}

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
    elements.countrySearchResults.innerHTML = "";
    return;
  }

  elements.countrySearchResults.classList.remove("hidden");
  elements.countrySearchResults.innerHTML = results
    .map((country) => {
      const mapValue = getMapValue(country);
      return `
        <button class="search-result" type="button" data-country="${country}">
          <span>${country}</span>
          <small>${mapValue === null ? "No map value" : formatEmissions(mapValue)}</small>
        </button>
      `;
    })
    .join("");

  elements.countrySearchResults.querySelectorAll(".search-result").forEach((button) => {
    button.addEventListener("click", async () => {
      await selectCountry(button.dataset.country);
      elements.countrySearchResults.classList.add("hidden");
    });
  });
}

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

function queueTooltipRender() {
  if (state.tooltipRenderQueued) {
    return;
  }
  state.tooltipRenderQueued = true;
  window.requestAnimationFrame(() => {
    state.tooltipRenderQueued = false;
    renderTooltip();
  });
}

function renderTooltip() {
  if (!state.hoveredCountry) {
    elements.hoverTooltip.classList.add("hidden");
    elements.hoverTooltip.innerHTML = "";
    return;
  }

  const mapEntry = getMapEntry(state.hoveredCountry);
  const mapValue = mapEntry?.paidEmissions ?? null;
  const hasCountry = countryHasAnyData(state.hoveredCountry);
  const cost = formatCurrency(mapValue);
  const dotColor = getColor(mapValue);

  elements.hoverTooltip.classList.remove("hidden");
  elements.hoverTooltip.style.left = `${state.mouse.x + 16}px`;
  elements.hoverTooltip.style.top = `${state.mouse.y - 18}px`;
  elements.hoverTooltip.innerHTML = `
    <h3>${state.hoveredCountry}</h3>
    <div class="tooltip-row">
      <span class="tooltip-dot" style="background:${dotColor};"></span>
      <span>${mapValue === null ? "No map value" : formatEmissions(mapValue)}</span>
    </div>
    ${mapEntry ? `<div class="tooltip-row"><span>Production Route: ${mapEntry.sourceLabel}</span></div>` : ""}
    ${cost ? `<div class="tooltip-row"><span>${cost}</span></div>` : ""}
    ${
      !hasCountry
        ? `<div class="tooltip-row"><span>No country data exists for this code/year.</span></div>`
        : ""
    }
  `;
}

function renderCountryDetail() {
  if (!state.countryDetail) {
    elements.detailCard.classList.add("hidden");
    elements.detailCard.innerHTML = "";
    return;
  }

  const heroValue = state.countryDetail.displayValue ?? state.countryDetail.routes[0]?.paidEmissions ?? null;
  const heroColor = getColor(heroValue);
  const mapCost = formatCurrency(heroValue);

  elements.detailCard.classList.remove("hidden");
  elements.detailCard.innerHTML = `
    <div class="detail-header">
      <button class="detail-close" type="button" aria-label="Close country detail">x</button>
      <h2>${state.countryDetail.country}</h2>
      <p class="detail-subtitle">CN code ${state.countryDetail.cnCode} · Year ${state.countryDetail.year}</p>
    </div>
    <div class="detail-body">
      <div class="detail-summary">
        <div class="value-chip" style="background:${heroColor};">
          ${heroValue === null ? "N/A" : Number(heroValue).toFixed(2)}
        </div>
        <div class="value-meta">
          <strong>${heroValue === null ? "No data" : Number(heroValue).toFixed(2)}</strong>
          <p>tCO2/ton shown on the map for this country</p>
          ${mapCost ? `<p>${mapCost}</p>` : ""}
        </div>
      </div>
      <p class="detail-note">
        ${
          state.countryDetail.mirroredFrom
            ? `This country mirrors <strong>${state.countryDetail.mirroredFrom}</strong> for map value and routes.<br />`
            : ""
        }
        ${
          state.countryDetail.displaySourceType === "average_routes"
            ? "This country has multiple production routes, so the map uses their average value."
            : ""
        }
      </p>
      <div class="routes-table">
        ${state.countryDetail.routes
          .map((route) => {
            const routeExplanation = getRouteExplanation(route.value);
            return `
              <div class="route-row">
                <div class="route-name">
                  <span>${formatRouteLabel(route.label)}</span>
                  ${route.isDisplayedValue ? '<span class="route-badge">Route</span>' : ""}
                </div>
                <div class="route-description">${routeExplanation || "No description available"}</div>
                <div class="route-metric">
                  <strong>${Number(route.paidEmissions).toFixed(2)}</strong>
                  <span>tCO2/ton</span>
                </div>
              </div>
            `;
          })
          .join("")}
      </div>
    </div>
  `;

  elements.detailCard.querySelector(".detail-close").addEventListener("click", () => {
    clearSelectedCountry();
  });
}

window.addEventListener("load", () => {
  init().catch((error) => {
    console.error(error);
    if (elements.legendMin) {
      elements.legendMin.textContent = "!";
    }
    if (elements.legendMax) {
      elements.legendMax.textContent = "!";
    }
  });
});
