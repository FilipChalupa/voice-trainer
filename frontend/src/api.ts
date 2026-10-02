export type TrainingParams = {
  epochs: number;
  batch_size: number;
  validation_every: number;
  preview_every: number;
  learning_rate: number;
  patience: number;
  quiet_pauses: boolean;
};

export type Consent = { text: string; owner: string; at: string; duration: number };

export type VoiceSettings = {
  id: string;
  name: string;
  language: string;
  owner: string;
  consent: Consent | null;
  has_consent: boolean;
  consent_statement: string;
  max_record_seconds: number;
  training: TrainingParams;
  created_at?: string;
  lexicon: Record<string, string>;
};

export type VoiceSummary = {
  id: string;
  name: string;
  language: string;
  owner: string;
  has_consent: boolean;
  recordings: number;
  jobs: number;
  created_at: string | null;
  current: boolean;
};

export type Language = { id: string; label: string; base: { name: string; file: string; epoch: number; size_mb: number; license: string } };

export type VoicesPayload = {
  voices: VoiceSummary[];
  current: string | null;
  languages: Language[];
  defaults: TrainingParams;
  minutes: { min: number; recommended: number; target: number };
  voice: VoiceSettings | null;
};

export type QualityIssue = "cut_start" | "cut_end" | "silent" | "clipping" | "too_quiet" | "text_mismatch" | "unreadable" | "level_mismatch" | "noisy" | "model_mismatch" | "transcript_mismatch";

export type Recording = {
  id: string;
  text: string;
  prompt_id: string | null;
  created: string;
  duration: number;
  url: string;
  peaks: number[];
  reviewed: boolean;
  verify: { status: "pending" | "ok" | "mismatch" | "error"; transcript?: string; similarity?: number } | null;
  source: "import" | "transcribed" | null;
  quality: { peak?: number; rms_db?: number; speech_db?: number | null; noise_db?: number | null; speech_seconds?: number; chars_per_second?: number | null; issues: QualityIssue[] };
};

export type TranscribeState = {
  status: "idle" | "uploading" | "downloading" | "loading" | "transcribing" | "cutting" | "storing" | "done" | "failed" | "cancelled";
  voice_id: string | null;
  file: string | null;
  progress: { current: number; total: number } | null;
  device: string | null;
  model: string;
  model_installed: boolean;
  result: { stored: number; skipped: number; count: number; minutes: number } | null;
  error: string | null;
  log: string[];
};

export type CheckRow = { id: string; text: string; duration: number; distance: number; z: number; flagged: boolean };
export type CheckState = {
  status: "idle" | "running" | "done" | "failed";
  job_id: string | null;
  progress: { current: number; total: number } | null;
  error: string | null;
  result: { job_id: string; variant: string; created_at: string; count: number; median: number; flagged: number; items: CheckRow[] } | null;
};

export type StorageJob = { job_id: string; checkpoints: number; exports: number; cache: number; previews: number; total: number };
export type StorageInfo = {
  total: number;
  disk_free: number;
  disk_total: number;
  base: { checkpoints: number; whisper: number; base_voices: number; torch_hub: number; prompts: number };
  base_total: number;
  voices: { id: string; name: string; recordings: number; trash: number; jobs: StorageJob[]; jobs_total: number; cache_total: number; total: number }[];
  reclaimable: { trash: number; cache: number };
};

export type ImportResult = { imported: number; skipped: { id: string; reason: string }[]; consent_imported: boolean; count: number; minutes: number };

export type Prompt = { id: string; text: string };
export type Book = { id: string; title: string; author: string; source: string };
export type Paragraph = { id: string; title: string; sentences: number; recorded: number; preview: string };
export type Prompts = {
  items: Prompt[];
  total: number;
  remaining: number;
  source: "corpus" | "builtin";
  preparing: null | { state: string; error: string | null };
  custom: number;
};

export type DatasetReport = {
  count: number;
  minutes: number;
  mean_seconds: number;
  min_minutes: number;
  recommended_minutes: number;
  target_minutes: number;
  flagged: number;
  issues: Record<string, number>;
  rare_letters: string[];
  sentence_types: Record<"statement" | "question" | "exclamation" | "continuation", { count: number; minutes: number }>;
  duration_histogram: number[];
  has_consent: boolean;
  ready: boolean;
};

export type BaseItem = {
  language: string;
  label: string;
  name: string;
  size_mb: number;
  license: string;
  installed: boolean;
  download: null | { state: string; received?: number; total?: number | null; error?: string | null };
};

