import { useEffect, useState } from "react";
import { api, type TrainingState } from "../api";

export const EMPTY_STATE: TrainingState = {
  status: "idle",
  job_id: null,
  voice_id: null,
  name: null,
  stage_key: null,
  message: null,
  message_key: null,
  message_params: null,
  progress: { current: 0, total: 0 },
  epoch: 0,
  total_epochs: 0,
  batch: 0,
  batches: 0,
  metrics: null,
  validation: [],
  previews: [],
  exports: [],
  bundle_url: null,
  resumable: false,
  device: null,
  started_at: null,
  finished_at: null,
  epoch_seconds: null,
  error: null,
};

const MAX_LOG = 400;

/** Live training state over Server-Sent Events (snapshot on connect, then partial updates and log lines). */
export function useTrainingStream() {
  const [state, setState] = useState<TrainingState>(EMPTY_STATE);
  const [log, setLog] = useState<string[]>([]);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    let closed = false;
    const source = new EventSource("/api/train/status");
    source.onopen = () => setConnected(true);
    source.addEventListener("snapshot", (e) => {
      const snap = JSON.parse((e as MessageEvent).data) as TrainingState;
      setState({ ...EMPTY_STATE, ...snap });
      setLog(snap.log_tail ?? []);
    });
    source.addEventListener("state", (e) => {
      const partial = JSON.parse((e as MessageEvent).data) as Partial<TrainingState>;
      setState((prev) => ({ ...prev, ...partial }));
    });
    source.addEventListener("log", (e) => {
      const { line } = JSON.parse((e as MessageEvent).data) as { line: string };
      setLog((prev) => (prev.length >= MAX_LOG ? [...prev.slice(prev.length - MAX_LOG + 1), line] : [...prev, line]));
    });
    source.onerror = () => {
      setConnected(false);
      api
        .trainingSnapshot()
        .then((snap) => !closed && setState({ ...EMPTY_STATE, ...snap }))
        .catch(() => undefined);
    };
    return () => {
      closed = true;
      source.close();
    };
  }, []);

  return { state, log, connected };
}
