import { useEffect } from "react";

/** Keeps the screen on while recording (a phone would otherwise lock mid-sentence). Best effort: browsers
 *  without the Screen Wake Lock API, or a denied request, simply do nothing. */
type Sentinel = { release: () => Promise<void> };

export async function holdScreenAwake(): Promise<() => void> {
  const nav = navigator as Navigator & { wakeLock?: { request: (type: "screen") => Promise<Sentinel> } };
  let sentinel: Sentinel | null = null;
  let released = false;
  const acquire = async () => {
    try {
      sentinel = (await nav.wakeLock?.request("screen")) ?? null;
    } catch {
      sentinel = null;
    }
  };
  // the lock is dropped whenever the page is hidden; take it again when it comes back
  const onVisible = () => {
    if (!released && document.visibilityState === "visible") void acquire();
  };
  await acquire();
  document.addEventListener("visibilitychange", onVisible);
  return () => {
    released = true;
    document.removeEventListener("visibilitychange", onVisible);
    void sentinel?.release().catch(() => undefined);
  };
}

export function useScreenAwake(active: boolean): void {
  useEffect(() => {
    if (!active) return;
    let release: (() => void) | null = null;
    let cancelled = false;
    holdScreenAwake().then((r) => {
      if (cancelled) r();
      else release = r;
    });
    return () => {
      cancelled = true;
      release?.();
    };
  }, [active]);
}
