"use client";
/**
 * The region selector — one component, both surfaces.
 *
 * It used to be a native <select> in two places, which was fine at nine
 * regions and is not fine at the several hundred a PJM screening sweep
 * publishes: a dropdown with 552 alphabetised counties buries the ten
 * that were actually surveyed. The rule lives in lib/regions
 * (filterRegions): surveyed counties by default, everything else behind
 * the search box, screening-only entries badged so a measurement never
 * masquerades as a survey.
 */
import React, { useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, Search } from "lucide-react";
import {
  filterRegions,
  HOME_REGION,
  isSurveyed,
  type Region,
} from "@/lib/regions";

interface RegionSelectProps {
  regions?: Region[] | null;
  selectedRegion: string;
  onRegionChange: (region: string) => void;
  /** "desktop" shows full labels in the header; "compact" fits the mobile pill. */
  variant: "desktop" | "compact";
}

export const RegionSelect: React.FC<RegionSelectProps> = ({
  regions,
  selectedRegion,
  onRegionChange,
  variant,
}) => {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const rootRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const options = regions ?? [];
  const list = useMemo(() => filterRegions(options, query), [options, query]);

  // The selected region stays visible even when filtered out — a
  // screening-only region already chosen must not vanish from the list the
  // moment its search query is cleared.
  const visible = useMemo(() => {
    if (list.some((r) => r.code === selectedRegion)) return list;
    const selected = options.find((r) => r.code === selectedRegion);
    return selected ? [selected, ...list] : list;
  }, [list, options, selectedRegion]);

  const selected = options.find((r) => r.code === selectedRegion);
  const hiddenCount =
    options.length - options.filter((r) => isSurveyed(r)).length;

  // Close on outside press. Not a click handler on a backdrop — this panel
  // drops over the map, and an invisible full-screen layer would eat the
  // pan gestures the map exists for.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(false);
        setQuery("");
      }
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  useEffect(() => {
    if (open) {
      setActiveIndex(0);
      // Next paint: the panel is measured before focus lands in it.
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [open]);

  const pick = (code: string) => {
    setOpen(false);
    setQuery("");
    onRegionChange(code);
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") {
      setOpen(false);
      setQuery("");
      return;
    }
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIndex((i) => {
        if (!visible.length) return 0;
        const next = e.key === "ArrowDown" ? i + 1 : i - 1;
        return (next + visible.length) % visible.length;
      });
    } else if (e.key === "Enter") {
      e.preventDefault();
      const r = visible[activeIndex];
      if (r) pick(r.code);
    }
  };

  const compact = variant === "compact";

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label="Select region"
        className={
          compact
            ? "flex h-10 items-center gap-1 rounded-[3px] border border-border-strong bg-surface/95 pl-2.5 pr-6 font-mono text-[11px] uppercase tracking-wide text-foreground shadow-plate backdrop-blur transition-colors focus:border-accent-600 focus:outline-none"
            : "flex h-8 items-center gap-1 rounded-[2px] border border-border-strong bg-surface pl-2 pr-6 font-mono text-[10px] uppercase tracking-wide text-foreground transition-colors hover:border-foreground/60 focus:border-accent-600 focus:outline-none sm:text-[11px]"
        }
      >
        {compact ? selected?.short ?? selectedRegion : selected?.label ?? selectedRegion}
      </button>
      <ChevronDown
        className={
          compact
            ? "pointer-events-none absolute right-1.5 top-1/2 h-3 w-3 -translate-y-1/2 text-muted"
            : "pointer-events-none absolute right-2 top-1/2 h-3 w-3 -translate-y-1/2 text-muted"
        }
      />

      {open && (
        <div
          role="listbox"
          aria-label="Regions"
          onKeyDown={onKeyDown}
          className={`absolute right-0 z-40 mt-1 ${
            compact ? "w-72" : "w-80"
          } rounded-[3px] border border-border-strong bg-surface shadow-plate`}
        >
          <div className="relative border-b border-border-strong">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted" />
            <input
              ref={inputRef}
              type="text"
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setActiveIndex(0);
              }}
              placeholder={
                hiddenCount > 0
                  ? `Search ${hiddenCount} screening counties…`
                  : "Search regions…"
              }
              aria-label="Search regions"
              className="h-9 w-full rounded-t-[3px] bg-transparent py-0 pl-8 pr-3 font-mono text-[11px] text-foreground placeholder:text-muted focus:border-accent-600 focus:outline-none"
            />
          </div>
          <div className="max-h-72 overflow-y-auto py-1">
            {visible.length === 0 && (
              <p className="px-3 py-4 font-mono text-[10px] text-muted">
                No region matches “{query.trim()}”.
              </p>
            )}
            {visible.map((r, i) => {
              const isSelected = r.code === selectedRegion;
              return (
                <button
                  key={r.code}
                  type="button"
                  role="option"
                  aria-selected={isSelected}
                  onClick={() => pick(r.code)}
                  onMouseEnter={() => setActiveIndex(i)}
                  className={`flex w-full items-center justify-between gap-3 px-3 py-1.5 text-left font-mono text-[11px] transition-colors ${
                    i === activeIndex ? "bg-surface-raised" : ""
                  } ${isSelected ? "text-accent-600 dark:text-accent-400" : "text-foreground"}`}
                >
                  <span className="truncate">
                    {compact ? `${r.short} · ${r.label}` : r.label}
                  </span>
                  {!isSurveyed(r) && (
                    <span className="shrink-0 rounded-[2px] border border-border-strong px-1.5 py-0.5 text-[8px] uppercase tracking-[0.14em] text-muted">
                      screening
                    </span>
                  )}
                </button>
              );
            })}
          </div>
          {!query.trim() && hiddenCount > 0 && (
            <p className="border-t border-border-strong px-3 py-2 font-mono text-[9px] uppercase tracking-[0.12em] text-muted">
              {options.filter(isSurveyed).length} surveyed · {hiddenCount}{" "}
              screening behind search
            </p>
          )}
        </div>
      )}
    </div>
  );
};
