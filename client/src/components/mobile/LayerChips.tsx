"use client";

import React from "react";
import {
  Zap,
  Droplets,
  ShieldAlert,
  ThermometerSnowflake,
  Grid2x2,
  Stamp,
} from "lucide-react";
import { LayerVisibility } from "@/types/parcel";

interface LayerChipsProps {
  layers: LayerVisibility;
  onToggleLayer: (layerKey: keyof LayerVisibility) => void;
}

const CHIPS: {
  key: keyof LayerVisibility;
  short: string;
  icon: React.ReactNode;
}[] = [
  {
    key: "powerGrid",
    short: "Power",
    icon: <Zap className="h-3.5 w-3.5 dark:text-power-night" />,
  },
  {
    key: "waterAquifers",
    short: "Water",
    icon: <Droplets className="h-3.5 w-3.5 text-water dark:text-water-night" />,
  },
  {
    key: "seismicHazard",
    short: "Seismic",
    icon: <ShieldAlert className="h-3.5 w-3.5 text-danger dark:text-danger-night" />,
  },
  {
    key: "climateCDD",
    short: "Climate",
    icon: <ThermometerSnowflake className="h-3.5 w-3.5 text-muted" />,
  },
  {
    key: "primeClusters",
    short: "Prime",
    icon: <Stamp className="h-3.5 w-3.5 text-accent-600 dark:text-accent-400" />,
  },
  {
    key: "parcelGrid",
    short: "Grid",
    icon: <Grid2x2 className="h-3.5 w-3.5 text-muted" />,
  },
];

/** Horizontal-scrolling layer pills — active state reads as stamped ink. */
export const LayerChips: React.FC<LayerChipsProps> = ({ layers, onToggleLayer }) => {
  return (
    <div
      role="group"
      aria-label="Map layers"
      className="scrollbar-hide flex gap-2 overflow-x-auto border-b border-border px-3 py-2"
    >
      {CHIPS.map((chip) => {
        const active = layers[chip.key];
        return (
          <button
            key={chip.key}
            onClick={() => onToggleLayer(chip.key)}
            aria-pressed={active}
            className={`flex shrink-0 items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium transition-colors ${
              active
                ? "border-accent-600/70 bg-accent-600/10 text-accent-700 dark:border-accent-400/60 dark:bg-accent-400/10 dark:text-accent-300"
                : "border-border-strong text-muted active:bg-surface-raised"
            }`}
          >
            <span className={active ? "" : "opacity-50"}>{chip.icon}</span>
            {chip.short}
          </button>
        );
      })}
    </div>
  );
};
