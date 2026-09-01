import React, { useState } from "react";
import { GridParcel } from "@/types/parcel";
import { Search, X } from "lucide-react";

interface RankedParcelsListProps {
  parcels: GridParcel[];
  selectedParcel: GridParcel | null;
  onSelectParcel: (parcel: GridParcel) => void;
}

export const RankedParcelsList: React.FC<RankedParcelsListProps> = ({
  parcels,
  selectedParcel,
  onSelectParcel,
}) => {
  const [searchTerm, setSearchTerm] = useState("");
  const [filterMode, setFilterMode] = useState<"all" | "prime">("all");

  const primeCount = parcels.filter((p) => p.is_prime_zone).length;

  const filteredParcels = parcels.filter((p) => {
    const q = searchTerm.toLowerCase();
    const matchesSearch =
      p.grid_id.toLowerCase().includes(q) ||
      p.county_name.toLowerCase().includes(q) ||
      p.cluster_label.toLowerCase().includes(q);

    if (filterMode === "prime") {
      return matchesSearch && p.is_prime_zone;
    }
    return matchesSearch;
  });

  return (
    <section className="flex h-full min-h-0 flex-col overflow-hidden rounded-[2px] border border-border-strong bg-surface">
      {/* Section head */}
      <div className="border-b border-border px-4 py-2.5">
        <div className="flex items-baseline justify-between">
          <h3 className="font-mono text-[10px] uppercase tracking-[0.16em] text-muted">
            03 — Ranked Parcels
          </h3>
          <span className="font-mono text-[10px] tabular-nums text-muted">
            {filteredParcels.length} shown
          </span>
        </div>

        {/* Search */}
        <div className="relative mt-2.5">
          <Search className="absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted" />
          <input
            type="text"
            placeholder="Search grid, county, zone…"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="h-8 w-full rounded-[2px] border border-border bg-background pl-8 pr-7 font-mono text-[11px] text-foreground placeholder:text-muted focus:border-accent-600 focus:outline-none"
          />
          {searchTerm && (
            <button
              onClick={() => setSearchTerm("")}
              aria-label="Clear search"
              className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded p-0.5 text-muted hover:text-foreground"
            >
              <X className="h-3 w-3" />
            </button>
          )}
        </div>

        {/* Ledger filter tabs */}
        <div className="mt-2.5 flex border border-border-strong">
          {(["all", "prime"] as const).map((mode) => {
            const active = filterMode === mode;
            return (
              <button
                key={mode}
                onClick={() => setFilterMode(mode)}
                className={`flex-1 py-1 font-mono text-[10px] uppercase tracking-[0.12em] transition-colors ${
                  active
                    ? "bg-foreground text-background"
                    : "text-muted hover:bg-surface-raised/60 hover:text-foreground"
                } ${mode === "prime" ? "border-l border-border-strong" : ""}`}
              >
                {mode === "all" ? `All · ${parcels.length}` : `Prime · ${primeCount}`}
              </button>
            );
          })}
        </div>
      </div>

      {/* Ledger rows */}
      <div className="scrollbar-hide min-h-0 flex-1 overflow-y-auto">
        {filteredParcels.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-2 px-6 text-center">
            <p className="font-display text-base text-foreground">No matching parcels</p>
            <p className="font-mono text-[10px] uppercase tracking-[0.1em] text-muted">
              Adjust search or filter
            </p>
          </div>
        ) : (
          <table className="w-full border-collapse">
            <tbody>
              {filteredParcels.map((parcel, index) => {
                const isSelected = selectedParcel?.id === parcel.id;
                return (
                  <tr
                    key={parcel.id}
                    onClick={() => onSelectParcel(parcel)}
                    className={`cursor-pointer border-b border-border/70 transition-colors ${
                      isSelected
                        ? "bg-surface-raised shadow-[inset_2px_0_0_rgb(var(--accent))]"
                        : "hover:bg-surface-raised/50"
                    }`}
                  >
                    <td className="w-8 py-2 pl-3 text-right font-mono text-[10px] tabular-nums text-muted">
                      {index + 1}
                    </td>
                    <td className="py-2 pl-2.5 pr-2">
                      <div className="flex items-center gap-1.5">
                        <span className="truncate font-mono text-[11px] font-medium text-foreground">
                          {parcel.grid_id}
                        </span>
                        {parcel.is_prime_zone && (
                          <span className="shrink-0 border border-accent-600/60 px-1 font-mono text-[8px] uppercase tracking-[0.14em] text-accent-600 dark:border-accent-400/50 dark:text-accent-400">
                            Prime
                          </span>
                        )}
                      </div>
                      <div className="mt-0.5 truncate font-mono text-[9.5px] uppercase tracking-[0.06em] text-muted">
                        {parcel.county_name} · {parcel.substation_distance_miles} mi to sub
                      </div>
                    </td>
                    <td
                      className={`py-2 pr-3 text-right font-mono text-[12px] font-medium tabular-nums ${
                        isSelected
                          ? "text-accent-600 dark:text-accent-400"
                          : "text-foreground"
                      }`}
                    >
                      {parcel.composite_score.toFixed(1)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </section>
  );
};
