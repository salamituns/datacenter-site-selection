import React from "react";
import { Zap, Droplets, ShieldAlert, ThermometerSnowflake, Grid2x2, Scan } from "lucide-react";
import { LayerVisibility } from "@/types/parcel";

interface LayerControlsProps {
  layers: LayerVisibility;
  onToggleLayer: (layerKey: keyof LayerVisibility) => void;
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
    description: "115 kV / 230 kV / 500 kV transmission",
    source: "HIFLD",
    icon: <Zap className="h-4 w-4 text-power" />,
  },
  {
    key: "waterAquifers",
    label: "Water & Aquifer Depth",
    description: "Groundwater and surface discharge",
    source: "USGS NWIS",
    icon: <Droplets className="h-4 w-4 text-water" />,
  },
  {
    key: "seismicHazard",
    label: "Hazard & Seismic Risk",
    description: "Peak ground acceleration, flood",
    source: "FEMA NRI",
    icon: <ShieldAlert className="h-4 w-4 text-danger" />,
  },
  {
    key: "climateCDD",
    label: "Climate & Cooling",
    description: "Annual cooling degree days",
    source: "NOAA NCEI",
    icon: <ThermometerSnowflake className="h-4 w-4 text-brand-300" />,
  },
  {
    key: "primeClusters",
    label: "Prime Development Zones",
    description: "Contiguous high-suitability clusters",
    source: "DBSCAN",
    icon: <Scan className="h-4 w-4 text-brand-400" />,
  },
  {
    key: "parcelGrid",
    label: "Parcel Grid",
    description: "10 km² fishnet boundaries",
    source: "PostGIS",
    icon: <Grid2x2 className="h-4 w-4 text-muted" />,
  },
];

function ToggleSwitch({ checked }: { checked: boolean }) {
  return (
    <span
      className={`relative inline-flex h-[18px] w-[32px] shrink-0 items-center rounded-full border transition-colors duration-150 ${
        checked ? "border-brand-500 bg-brand-500" : "border-border-strong bg-transparent"
      }`}
    >
      <span
        className={`absolute h-3 w-3 rounded-full transition-transform duration-150 ${
          checked ? "translate-x-[15px] bg-white" : "translate-x-[2px] bg-muted"
        }`}
      />
    </span>
  );
}

export const LayerControls: React.FC<LayerControlsProps> = ({ layers, onToggleLayer }) => {
  const visibleCount = Object.values(layers).filter(Boolean).length;

  return (
    <section className="rounded-xl border border-border bg-surface">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <h3 className="text-[13px] font-semibold tracking-tight text-foreground">Layers</h3>
        <span className="text-[11px] tabular-nums text-muted">
          {visibleCount} of {LAYER_CONFIGS.length}
        </span>
      </div>

      <div className="p-1.5">
        {LAYER_CONFIGS.map((layer) => {
          const isVisible = layers[layer.key];
          return (
            <button
              key={layer.key}
              onClick={() => onToggleLayer(layer.key)}
              aria-pressed={isVisible}
              className="group flex w-full items-center justify-between gap-3 rounded-lg px-2.5 py-2 text-left transition-colors hover:bg-surface-raised"
            >
              <div className={`flex min-w-0 items-center gap-2.5 transition-opacity ${isVisible ? "" : "opacity-45"}`}>
                {layer.icon}
                <div className="min-w-0">
                  <div className="truncate text-xs font-medium text-foreground">
                    {layer.label}
                  </div>
                  <div className="mt-0.5 flex items-center gap-1.5">
                    <span className="text-[10px] font-medium uppercase tracking-wide text-muted">
                      {layer.source}
                    </span>
                    <span className="text-[10px] text-muted">·</span>
                    <span className="truncate text-[10px] text-muted">{layer.description}</span>
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
