/** Country-name normalization between the GeoJSON layer and the API. */

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

/** Territories whose map data comes from another country's records. */
const COUNTRY_DATA_OVERRIDES = {
  "northern cyprus": {
    sourceCountry: "Turkey",
    displayCountry: "Northern Cyprus",
  },
};

export function normalizeCountryName(value) {
  return (value || "")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/&/g, "and")
    .replace(/[().,'`’/-]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

export function canonicalCountryName(value) {
  const normalized = normalizeCountryName(value);
  return COUNTRY_ALIASES[normalized] || normalized;
}

export function getCountryDataOverride(country) {
  const normalized = normalizeCountryName(country);
  const canonical = canonicalCountryName(country);
  return COUNTRY_DATA_OVERRIDES[normalized] || COUNTRY_DATA_OVERRIDES[canonical] || null;
}

export function getDataLookupCanonical(country) {
  const override = getCountryDataOverride(country);
  return canonicalCountryName(override?.sourceCountry || country);
}
