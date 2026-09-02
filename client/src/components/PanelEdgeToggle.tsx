"use client";

import React from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";

interface PanelEdgeToggleProps {
  /** Whether the panel this control belongs to is currently open. */
  open: boolean;
  /** Toggles the owning panel — wired from the page state. */
  onToggle: () => void;
  /** Which side of the map the panel sits on. */
  side: "left" | "right";
  titleOpen: string;
  titleClosed: string;
}

/**
 * Collapse/expand chevron straddling the seam between a side panel and the
 * map (desktop only). Collapsing points toward the panel's outer edge; the
 * control stays at the map edge when the panel is closed so it can be
 * brought back.
 */
export const PanelEdgeToggle: React.FC<PanelEdgeToggleProps> = ({
  open,
  onToggle,
  side,
  titleOpen,
  titleClosed,
}) => {
  const isLeft = side === "left";
  // Open: chevron points toward the panel's outer edge (collapse direction).
  // Closed: it points back into the space the panel will reoccupy.
  const Icon = open ? (isLeft ? ChevronLeft : ChevronRight) : isLeft ? ChevronRight : ChevronLeft;

  return (
    <button
      onClick={onToggle}
      aria-pressed={open}
      aria-label={open ? titleOpen : titleClosed}
      title={open ? titleOpen : titleClosed}
      className={`absolute top-1/2 z-[500] hidden h-14 w-5 -translate-y-1/2 items-center justify-center rounded-[3px] border border-border-strong bg-surface/95 text-muted shadow-plate backdrop-blur transition-colors hover:border-foreground/60 hover:text-foreground lg:flex ${
        isLeft ? "-left-[10px]" : "-right-[10px]"
      }`}
    >
      <Icon className="h-3.5 w-3.5" />
    </button>
  );
};