export type ValidationEntry = { epoch: number; val_mel: number | null; val_mos: number | null; val_loss: number | null };
export type Preview = { epoch: number; items: { url: string; text: string }[] };
export type ExportedVoice = { variant: string; file: string; checkpoint: string; size: number; url: string; config_url: string };

export type TrainingStatus = "idle" | "downloading" | "preparing" | "training" | "exporting" | "done" | "failed" | "cancelled" | "interrupted";

export type Calibration = { rate: number | null; basis: "history" | "default" | "none"; device: string | null };

export type TrainingState = {
  status: TrainingStatus;
  job_id: string | null;
  voice_id: string | null;
  name: string | null;
  stage_key: string | null;
  message: string | null;
  message_key: string | null;
  message_params: Record<string, string | number> | null;
  progress: { current: number; total: number };
  epoch: number;
  total_epochs: number;
  batch: number;
  batches: number;
  metrics: null | { loss_g: number | null; loss_d: number | null };
  validation: ValidationEntry[];
  previews: Preview[];
  exports: ExportedVoice[];
  bundle_url: string | null;
  resumable: boolean;
  stopped_early: boolean;
  device: string | null;
  started_at: string | null;
  finished_at: string | null;
  epoch_seconds: number | null;
  error: string | null;
  log_tail?: string[];
};

export type Job = {
  job_id: string;
  voice_id: string;
  name: string;
  slug: string;
  language: string;
  created_at: string;
  finished_at: string | null;
  status: string;
  minutes: number;
  recordings: number;
  training: TrainingParams;
  max_epochs: number;
  epoch: number | null;
  validation_last: ValidationEntry | null;
  exports: ExportedVoice[];
  bundle_url: string | null;
  resumable: boolean;
  stopped_early: boolean;
  previews: number;
};

export type SystemInfo = {
  version: string;
  latest_version: string | null;
  update_available: boolean;
  releases_url: string;
  gpu: null | { name: string; memory_total_mb: number; memory_used_mb: number; driver: string };
  gpu_available: boolean;
  torch_cuda: boolean;
  cpu_count: number | null;
  disk_free_gb: number;
  disk_total_gb: number;
  https: boolean;
  public_host: string | null;
  public_https_port: number;
};

export class ApiError extends Error {
  code: string | null;
  constructor(message: string, code: string | null = null) {
    super(message);
    this.code = code;
  }
}

async function check(res: Response): Promise<Response> {
  if (res.ok) return res;
  let detail: unknown = res.statusText;
  try {
    const body = await res.json();
    detail = body.detail ?? body;
  } catch {
    /* ignore */
  }
  if (detail && typeof detail === "object" && "code" in (detail as object)) {
    const d = detail as { code: string; message?: string };
    throw new ApiError(d.message ?? d.code, d.code);
  }
  throw new ApiError(typeof detail === "string" ? detail : JSON.stringify(detail));
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await check(await fetch(url, init));
  return res.json() as Promise<T>;
}

