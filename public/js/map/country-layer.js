/**
 * Country shapes drawn once as SVG and scaled by the browser when zooming.
 *
 * Leaflet's vector layers re-project every border point and rebuild every path
 * after each zoom, which freezes the page for a noticeable moment with detailed
 * borders (longest when zooming out, because every country is visible). Here
 * each path is built once in Web Mercator pixel space and placed in an
 * `L.svgOverlay`: a zoom only resizes the <svg>, the browser redraws the same
 * vectors, and the page stays responsive.
 */

const SVG_NS = "http://www.w3.org/2000/svg";

/** Leaflet's Web Mercator latitude limit; the overlay spans exactly one world square. */
export const MAX_LATITUDE = 85.0511287798;

/**
 * World width in path units: 1 unit = 0.1 px at zoom 6, the map's maximum zoom,
 * so integer coordinates keep sub-pixel precision at every zoom level.
 */
export const WORLD_SIZE = 256 * 2 ** 6 * 10;

const DEGREES = Math.PI / 180;

/** Web Mercator position in `worldSize` units (the formula Leaflet's EPSG:3857 CRS uses). */
export function projectLngLat(lng, lat, worldSize = WORLD_SIZE) {
  const clampedLat = Math.max(Math.min(MAX_LATITUDE, lat), -MAX_LATITUDE);
  const sin = Math.sin(clampedLat * DEGREES);
  return [
    (lng / 360 + 0.5) * worldSize,
    (0.5 - Math.log((1 + sin) / (1 - sin)) / (4 * Math.PI)) * worldSize,
  ];
}

function appendPair(data, dx, dy, first) {
  const xSeparator = first || dx < 0 ? "" : " ";
  const ySeparator = dy < 0 ? "" : " ";
  return `${data}${xSeparator}${dx}${ySeparator}${dy}`;
}

/**
 * Compact SVG path data for a GeoJSON Polygon or MultiPolygon: integer world
 * units, one relative line command per ring, repeated points dropped.
 */
export function geometryToPathData(geometry, worldSize = WORLD_SIZE) {
  const polygons =
    geometry?.type === "Polygon"
      ? [geometry.coordinates]
      : geometry?.type === "MultiPolygon"
        ? geometry.coordinates
        : [];
  let data = "";
  for (const polygon of polygons) {
    for (const ring of polygon) {
      let ringData = "";
      let points = 0;
      let lastX = 0;
      let lastY = 0;
      // GeoJSON rings repeat the first point at the end; "z" closes the ring instead.
      const end = ring.length > 1 && ring[0][0] === ring.at(-1)[0] && ring[0][1] === ring.at(-1)[1]
        ? ring.length - 1
        : ring.length;
      for (let index = 0; index < end; index += 1) {
        const [px, py] = projectLngLat(ring[index][0], ring[index][1], worldSize);
        const x = Math.round(px);
        const y = Math.round(py);
        if (points === 0) {
          ringData = `M${x} ${y}l`;
        } else if (x === lastX && y === lastY) {
          continue;
        } else {
          ringData = appendPair(ringData, x - lastX, y - lastY, points === 1);
        }
        lastX = x;
        lastY = y;
        points += 1;
      }
      if (points >= 3) {
        data += `${ringData}z`;
      }
    }
  }
  return data;
}

/**
 * `L.svgOverlay` resizes its <svg> on every "zoom" event, which a pinch gesture
 * fires once per frame; resizing forces a full redraw each time. Here the
 * drawing is only scaled while the gesture runs and resized once when it ends.
 */
let CountryOverlayClass = null;

function createOverlay(svg, bounds, options) {
  CountryOverlayClass ??= L.SVGOverlay.extend({
    getEvents() {
      const events = { zoom: this._scaleToZoom, zoomend: this._reset, viewreset: this._reset };
      if (this._zoomAnimated) {
        events.zoomanim = this._animateZoom;
      }
      return events;
    },
    _reset() {
      L.SVGOverlay.prototype._reset.call(this);
      this._drawnZoom = this._map.getZoom();
    },
    _scaleToZoom() {
      const map = this._map;
      const scale = map.getZoomScale(map.getZoom(), this._drawnZoom);
      L.DomUtil.setTransform(this._image, map.latLngToLayerPoint(this._bounds.getNorthWest()), scale);
    },
  });
  return new CountryOverlayClass(svg, bounds, options);
}

/**
 * Build the overlay. Returns the Leaflet layer plus lookups between features and
 * their <path> elements; styling and events are left to the caller.
 */
export function createCountryLayer(features) {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", `0 0 ${WORLD_SIZE} ${WORLD_SIZE}`);
  svg.setAttribute("preserveAspectRatio", "none");

  const pathByFeature = new Map();
  const featureByPath = new WeakMap();
  const fragment = document.createDocumentFragment();
  for (const feature of features) {
    const data = geometryToPathData(feature.geometry);
    if (!data) {
      continue;
    }
    const path = document.createElementNS(SVG_NS, "path");
    path.setAttribute("d", data);
    path.setAttribute("class", "country-path leaflet-interactive");
    path.setAttribute("fill-rule", "evenodd");
    path.setAttribute("stroke-linejoin", "round");
    path.setAttribute("stroke-linecap", "round");
    path.setAttribute("vector-effect", "non-scaling-stroke");
    pathByFeature.set(feature, path);
    featureByPath.set(path, feature);
    fragment.append(path);
  }
  svg.append(fragment);

  const layer = createOverlay(
    svg,
    [
      [-MAX_LATITUDE, -180],
      [MAX_LATITUDE, 180],
    ],
    { className: "country-layer" },
  );
  return {
    layer,
    svg,
    pathFor: (feature) => pathByFeature.get(feature) ?? null,
    featureFor: (element) => featureByPath.get(element?.closest?.(".country-path")) ?? null,
    features: () => pathByFeature.keys(),
  };
}

/** Apply a Leaflet-style path style object to a <path>. */
export function setPathStyle(path, style) {
  path.setAttribute("fill", style.fillColor);
  path.setAttribute("fill-opacity", String(style.fillOpacity));
  path.setAttribute("stroke", style.color);
  path.setAttribute("stroke-opacity", String(style.opacity));
  path.setAttribute("stroke-width", String(style.weight));
}
