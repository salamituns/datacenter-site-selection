"use client";

import * as React from "react";
import { Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";

export function ThemeToggle() {
  const { setTheme, resolvedTheme } = useTheme();
  const [mounted, setMounted] = React.useState(false);

  // Avoid hydration mismatch
  React.useEffect(() => {
    setMounted(true);
  }, []);

  const isDark = resolvedTheme === "dark";

  return (
    <button
      onClick={() => setTheme(isDark ? "light" : "dark")}
      aria-label={mounted ? (isDark ? "Switch to paper (light) theme" : "Switch to blueprint (dark) theme") : "Toggle theme"}
      title={mounted ? (isDark ? "Switch to paper (light) theme" : "Switch to blueprint (dark) theme") : "Toggle theme"}
      className="flex h-8 w-8 items-center justify-center rounded-[2px] border border-border-strong bg-surface text-muted transition-colors hover:border-foreground/60 hover:text-foreground"
    >
      {mounted && isDark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
    </button>
  );
}
