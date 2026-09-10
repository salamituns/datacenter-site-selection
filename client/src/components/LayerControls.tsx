import React from "react";
import {
  Zap,
  Droplets,
  ShieldAlert,
  ThermometerSnowflake,
  Grid2x2,
  Stamp,
  LandPlot,
} from "lucide-react";
import { LayerVisibility } from "@/types/parcel";

interface LayerControlsProps {
  layers: LayerVisibility;
  onToggleLayer: (layerKey: keyof LayerVisibility) => void;
  /** Region in view. The parcel layer names the county that publishes it,
   *  which differs per region and does not exist in all of them. */
  selectedRegion?: string;
}

interface LayerConfig {
  key: keyof LayerVisibility;
  label: string;
  description: string;
  source: string;
  icon: React.ReactNode;
}

const LAYER_CONFIGS: LayerConfig[] = [
  {
    key: "powerGrid",
    label: "Power Grid & Substations",
    description: "115 / 230 / 500 kV transmission",
    source: "HIFLD",
    icon: <Zap className="h-3.5 w-3.5 dark:text-power-night" />,
  },
  {
    key: "waterAquifers",
    label: "Water & Aquifer Depth",
    description: "Groundwater & discharge",
    source: "USGS NWIS",
    icon: <Droplets className="h-3.5 w-3.5 text-water dark:text-water-night" />,
  },
  {
    key: "seismicHazard",
    label: "Hazard & Seismic Risk",
    description: "Peak ground acceleration",
    source: "FEMA NRI",
    icon: <ShieldAlert className="h-3.5 w-3.5 text-danger dark:text-danger-night" />,
  },
  {
    key: "climateCDD",
    label: "Climate & Cooling",
    description: "Cooling degree days",
    source: "NOAA NCEI",
    icon: <ThermometerSnowflake className="h-3.5 w-3.5 text-muted" />,
  },
  {
    key: "primeClusters",
    label: "Prime Development Zones",
    description: "Contiguous suitability clusters",
    source: "DBSCAN",
    icon: <Stamp className="h-3.5 w-3.5 text-accent-600 dark:text-accent-400" />,
  },
  {
    key: "parcelGrid",
    label: "Parcel Grid",
    description: "10 km² fishnet boundaries",
    source: "PostGIS",
    icon: <Grid2x2 className="h-3.5 w-3.5 text-muted" />,
  },
  {
    key: "qualifiedParcels",
    label: "Qualified Parcels",
    description: "Cadastral gates & verdicts",
    // Filled per region — see PARCEL_SOURCE.
    source: "",
    icon: <LandPlot className="h-3.5 w-3.5 text-success dark:text-success-night" />,
  },
];

/**
 * Who publishes the cadastre, by region. Each jurisdiction is a separate
 * adapter against a separate authority, so the layer names the one it is
 * actually reading rather than a single county that happened to be first.
 *
 * A region absent here has no parcel pilot: the layer is empty there, and
 * saying so is more useful than an unexplained blank map.
 */
const PARCEL_SOURCE: Record<string, string> = {
  "VA-LOUDOUN": "Loudoun County GIS",
  "OH-FRANKLIN": "Franklin County Auditor",
  "OH-LICKING": "Licking County Auditor",
  "TX-TAYLOR": "Taylor CAD",
};

/** Square instrument switch — a slide plate, not a pill. */
function ToggleSwitch({ checked }: { checked: boolean }) {
  return (
    <span
      className={`relative inline-flex h-4 w-7 shrink-0 items-center rounded-[2px] border transition-colors duration-150 ${
        checked
          ? "border-accent-600 bg-accent-600 dark:border-accent-400 dark:bg-accent-400/15"
          : "border-border-strong bg-transparent"
      }`}
    >
      <span
        className={`absolute h-3 w-2.5 rounded-[1px] transition-transform duration-150 ${
          checked
            ? "translate-x-[15px] bg-surface dark:bg-accent-400"
            : "translate-x-[2px] bg-border-strong"
        }`}
      />
    </span>
  );
}

export const LayerControls: React.FC<LayerControlsProps> = ({
  layers,
  onToggleLayer,
  selectedRegion,
}) => {
  const visibleCount = Object.values(layers).filter(Boolean).length;

  return (
    <section className="rounded-[2px] border border-border-strong bg-surface">
      <div className="flex items-baseline justify-between border-b border-border px-4 py-2.5">
        <h3 className="font-mono text-[10px] uppercase tracking-[0.16em] text-muted">
          Layers
        </h3>
        <span className="font-mono text-[10px] tabular-nums text-muted">
          {visibleCount}/{LAYER_CONFIGS.length}
        </span>
      </div>

      <div className="divide-y divide-border">
        {LAYER_CONFIGS.map((layer) => {
          const isVisible = layers[layer.key];
          return (
            <button
              key={layer.key}
              onClick={() => onToggleLayer(layer.key)}
              aria-pressed={isVisible}
              className="group flex w-full items-center justify-between gap-3 px-4 py-2.5 text-left transition-colors hover:bg-surface-raised/60"
            >
              <div
                className={`flex min-w-0 items-center gap-2.5 transition-opacity ${
                  isVisible ? "" : "opacity-40"
                }`}
              >
                {layer.icon}
                <div className="min-w-0">
                  <div className="truncate text-xs font-medium text-foreground">
                    {layer.label}
                  </div>
                  <div className="mt-0.5 font-mono text-[9.5px] uppercase tracking-[0.08em] text-muted">
                    {layer.key === "qualifiedParcels"
                      ? (PARCEL_SOURCE[selectedRegion ?? ""]
                          ? `${PARCEL_SOURCE[selectedRegion ?? ""]} · ${layer.description}`
                          : "No parcel survey in this region")
                      : `${layer.source} · ${layer.description}`}
                  </div>
                </div>
              </div>
              <ToggleSwitch checked={isVisible} />
            </button>
          );
        })}
      </div>
    </section>
  );
};
