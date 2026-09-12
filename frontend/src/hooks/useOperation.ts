import { useEffect, useRef, useState } from "react";

export function useOperation<T>() {
  const active = useRef<AbortController | null>(null);
  const [data, setData] = useState<T | null>(null),
    [error, setError] = useState<string | null>(null),
    [busy, setBusy] = useState(false);
  useEffect(() => () => active.current?.abort(), []);
  function reset() {
    active.current?.abort();
    active.current = null;
    setData(null);
    setError(null);
    setBusy(false);
  }
  async function run(task: (signal: AbortSignal) => Promise<T>) {
    if (active.current) return;
    const controller = new AbortController();
    active.current = controller;
    setData(null);
    setError(null);
    setBusy(true);
    try {
      const value = await task(controller.signal);
      if (!controller.signal.aborted) setData(value);
    } catch (e) {
      if (!controller.signal.aborted)
        setError(
          e instanceof Error ? e.message : "The operation could not finish.",
        );
    } finally {
      if (active.current === controller) {
        active.current = null;
        setBusy(false);
      }
    }
  }
  return { data, error, busy, run, reset };
}
