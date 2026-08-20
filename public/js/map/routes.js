/** Production-route labels and human-readable explanations. */

const ROUTE_EXPLANATIONS = {
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

export function formatRouteLabel(route) {
  return route || "Unspecified";
}

export function normalizeRouteCode(route) {
  const normalized = (route || "").replace(/[()]/g, "").trim().toUpperCase();
  if (!normalized) {
    return "";
  }
  const letterMatch = normalized.match(/^[A-Z]+/);
  return letterMatch ? letterMatch[0] : normalized;
}

export function getRouteExplanation(route) {
  return ROUTE_EXPLANATIONS[normalizeRouteCode(route)] || null;
}
