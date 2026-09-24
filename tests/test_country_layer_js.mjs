import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";

import {
  MAX_LATITUDE,
  WORLD_SIZE,
  geometryToPathData,
  projectLngLat,
} from "../public/js/map/country-layer.js";

// Leaflet's EPSG:3857 pixel position at zoom z (SphericalMercator + transformation).
function leafletPoint(lng, lat, zoom) {
  const R = 6378137;
  const d = Math.PI / 180;
  const clamped = Math.max(Math.min(MAX_LATITUDE, lat), -MAX_LATITUDE);
  const sin = Math.sin(clamped * d);
  const scale = 256 * 2 ** zoom;
  const k = 0.5 / (Math.PI * R);
  return [
    scale * (k * R * lng * d + 0.5),
    scale * (-k * ((R * Math.log((1 + sin) / (1 - sin))) / 2) + 0.5),
  ];
}

test("projection matches Leaflet's Web Mercator pixels at the maximum zoom", () => {
  for (const [lng, lat] of [
    [0, 0],
    [23.72, 37.98],
    [-74.0, 40.7],
    [179.9, -85.2],
    [13.0, 66.5],
  ]) {
    const [x, y] = projectLngLat(lng, lat);
    const [lx, ly] = leafletPoint(lng, lat, 6);
    assert.ok(Math.abs(x / 10 - lx) < 1e-6, `x for ${lng},${lat}`);
    assert.ok(Math.abs(y / 10 - ly) < 1e-6, `y for ${lng},${lat}`);
  }
});

test("the world square spans the whole overlay", () => {
  assert.deepEqual(projectLngLat(-180, MAX_LATITUDE).map(Math.round), [0, 0]);
  assert.deepEqual(projectLngLat(180, -MAX_LATITUDE).map(Math.round), [WORLD_SIZE, WORLD_SIZE]);
});

test("path data uses one relative command per ring and drops repeated points", () => {
  const worldSize = 360;
  const data = geometryToPathData(
    {
      type: "Polygon",
      coordinates: [
        [
          [0, 0],
          [10, 0],
          [10, 0],
          [10, -10],
          [0, 0],
        ],
      ],
    },
    worldSize,
  );
  assert.equal(data, "M180 180l10 0 0 10z");
});

test("negative deltas need no separator and each MultiPolygon ring is closed", () => {
  const data = geometryToPathData(
    {
      type: "MultiPolygon",
      coordinates: [
        [[[0, 0], [-10, 0], [-10, 10], [0, 0]]],
        [[[20, 0], [30, 0], [30, -10], [20, 0]]],
      ],
    },
    360,
  );
  assert.equal(data, "M180 180l-10 0 0-10zM200 180l10 0 0 10z");
});

test("degenerate rings and unsupported geometries produce no path", () => {
  assert.equal(geometryToPathData({ type: "Polygon", coordinates: [[[0, 0], [0, 0], [0, 0]]] }, 360), "");
  assert.equal(geometryToPathData({ type: "Point", coordinates: [0, 0] }, 360), "");
  assert.equal(geometryToPathData(null, 360), "");
});

test("every bundled country produces a drawable path", async () => {
  const { readFile } = await import("node:fs/promises");
  const require = createRequire(import.meta.url);
  const topojson = require("../public/vendor/topojson-client.min.js");
  const topology = JSON.parse(await readFile(new URL("../public/countries.topojson", import.meta.url)));
  const { features } = topojson.feature(topology, topology.objects.countries);
  const empty = features.filter((feature) => !geometryToPathData(feature.geometry));
  assert.deepEqual(empty.map((feature) => feature.properties.name), []);
});
