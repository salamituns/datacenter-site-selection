import React, { useEffect } from "react";
import { GridParcel } from "@/types/parcel";
import {
  X,
  Zap,
  Droplets,
  ShieldAlert,
  ThermometerSnowflake,
  Download,
  CheckCircle2,
} from "lucide-react";

interface ParcelDetailModalProps {
  parcel: GridParcel | null;
  onClose: () => void;
}

function scoreTier(score: number): string {
  if (score >= 82) return "Top tier";
  if (score >= 70) return "Strong";
  if (score >= 60) return "Moderate";
  return "Marginal";
}

export const ParcelDetailModal: React.FC<ParcelDetailModalProps> = ({ parcel, onClose }) => {
  useEffect(() => {
    if (!parcel) return;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [parcel, onClose]);

  if (!parcel) return null;

  const fastTrackEligible = parcel.seismic_hazard_pga < 0.08 && parcel.power_distance_miles <= 2;

  const exportDossier = () => {
    const blob = new Blob([JSON.stringify(parcel, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${parcel.grid_id}-dossier.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const stats = [
    {
      label: "Composite",
      value: parcel.composite_score.toFixed(1),
      sub: scoreTier(parcel.composite_score),
    },
    {
      label: "Power",
      value: parcel.power_score.toFixed(0),
      sub: `${parcel.substation_voltage_kv} kV grid`,
    },
    {
      label: "Water",
      value: parcel.water_score.toFixed(0),
      sub: `${parcel.groundwater_depth_ft} ft depth`,
    },
    {
      label: "Capacity",
      value: `${parcel.megawatt_capacity_estimate}`,
      sub: "MW est. build-out",
    },
  ];

  const constraints = [
    {
      icon: <Zap className="h-3.5 w-3.5 text-power" />,
      title: "Power Grid Proximity",
      rows: [
        { label: "115 kV+ line", value: `${parcel.power_distance_miles} mi` },
        {
          label: "Nearest substation",
          value: `${parcel.substation_distance_miles} mi`,
        },
        { label: "Grid operator", value: parcel.grid_operator || "Unknown" },
      ],
    },
    {
      icon: <Droplets className="h-3.5 w-3.5 text-water" />,
      title: "Water Availability",
      rows: [
        { label: "Groundwater table", value: `${parcel.groundwater_depth_ft} ft` },
        { label: "Availability index", value: `${parcel.water_availability_index}/100` },
        { label: "Cooling mode", value: "Closed-loop capable" },
      ],
    },
    {
      icon: <ShieldAlert className="h-3.5 w-3.5 text-danger" />,
      title: "Geological Risk",
      rows: [
        { label: "Seismic (PGA)", value: `${parcel.seismic_hazard_pga}g` },
        { label: "FEMA flood risk", value: `${parcel.flood_risk_score}/100` },
        { label: "Design threshold", value: "< 0.08g PGA" },
      ],
    },
    {
      icon: <ThermometerSnowflake className="h-3.5 w-3.5 text-brand-300" />,
      title: "Ambient Cooling",
      rows: [
        { label: "Cooling degree days", value: `${parcel.cooling_degree_days}` },
        { label: "Economizer hours", value: `${parcel.free_cooling_potential_hours}` },
        { label: "Mean ambient", value: `${parcel.ambient_avg_temp_f}°F` },
      ],
    },
  ];

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={`Parcel ${parcel.grid_id} details`}
      onClick={onClose}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-[2px]"
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="max-h-[85vh] w-full max-w-2xl overflow-y-auto rounded-xl border border-border bg-surface shadow-overlay"
      >
        {/* Header */}
        <div className="flex items-start justify-between border-b border-border px-6 py-4">
          <div>
            <div className="flex items-center gap-2.5">
              <h2 className="font-mono text-sm font-semibold tracking-tight text-foreground">
                {parcel.grid_id}
              </h2>
              {parcel.is_prime_zone && (
                <span className="rounded border border-brand-500/25 bg-brand-500/10 px-1.5 py-0.5 text-[10px] font-medium text-brand-300">
                  {parcel.cluster_label}
                </span>
              )}
            </div>
            <p className="mt-1 text-[11px] text-muted">
              {parcel.county_name} County, {parcel.state_code} · {parcel.area_sq_km.toFixed(1)} km²
              · {parcel.lat.toFixed(4)}, {parcel.lon.toFixed(4)}
            </p>
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-muted transition-colors hover:bg-surface-raised hover:text-foreground"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Key metrics */}
        <div className="grid grid-cols-2 gap-3 px-6 pt-5 sm:grid-cols-4">
          {stats.map((stat) => (
            <div key={stat.label} className="rounded-lg border border-border bg-background p-3">
              <div className="text-[10px] font-medium uppercase tracking-wide text-muted">
                {stat.label}
              </div>
              <div className="mt-1.5 font-mono text-lg font-semibold tabular-nums leading-none text-foreground">
                {stat.value}
              </div>
              <div className="mt-1.5 text-[10px] text-muted">{stat.sub}</div>
            </div>
          ))}
        </div>

        {/* Constraint breakdown */}
        <div className="px-6 py-5">
          <h4 className="text-[11px] font-semibold uppercase tracking-wide text-muted">
            Constraint Analysis
          </h4>
          <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
            {constraints.map((group) => (
              <div key={group.title} className="rounded-lg border border-border bg-background p-3.5">
                <div className="flex items-center gap-2 text-xs font-medium text-foreground">
                  {group.icon}
                  {group.title}
                </div>
                <div className="mt-2.5 space-y-1.5">
                  {group.rows.map((row) => (
                    <div key={row.label} className="flex items-baseline justify-between gap-3">
                      <span className="text-[11px] text-muted">{row.label}</span>
                      <span className="truncate font-mono text-[11px] tabular-nums text-foreground">
                        {row.value}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between border-t border-border px-6 py-4">
          <div
            className={`flex items-center gap-1.5 text-[11px] font-medium ${
              fastTrackEligible ? "text-success" : "text-muted"
            }`}
          >
            <CheckCircle2 className="h-3.5 w-3.5" />
            {fastTrackEligible
              ? "Meets fast-track interconnection profile"
              : "Standard interconnection review"}
          </div>
          <button
            onClick={exportDossier}
            className="flex h-8 items-center gap-2 rounded-md bg-brand-500 px-3 text-xs font-medium text-white transition-colors hover:bg-brand-400"
          >
            <Download className="h-3.5 w-3.5" />
            Export dossier
          </button>
        </div>
      </div>
    </div>
  );
};
