import React from "react";
import { RefreshCw, ChevronDown } from "lucide-react";
import { ThemeToggle } from "./ThemeToggle";

interface HeaderProps {
  totalParcels: number;
  primeCount: number;
  totalCapacityMW: number;
  selectedState: string;
  onStateChange: (state: string) => void;
  isLive: boolean;
  isSyncing: boolean;
  onSync: () => void;
}

/** Geodetic benchmark: crosshair circle with a signal-orange station dot. */
function BenchmarkMark() {
  return (
    <svg
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
      className="shrink-0 text-foreground"
    >
      <circle cx="12" cy="12" r="7.25" stroke="currentColor" strokeWidth="1.25" />
      <path
        d="M12 1.5v4.5M12 18v4.5M1.5 12h4.5M18 12h4.5"
        stroke="currentColor"
        strokeWidth="1.25"
      />
      <circle cx="12" cy="12" r="2.25" className="fill-accent-600 dark:fill-accent-400" />
    </svg>
  );
}

export const Header: React.FC<HeaderProps> = ({
  totalParcels,
  primeCount,
  totalCapacityMW,
  selectedState,
  onStateChange,
  isLive,
  isSyncing,
  onSync,
}) => {
  return (
    <header className="flex h-16 shrink-0 items-center justify-between gap-3 border-b border-border-strong bg-background px-3 sm:px-4">
      {/* Masthead */}
      <div className="flex min-w-0 items-center gap-2.5 sm:gap-3.5">
        <BenchmarkMark />
        <div className="min-w-0">
          <h1 className="font-display text-lg font-semibold leading-none tracking-tight text-foreground sm:text-[22px]">
            Site Selection Engine
          </h1>
          <p className="mt-1 hidden font-mono text-[9px] uppercase tracking-[0.18em] text-muted sm:block">
            Hyperscale parcel survey · 100+ MW
          </p>
        </div>
      </div>

      <div className="flex shrink-0 items-center gap-2.5 sm:gap-5">
        {/* Ledger stats */}
        <div className="hidden items-center gap-4 font-mono text-[11px] tabular-nums text-muted lg:flex">
          <span>
            <span className="text-foreground">{totalParcels}</span> parcels
          </span>
          <span className="h-px w-3 bg-border-strong" />
          <span>
            <span className="text-foreground">{primeCount}</span> prime zones
          </span>
          <span className="h-px w-3 bg-border-strong" />
          <span>
            <span className="text-foreground">{totalCapacityMW.toLocaleString()}</span> MW est.
          </span>
        </div>

        {/* Region selector */}
        <div className="relative hidden sm:block">
          <select
            value={selectedState}
            onChange={(e) => onStateChange(e.target.value)}
            aria-label="Select region"
            className="h-8 appearance-none rounded-[2px] border border-border-strong bg-surface pl-2 pr-6 font-mono text-[10px] uppercase tracking-wide text-foreground transition-colors hover:border-foreground/60 focus:border-accent-600 focus:outline-none sm:pl-2.5 sm:pr-7 sm:text-[11px]"
          >
            <option value="VA">N. Virginia · PJM</option>
            <option value="TX">Texas · ERCOT</option>
            <option value="OH">C. Ohio · PJM</option>
            <option value="OR">Pacific NW</option>
          </select>
          <ChevronDown className="pointer-events-none absolute right-2 top-1/2 h-3 w-3 -translate-y-1/2 text-muted" />
        </div>

        {/* Data source + sync */}
        <div className="hidden items-center gap-1.5 rounded-[2px] border border-border-strong bg-surface px-2.5 py-1.5 sm:flex">
          <span
            className={`h-1.5 w-1.5 rounded-full ${isLive ? "bg-success dark:bg-success-night" : "bg-warning dark:bg-power-night"}`}
            title={isLive ? "Connected to Supabase PostGIS" : "Using local demo dataset"}
          />
          <span className="font-mono text-[10px] uppercase tracking-[0.12em] text-muted">
            {isLive ? "PostGIS" : "Demo"}
          </span>
        </div>

        <button
          onClick={onSync}
          disabled={isSyncing}
          aria-label="Sync parcels from PostGIS"
          title="Sync parcels from PostGIS"
          className="flex h-8 w-8 items-center justify-center rounded-[2px] border border-border-strong bg-surface text-muted transition-colors hover:border-foreground/60 hover:text-foreground disabled:opacity-60"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${isSyncing ? "animate-spin" : ""}`} />
        </button>

        <ThemeToggle />
      </div>
    </header>
  );
};
