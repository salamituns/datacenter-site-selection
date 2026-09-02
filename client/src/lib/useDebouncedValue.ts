import { useEffect, useState } from "react";

/**
 * Debounced mirror of a value. Used to decouple cheap, per-frame updates
 * (parcel shading recomputes instantly on every slider tick) from more
 * expensive derived work (DBSCAN + hull polygons), so slider drags stay at
 * full frame rate while the zone morphs land a few frames later.
 */
export function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);
  return debounced;
}
