import type { StyleSpecification } from "maplibre-gl";

export const BASEMAP_STYLE: StyleSpecification = {
  version: 8,
  sources: {
    esri: {
      type: "raster",
      tiles: [
        "https://services.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}",
      ],
      tileSize: 256,
      attribution:
        "© Esri, HERE, Garmin, OpenStreetMap contributors, and the GIS user community",
    },
  },
  layers: [{ id: "esri", type: "raster", source: "esri" }],
};
