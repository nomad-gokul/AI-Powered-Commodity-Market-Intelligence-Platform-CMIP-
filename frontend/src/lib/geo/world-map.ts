import * as echarts from "echarts";
import { feature } from "topojson-client";
import type { Topology, GeometryCollection } from "topojson-specification";
import type { FeatureCollection, Geometry } from "geojson";
import worldTopology from "world-atlas/countries-110m.json";

let registered = false;

/**
 * Registers a plain landmass silhouette (no per-country choropleth data —
 * see world-commodity-map.tsx for why activity/risk render as a geo
 * effectScatter layer instead of per-country fills) under the map name
 * "world". Idempotent; safe to call from every render.
 */
export function ensureWorldMapRegistered(): void {
  if (registered) return;
  const topology = worldTopology as unknown as Topology;
  const countries = feature(
    topology,
    topology.objects.countries as GeometryCollection
  ) as unknown as FeatureCollection<Geometry>;
  // echarts' registerMap expects its own (stricter, non-null `properties`)
  // GeoJSON type; every feature here genuinely has a `{ name: string }`
  // properties object, so this cast is bridging two GeoJSON type
  // definitions that describe the same real shape, not suppressing a
  // real mismatch.
  echarts.registerMap("world", countries as unknown as Parameters<typeof echarts.registerMap>[1]);
  registered = true;
}
