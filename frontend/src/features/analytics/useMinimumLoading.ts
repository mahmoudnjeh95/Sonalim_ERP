import { useEffect, useRef, useState } from "react";

/**
 * Keeps a loading state visible for at least `minMs` once it starts, so a fast response doesn't flash the
 * loader for a split second. A slower load is not extended: it ends as soon as the data is ready.
 */
export function useMinimumLoading(isLoading: boolean, minMs = 1000): boolean {
  const [holding, setHolding] = useState(isLoading);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => {
    if (!isLoading) return;
    setHolding(true);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setHolding(false), minMs);
  }, [isLoading, minMs]);

  useEffect(() => () => window.clearTimeout(timer.current), []);

  return isLoading || holding;
}
