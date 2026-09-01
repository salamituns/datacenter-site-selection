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
    <section className="flex h-full min-h-0 flex-col overflow-hidden rounded-xl border border-border bg-surface">
      {/* Panel header */}
      <div className="border-b border-border px-4 py-3">
        <div className="flex items-center justify-between">
          <h3 className="text-[13px] font-semibold tracking-tight text-foreground">
            Ranked Parcels
          </h3>
          <span className="text-[11px] tabular-nums text-muted">{filteredParcels.length}</span>
        </div>

        {/* Search */}
        <div className="relative mt-3">
          <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted" />
          <input
            type="text"
            placeholder="Search grid, county, zone"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="h-8 w-full rounded-md border border-border bg-background pl-8 pr-7 text-xs text-foreground placeholder:text-muted focus:border-brand-500 focus:outline-none"
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

        {/* Segmented filter */}
        <div className="mt-2.5 flex gap-0.5 rounded-md bg-surface-raised p-0.5">
          <button
            onClick={() => setFilterMode("all")}
            className={`flex-1 rounded py-1 text-[11px] font-medium transition-colors ${
              filterMode === "all"
                ? "bg-surface text-foreground shadow-raised"
                : "text-muted hover:text-foreground"
            }`}
          >
            All · {parcels.length}
          </button>
          <button
            onClick={() => setFilterMode("prime")}
            className={`flex-1 rounded py-1 text-[11px] font-medium transition-colors ${
              filterMode === "prime"
                ? "bg-surface text-foreground shadow-raised"
                : "text-muted hover:text-foreground"
            }`}
          >
            Prime · {primeCount}
          </button>
        </div>
      </div>

      {/* List */}
      <div className="scrollbar-hide min-h-0 flex-1 overflow-y-auto p-1.5">
        {filteredParcels.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-2 px-6 text-center">
            <p className="text-xs font-medium text-foreground">No matching parcels</p>
            <p className="text-[11px] leading-relaxed text-muted">
              Try a different search term or switch back to the All filter.
            </p>
          </div>
        ) : (
          filteredParcels.map((parcel, index) => {
            const isSelected = selectedParcel?.id === parcel.id;
            return (
              <button
                key={parcel.id}
                onClick={() => onSelectParcel(parcel)}
                className={`flex w-full items-center gap-3 rounded-lg px-2.5 py-2 text-left transition-colors ${
                  isSelected
                    ? "bg-surface-raised ring-1 ring-border-strong"
                    : "hover:bg-surface-raised/60"
                }`}
              >
                <span className="w-5 shrink-0 text-right font-mono text-[11px] tabular-nums text-muted">
                  {index + 1}
                </span>

                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5">
                    <span className="truncate font-mono text-xs font-medium text-foreground">
                      {parcel.grid_id}
                    </span>
                    {parcel.is_prime_zone && (
                      <span className="flex shrink-0 items-center gap-1">
                        <span className="h-1.5 w-1.5 rounded-full bg-brand-400" />
                        <span className="text-[10px] font-medium text-brand-300">Prime</span>
                      </span>
                    )}
                  </div>
                  <p className="mt-0.5 truncate text-[11px] text-muted">
                    {parcel.county_name} County · {parcel.substation_distance_miles} mi to
                    substation
                  </p>
                </div>

                <span
                  className={`shrink-0 font-mono text-xs font-semibold tabular-nums ${
                    isSelected ? "text-brand-300" : "text-foreground"
                  }`}
                >
                  {parcel.composite_score.toFixed(1)}
                </span>
              </button>
            );
          })
        )}
      </div>
    </section>
  );
};
