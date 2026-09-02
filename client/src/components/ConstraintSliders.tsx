import React from "react";
import { RotateCcw } from "lucide-react";
import { WeightFactors } from "@/types/parcel";

interface ConstraintSlidersProps {
  weights: WeightFactors;
  onWeightChange: (weights: WeightFactors) => void;
  onResetWeights: () => void;
  /** Minimum composite score for Prime Zone candidacy (worker baseline: 60). */
  primeThreshold: number;
  onPrimeThresholdChange: (threshold: number) => void;
}

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
  primeThreshold,
  onPrimeThresholdChange,
}) => {
  const totalWeight =
    weights.powerWeight + weights.waterWeight + weights.riskWeight + weights.climateWeight || 1;

  const segments = [
    {
      key: "power",
      label: "PWR",
      value: weights.powerWeight,
      className: "bg-power dark:bg-power-night",
    },
    {
      key: "water",
      label: "WTR",
      value: weights.waterWeight,
      className: "bg-water dark:bg-water-night",
    },
    {
      key: "risk",
      label: "RSK",
      value: weights.riskWeight,
      className: "bg-danger dark:bg-danger-night",
    },
    {
      key: "climate",
      label: "CLM",
      value: weights.climateWeight,
      className: "bg-accent-500",
    },
  ];

  return (
    <section className="rounded-[2px] border border-border-strong bg-surface">
      <div className="flex items-center justify-between border-b border-border px-4 py-2.5">
        <h3 className="font-mono text-[10px] uppercase tracking-[0.16em] text-muted">
          02 — Scoring Weights
        </h3>
        <button
          onClick={onResetWeights}
          aria-label="Reset weights to defaults"
          title="Reset to defaults"
          className="flex h-5 w-5 items-center justify-center text-muted transition-colors hover:bg-surface-raised hover:text-foreground"
        >
          <RotateCcw className="h-3 w-3" />
        </button>
      </div>

      <div className="space-y-4 px-4 py-4">
        {SLIDERS.map((slider) => {
          const value = weights[slider.key];
          return (
            <div key={slider.key}>
              <div className="mb-2 flex items-baseline justify-between">
                <label className="text-xs font-medium text-foreground">{slider.label}</label>
                <span className="font-mono text-[11px] tabular-nums text-muted">
                  {value}%
                </span>
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
                  background: `linear-gradient(to right, rgb(var(--accent)) ${value}%, rgb(var(--border-strong)) ${value}%)`,
                }}
              />
            </div>
          );
        })}
      </div>

      {/* Weight distribution — stacked rule */}
      <div className="border-t border-border px-4 py-3">
        <div className="flex h-1.5 w-full gap-[2px]">
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
        <div className="mt-2 flex items-center justify-between">
          <div className="flex items-center gap-3">
            {segments.map((s) => (
              <span
                key={s.key}
                className="flex items-center gap-1 font-mono text-[9px] uppercase tracking-[0.1em] text-muted"
              >
                <span className={`h-1.5 w-1.5 ${s.className}`} />
                {s.label}
              </span>
            ))}
          </div>
          <span className="font-mono text-[9px] uppercase tracking-[0.1em] text-muted">
            Norm. 100%
          </span>
        </div>
      </div>

      {/* Stringency threshold — prime zone candidacy cutoff.
          Defaults to the Python worker's ingestion baseline (60) so the
          initial page load matches the persisted survey exactly. */}
      <div className="border-t border-border px-4 py-4">
        <div className="mb-2 flex items-baseline justify-between">
          <label className="text-xs font-medium text-foreground">Stringency Threshold</label>
          <span className="font-mono text-[11px] tabular-nums text-muted">
            ≥ {primeThreshold}
          </span>
        </div>
        <input
          type="range"
          min={50}
          max={90}
          step={1}
          value={primeThreshold}
          aria-label="Stringency Threshold"
          onChange={(e) => onPrimeThresholdChange(Number(e.target.value))}
          style={{
            background: `linear-gradient(to right, rgb(var(--accent)) ${
              ((primeThreshold - 50) / 40) * 100
            }%, rgb(var(--border-strong)) ${((primeThreshold - 50) / 40) * 100}%)`,
          }}
        />
        <p className="mt-2 font-mono text-[9px] uppercase tracking-[0.1em] text-muted">
          Min composite score for Prime Zone candidacy · baseline 60
        </p>
      </div>
    </section>
  );
};