const json = (method: string, body: unknown): RequestInit => ({ method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

export const api = {
  voices: () => request<VoicesPayload>("/api/voices"),
  createVoice: (name: string, owner: string, language: string) => request<VoicesPayload>("/api/voices", json("POST", { name, owner, language })),
  selectVoice: (id: string) => request<VoicesPayload>(`/api/voices/${id}/select`, { method: "POST" }),
  deleteVoice: (id: string) => request<VoicesPayload>(`/api/voices/${id}`, { method: "DELETE" }),
  saveVoice: (update: Partial<Pick<VoiceSettings, "name" | "owner">> & { training?: TrainingParams; lexicon?: Record<string, string> }) => request<VoicesPayload>("/api/voice", json("PUT", update)),
  uploadConsent: (wav: Blob) => {
    const form = new FormData();
    form.append("file", wav, "consent.wav");
    return request<VoicesPayload>("/api/consent", { method: "POST", body: form });
  },
  deleteConsent: () => request<VoicesPayload>("/api/consent", { method: "DELETE" }),
  recordings: (opts: { brief?: boolean; ids?: string[] } = {}) => request<{ items: Recording[]; count: number; minutes: number }>(`/api/recordings?${new URLSearchParams({ ...(opts.brief ? { brief: "1" } : {}), ...(opts.ids ? { ids: opts.ids.join(",") } : {}) })}`),
  uploadRecording: (wav: Blob, text: string, promptId: string | null) => {
    const form = new FormData();
    form.append("text", text);
    if (promptId) form.append("prompt_id", promptId);
    form.append("file", wav, "sample.wav");
    return request<Recording>("/api/recordings", { method: "POST", body: form });
  },
  updateRecording: (id: string, text: string) => request<Recording>(`/api/recordings/${id}`, json("PUT", { text })),
  redoRecording: (id: string) => request<{ deleted: string; prompt_id: string; text: string }>(`/api/recordings/${id}/redo`, { method: "POST" }),
  reviewRecording: (id: string, text: string | null) => request<Recording>(`/api/recordings/${id}`, json("PUT", { reviewed: true, ...(text !== null ? { text } : {}) })),
  deleteRecording: (id: string) => request<{ deleted: string }>(`/api/recordings/${id}`, { method: "DELETE" }),
  restoreRecording: (id: string) => request<Recording>(`/api/recordings/${id}/restore`, { method: "POST" }),
  prompts: (count = 4) => request<Prompts>(`/api/prompts?count=${count}`),
  library: () => request<{ items: Book[] }>("/api/library"),
  book: (id: string) => request<{ id: string; title: string; author: string; chapters: { page: string; title: string }[] }>(`/api/library/${id}`),
  queueText: (body: { book?: string; page?: string; url?: string; text?: string }) => request<{ added: number; sentences: number }>("/api/library/queue", json("POST", body)),
  verifyRecording: (id: string) => request<{ status: string }>(`/api/recordings/${id}/verify`, { method: "POST" }),
  paragraphs: () => request<{ items: Paragraph[] }>("/api/paragraphs"),
  queueParagraph: (id: string) => request<{ added: number; sentences: number }>(`/api/paragraphs/${id}/queue`, { method: "POST" }),
  customBatches: () => request<{ batches: { source: string; total: number; remaining: number }[] }>("/api/prompts/custom"),
  removeCustom: (source: string | null) => request<{ removed: number }>(`/api/prompts/custom${source === null ? "" : `?source=${encodeURIComponent(source)}`}`, { method: "DELETE" }),
  addCustomPrompts: (text: string) => request<{ added: number }>("/api/prompts/custom", json("POST", { text })),
  skipPrompt: (id: string) => request<{ skipped: string }>(`/api/prompts/${id}/skip`, { method: "POST" }),
  dataset: () => request<DatasetReport>("/api/dataset"),
  check: (jobId: string) => request<CheckState>(`/api/jobs/${jobId}/check`),
  startCheck: (jobId: string) => request<CheckState>(`/api/jobs/${jobId}/check`, { method: "POST" }),
  transcribe: () => request<TranscribeState>("/api/transcribe"),
  startTranscribe: (audio: File) => {
    const form = new FormData();
    form.append("file", audio, audio.name);
    return request<TranscribeState>("/api/transcribe", { method: "POST", body: form });
  },
  cancelTranscribe: () => request<TranscribeState>("/api/transcribe/cancel", { method: "POST" }),
  storage: () => request<StorageInfo>("/api/storage"),
  emptyTrash: () => request<{ freed: number }>("/api/storage/empty-trash", { method: "POST" }),
  clearCache: () => request<{ freed: number }>("/api/storage/clear-cache", { method: "POST" }),
  importDataset: (zip: File) => {
    const form = new FormData();
    form.append("file", zip, zip.name);
    return request<ImportResult>("/api/dataset/import", { method: "POST", body: form });
  },
  base: () => request<{ items: BaseItem[] }>("/api/base"),
  downloadBase: (language: string) => request<unknown>(`/api/base/${language}/download`, { method: "POST" }),
  startTraining: () => request<TrainingState>("/api/train", { method: "POST" }),
  resumeTraining: (extraEpochs = 0) => request<TrainingState>("/api/train/resume", json("POST", { extra_epochs: extraEpochs })),
  calibration: () => request<Calibration>("/api/train/calibration"),
  cancelTraining: () => request<TrainingState>("/api/train/cancel", { method: "POST" }),
  trainingSnapshot: () => request<TrainingState>("/api/train"),
  jobs: () => request<{ items: Job[] }>("/api/jobs"),
  allJobs: () => request<{ items: (Job & { voice_name: string })[] }>("/api/jobs?all=1"),
  suggestTraining: () => request<{ minutes: number; training: Partial<TrainingParams> }>("/api/train/suggest"),
  deleteJob: (id: string) => request<unknown>(`/api/jobs/${id}`, { method: "DELETE" }),
  exportJob: (id: string) => request<TrainingState>(`/api/jobs/${id}/export`, { method: "POST" }),
  synthesize: async (body: { job_id: string; file: string; voice_id?: string; text: string; length_scale: number; noise_scale: number; noise_w_scale: number }) => {
    const res = await check(await fetch("/api/synthesize", json("POST", body)));
    return res.blob();
  },
  system: () => request<SystemInfo>("/api/system"),
};
