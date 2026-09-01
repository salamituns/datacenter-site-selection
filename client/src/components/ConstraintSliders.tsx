import React from "react";
import { RotateCcw } from "lucide-react";
import { WeightFactors } from "@/types/parcel";

interface ConstraintSlidersProps {
  weights: WeightFactors;
  onWeightChange: (weights: WeightFactors) => void;
  onResetWeights: () => void;
}

const BRAND = "#5E6AD2";

const SLIDERS: {
  key: keyof WeightFactors;
  label: string;
}[] = [
  { key: "powerWeight", label: "Power Proximity" },
  { key: "waterWeight", label: "Water Availability" },
  { key: "riskWeight", label: "Geological Risk" },
  { key: "climateWeight", label: "Ambient Cooling" },
];

export const ConstraintSliders: React.FC<ConstraintSlidersProps> = ({
  weights,
  onWeightChange,
  onResetWeights,
}) => {
  const totalWeight =
    weights.powerWeight + weights.waterWeight + weights.riskWeight + weights.climateWeight || 1;

  const segments = [
    { key: "power", label: "Power", value: weights.powerWeight, className: "bg-power" },
    { key: "water", label: "Water", value: weights.waterWeight, className: "bg-water" },
    { key: "risk", label: "Risk", value: weights.riskWeight, className: "bg-danger" },
    { key: "climate", label: "Climate", value: weights.climateWeight, className: "bg-brand-400" },
  ];

  return (
    <section className="rounded-xl border border-border bg-surface">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <h3 className="text-[13px] font-semibold tracking-tight text-foreground">
          Scoring Weights
        </h3>
        <button
          onClick={onResetWeights}
          aria-label="Reset weights to defaults"
          title="Reset to defaults"
          className="flex h-6 w-6 items-center justify-center rounded-md text-muted transition-colors hover:bg-surface-raised hover:text-foreground"
        >
          <RotateCcw className="h-3.5 w-3.5" />
        </button>
      </div>

      <div className="space-y-4 px-4 py-4">
        {SLIDERS.map((slider) => {
          const value = weights[slider.key];
          return (
            <div key={slider.key}>
              <div className="mb-2 flex items-center justify-between">
                <label className="text-xs font-medium text-foreground">{slider.label}</label>
                <span className="font-mono text-xs tabular-nums text-muted">{value}%</span>
              </div>
              <input
                type="range"
                min={0}
                max={100}
                step={5}
                value={value}
                aria-label={slider.label}
                onChange={(e) =>
                  onWeightChange({ ...weights, [slider.key]: Number(e.target.value) })
                }
                style={{
                  background: `linear-gradient(to right, ${BRAND} ${value}%, rgb(var(--border)) ${value}%)`,
                }}
              />
            </div>
          );
        })}
      </div>

      {/* Weight distribution */}
      <div className="border-t border-border px-4 py-3">
        <div className="flex h-1.5 w-full gap-px overflow-hidden rounded-full">
          {segments.map(
            (s) =>
              s.value > 0 && (
                <div
                  key={s.key}
                  className={s.className}
                  style={{ width: `${(s.value / totalWeight) * 100}%` }}
                />
              )
          )}
        </div>
        <div className="mt-2.5 flex items-center justify-between">
          <div className="flex items-center gap-3">
            {segments.map((s) => (
              <span key={s.key} className="flex items-center gap-1.5 text-[10px] text-muted">
                <span className={`h-1.5 w-1.5 rounded-full ${s.className}`} />
                {s.label}
              </span>
            ))}
          </div>
          <span className="text-[10px] text-muted">Normalized to 100%</span>
        </div>
      </div>
    </section>
  );
};
