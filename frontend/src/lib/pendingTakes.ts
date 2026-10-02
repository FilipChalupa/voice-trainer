import { api, ApiError, type Recording } from "../api";

/** Takes that were recorded but not yet stored on the server, kept in IndexedDB so a dropped connection, a
 *  server restart or a closed tab does not lose them. Each take is removed once its upload succeeds. */
export type PendingTake = { id: string; voiceId: string; promptId: string | null; text: string; wav: Blob; createdAt: string };

const DB = "voice-trainer";
const STORE = "pending-takes";

function open(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(STORE, { keyPath: "id" });
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function run<T>(mode: IDBTransactionMode, fn: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  const db = await open();
  try {
    return await new Promise<T>((resolve, reject) => {
      const req = fn(db.transaction(STORE, mode).objectStore(STORE));
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  } finally {
    db.close();
  }
}

export const pendingTakes = {
  available: () => typeof indexedDB !== "undefined",
  /** Storage is a safety net: a failure here must never stop the recording itself. */
  async put(take: PendingTake): Promise<void> {
    if (!this.available()) return;
    await run("readwrite", (s) => s.put(take)).catch(() => undefined);
  },
  async remove(id: string): Promise<void> {
    if (!this.available()) return;
    await run("readwrite", (s) => s.delete(id)).catch(() => undefined);
  },
  async list(voiceId: string): Promise<PendingTake[]> {
    if (!this.available()) return [];
    const all = await run<PendingTake[]>("readonly", (s) => s.getAll()).catch(() => [] as PendingTake[]);
    return all.filter((t) => t.voiceId === voiceId).sort((a, b) => a.createdAt.localeCompare(b.createdAt));
  },
};

export function newTakeId(): string {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

/** The server answered and refused the take (no speech, too long…): keeping a copy would not help. */
const refused = (e: unknown) => e instanceof ApiError && e.status >= 400 && e.status < 500;

const inFlight = new Set<string>();

/** Uploads a take with a copy held in the browser until the server has it. A refusal drops the copy,
 *  a dead connection or a server error keeps it for later; `kept` on the thrown error says which. */
export async function uploadKept(voiceId: string, wav: Blob, text: string, promptId: string | null): Promise<Recording> {
  const id = newTakeId();
  inFlight.add(id);
  await pendingTakes.put({ id, voiceId, promptId, text, wav, createdAt: new Date().toISOString() });
  try {
    const rec = await api.uploadRecording(wav, text, promptId);
    await pendingTakes.remove(id);
    return rec;
  } catch (e) {
    if (refused(e)) await pendingTakes.remove(id);
    else if (e && typeof e === "object") (e as { kept?: boolean }).kept = pendingTakes.available();
    throw e;
  } finally {
    inFlight.delete(id);
  }
}

export const wasKept = (e: unknown): boolean => Boolean(e && typeof e === "object" && (e as { kept?: boolean }).kept);

/** Takes waiting in the browser for this voice, without those this tab is uploading right now. */
export async function waitingTakes(voiceId: string): Promise<PendingTake[]> {
  return (await pendingTakes.list(voiceId)).filter((t) => !inFlight.has(t.id));
}

/** Uploads what is waiting. A sentence that was recorded again in the meantime keeps its newer take. */
export async function flushTakes(voiceId: string): Promise<{ uploaded: Recording[]; dropped: number; left: number }> {
  const waiting = await waitingTakes(voiceId);
  const result = { uploaded: [] as Recording[], dropped: 0, left: 0 };
  if (!waiting.length) return result;
  let newest = new Map<string, string>();
  try {
    newest = new Map((await api.recordings({ brief: true })).items.filter((r) => r.prompt_id).map((r) => [r.prompt_id as string, r.created]));
  } catch {
    return { ...result, left: waiting.length };
  }
  for (const take of waiting) {
    const existing = take.promptId ? newest.get(take.promptId) : undefined;
    if (existing && Date.parse(existing) > Date.parse(take.createdAt)) {
      await pendingTakes.remove(take.id);
      result.dropped += 1;
      continue;
    }
    inFlight.add(take.id);
    try {
      result.uploaded.push(await api.uploadRecording(take.wav, take.text, take.promptId));
      await pendingTakes.remove(take.id);
    } catch (e) {
      if (refused(e)) {
        await pendingTakes.remove(take.id);
        result.dropped += 1;
      } else result.left += 1;
    } finally {
      inFlight.delete(take.id);
    }
  }
  return result;
}

export async function discardTakes(voiceId: string): Promise<void> {
  for (const take of await waitingTakes(voiceId)) await pendingTakes.remove(take.id);
}
