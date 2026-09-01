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

function LogoMark() {
  return (
    <svg
      width="22"
      height="22"
      viewBox="0 0 22 22"
      fill="none"
      aria-hidden="true"
      className="shrink-0"
    >
      <rect x="1" y="1" width="9" height="9" rx="2.5" fill="#5E6AD2" />
      <rect
        x="12"
        y="1"
        width="9"
        height="9"
        rx="2.5"
        stroke="currentColor"
        strokeOpacity="0.35"
        strokeWidth="1.5"
      />
      <rect
        x="1"
        y="12"
        width="9"
        height="9"
        rx="2.5"
        stroke="currentColor"
        strokeOpacity="0.35"
        strokeWidth="1.5"
      />
      <rect x="12" y="12" width="9" height="9" rx="2.5" fill="#5E6AD2" fillOpacity="0.4" />
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
    <header className="flex h-14 shrink-0 items-center justify-between border-b border-border bg-background px-4">
      {/* Brand */}
      <div className="flex items-center gap-3">
        <LogoMark />
        <div>
          <h1 className="text-[13px] font-semibold leading-tight tracking-tight text-foreground">
            Site Selection Engine
          </h1>
          <p className="text-[11px] leading-tight text-muted">
            Hyperscale data centers · 100+ MW
          </p>
        </div>
      </div>

      <div className="flex items-center gap-4">
        {/* Quiet summary stats */}
        <div className="hidden items-center gap-4 text-[11px] text-muted md:flex">
          <span>
            <span className="font-medium tabular-nums text-foreground">{totalParcels}</span>{" "}
            parcels
          </span>
          <span className="h-0.5 w-0.5 rounded-full bg-border-strong" />
          <span>
            <span className="font-medium tabular-nums text-foreground">{primeCount}</span> prime
            zones
          </span>
          <span className="h-0.5 w-0.5 rounded-full bg-border-strong" />
          <span>
            <span className="font-medium tabular-nums text-foreground">
              {totalCapacityMW.toLocaleString()}
            </span>{" "}
            MW est. capacity
          </span>
        </div>

        {/* Region selector */}
        <div className="relative">
          <select
            value={selectedState}
            onChange={(e) => onStateChange(e.target.value)}
            aria-label="Select region"
            className="h-8 appearance-none rounded-md border border-border bg-surface pl-2.5 pr-7 text-xs font-medium text-foreground transition-colors hover:border-border-strong focus:border-brand-500 focus:outline-none"
          >
            <option value="VA">Northern Virginia (PJM)</option>
            <option value="TX">Texas (ERCOT)</option>
            <option value="OH">Central Ohio (PJM)</option>
            <option value="OR">Pacific Northwest</option>
          </select>
          <ChevronDown className="pointer-events-none absolute right-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted" />
        </div>

        {/* Data source + sync */}
        <div className="flex items-center gap-1.5 rounded-md border border-border bg-surface px-2.5 py-1.5">
          <span
            className={`h-1.5 w-1.5 rounded-full ${isLive ? "bg-success" : "bg-warning"}`}
            title={isLive ? "Connected to Supabase PostGIS" : "Using local demo dataset"}
          />
          <span className="text-[11px] font-medium text-muted">
            {isLive ? "PostGIS" : "Demo"}
          </span>
        </div>

        <button
          onClick={onSync}
          disabled={isSyncing}
          aria-label="Sync parcels from PostGIS"
          title="Sync parcels from PostGIS"
          className="flex h-8 w-8 items-center justify-center rounded-md border border-border bg-surface text-muted transition-colors hover:border-border-strong hover:text-foreground disabled:opacity-60"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${isSyncing ? "animate-spin" : ""}`} />
        </button>

        <ThemeToggle />
      </div>
    </header>
  );
};
