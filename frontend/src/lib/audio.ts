/** One sound at a time: starting any player or clip pauses whatever else is playing. */
let current: HTMLAudioElement | null = null;
const listeners = new Set<(audio: HTMLAudioElement | null) => void>();

export function playExclusive(audio: HTMLAudioElement): Promise<void> {
  if (current && current !== audio) current.pause();
  current = audio;
  listeners.forEach((fn) => fn(audio));
  return audio.play().catch(() => undefined);
}

export function stopAll(): void {
  current?.pause();
  current = null;
  listeners.forEach((fn) => fn(null));
}

/** Called whenever another element takes over, so a player can show itself as paused. */
export function onExclusiveChange(fn: (audio: HTMLAudioElement | null) => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

/** Plays a list of sources one after the other (comparisons). */
export function playSequence(urls: string[]): void {
  const [first, ...rest] = urls;
  if (!first) return;
  const audio = new Audio(first);
  audio.onended = () => playSequence(rest);
  void playExclusive(audio);
}

const peakCache = new Map<string, number[]>();

/** Waveform peaks of a sound file, decoded in the browser and cached per URL. */
export async function loadPeaks(url: string, buckets = 80): Promise<number[]> {
  const cached = peakCache.get(url);
  if (cached) return cached;
  const data = await (await fetch(url)).arrayBuffer();
  const Ctx = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
  const ctx = new Ctx();
  try {
    const buffer = await ctx.decodeAudioData(data);
    const samples = buffer.getChannelData(0);
    const size = Math.max(1, Math.floor(samples.length / buckets));
    const peaks: number[] = [];
    for (let b = 0; b < buckets; b++) {
      let peak = 0;
      for (let i = b * size; i < Math.min(samples.length, (b + 1) * size); i++) peak = Math.max(peak, Math.abs(samples[i]));
      peaks.push(peak);
    }
    if (peakCache.size > 200) peakCache.clear();
    peakCache.set(url, peaks);
    return peaks;
  } finally {
    void ctx.close();
  }
}

export function formatTime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}
