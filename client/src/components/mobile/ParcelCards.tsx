"use client";

import React from "react";
import { GridParcel } from "@/types/parcel";

interface ParcelCardsProps {
  parcels: GridParcel[];
  selectedId?: string;
  onSelect: (parcel: GridParcel) => void;
}

/** Minimal ledger card — name and tags left, serif score right. */
export const ParcelCards: React.FC<ParcelCardsProps> = ({
  parcels,
  selectedId,
  onSelect,
}) => {
  if (parcels.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 px-6 text-center">
        <p className="font-display text-base text-foreground">No matching parcels</p>
        <p className="font-mono text-[10px] uppercase tracking-[0.1em] text-muted">
          Adjust search or filters
        </p>
      </div>
    );
  }

  return (
    <div role="list" aria-label="Ranked parcels">
      {parcels.map((parcel) => {
        const isSelected = selectedId === parcel.id;
        return (
          <button
            key={parcel.id}
            role="listitem"
            onClick={() => onSelect(parcel)}
            className={`flex w-full items-center justify-between gap-3 border-b border-border/70 px-4 py-3 text-left transition-colors active:bg-surface-raised ${
              isSelected
                ? "bg-surface-raised shadow-[inset_2px_0_0_rgb(var(--accent))]"
                : ""
            }`}
          >
            <div className="min-w-0">
              <div className="flex items-center gap-1.5">
                <span className="truncate font-mono text-[12px] font-medium text-foreground">
                  {parcel.grid_id}
                </span>
                {parcel.is_prime_zone && (
                  <span className="shrink-0 border border-accent-600/60 px-1 font-mono text-[8px] uppercase tracking-[0.14em] text-accent-600 dark:border-accent-400/50 dark:text-accent-400">
                    Prime
                  </span>
                )}
              </div>
              <div className="mt-0.5 truncate font-mono text-[9.5px] uppercase tracking-[0.06em] text-muted">
                {parcel.county_name} · {parcel.cluster_label}
              </div>
            </div>
            <span
              className={`shrink-0 font-display text-lg font-semibold leading-none tabular-nums ${
                isSelected ? "text-accent-600 dark:text-accent-400" : "text-foreground"
              }`}
            >
              {parcel.composite_score.toFixed(1)}
            </span>
          </button>
        );
      })}
    </div>
  );
};
