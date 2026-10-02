import { useEffect, useRef, useState } from "react";
import { Alert, Button, Card, CardContent, CardHeader, LinearProgress, Stack, TextField, Typography } from "@mui/material";
import SubtitlesIcon from "@mui/icons-material/Subtitles";
import UploadFileIcon from "@mui/icons-material/UploadFile";
import StopIcon from "@mui/icons-material/Stop";
import { api, type TranscribeState } from "../api";
import { errorText, useI18n, type TKey } from "../i18n";

type Props = { voiceId: string; disabled: boolean; onImported: () => void; onError: (message: string) => void };

const RUNNING = new Set(["uploading", "downloading", "loading", "transcribing", "cutting", "storing"]);

/** Turns one long recording into sentence recordings: Whisper transcribes it, the pauses decide the cuts. */
export function TranscribeCard({ voiceId, disabled, onImported, onError }: Props) {
  const { t } = useI18n();
  const [state, setState] = useState<TranscribeState | null>(null);
  const [uploading, setUploading] = useState(false);
  const [hints, setHints] = useState("");
  const fileRef = useRef<HTMLInputElement | null>(null);
  const wasRunning = useRef(false);

  const running = uploading || (!!state && RUNNING.has(state.status));

  useEffect(() => {
    let alive = true;
    const poll = () => api.transcribe().then((s) => alive && setState(s)).catch(() => undefined);
    poll();
    const timer = setInterval(poll, running ? 1500 : 10000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [running]);

  useEffect(() => {
    if (!state) return;
    if (wasRunning.current && !RUNNING.has(state.status) && state.status === "done") onImported();
    wasRunning.current = RUNNING.has(state.status);
  }, [state, onImported]);

  const upload = async (file: File | undefined) => {
    if (!file) return;
    setUploading(true);
    try {
      setState(await api.startTranscribe(file, hints));
    } catch (e) {
      onError(errorText(t, e));
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const mine = !state?.voice_id || state.voice_id === voiceId;
  const pct = state?.progress && state.progress.total > 0 ? (state.progress.current / state.progress.total) * 100 : null;
  const stage = state && RUNNING.has(state.status) ? t(`imp.stage.${uploading ? "uploading" : state.status}` as TKey) : uploading ? t("imp.stage.uploading") : null;

  return (
    <Card>
      <CardHeader avatar={<SubtitlesIcon color="primary" />} title={t("imp.title")} subheader={t("imp.subtitle")} />
      <CardContent>
        <Stack spacing={2}>
          <Typography variant="body2" color="text.secondary">
            {t("imp.help")} {state && !state.model_installed ? t("imp.modelDownload") : ""}
          </Typography>
          <TextField size="small" label={t("imp.hints")} helperText={t("imp.hintsHelp")} value={hints} onChange={(e) => setHints(e.target.value)} disabled={disabled || running} fullWidth />
          <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap" useFlexGap>
            <Button variant="contained" component="label" startIcon={<UploadFileIcon />} disabled={disabled || running}>
              {t("imp.pick")}
              <input ref={fileRef} type="file" accept="audio/*,video/mp4,.m4a,.opus,.webm" hidden onChange={(e) => upload(e.target.files?.[0])} />
            </Button>
            {running && !uploading && (
              <Button color="error" startIcon={<StopIcon />} onClick={() => api.cancelTranscribe().then(setState).catch((e) => onError(errorText(t, e)))}>
                {t("imp.cancel")}
              </Button>
            )}
          </Stack>
          {stage && (
            <Stack spacing={0.5}>
              <Typography variant="subtitle2">
                {stage}
                {state?.file ? ` · ${state.file}` : ""}
                {state?.device ? ` · ${state.device}` : ""}
              </Typography>
              <LinearProgress variant={pct !== null ? "determinate" : "indeterminate"} value={pct ?? 0} />
            </Stack>
          )}
          {mine && state?.status === "done" && state.result && (
            <Alert severity="success" variant="outlined">
              {t("imp.done", { n: state.result.stored, minutes: state.result.minutes.toFixed(1) })}
              {state.result.skipped ? ` ${t("imp.skipped", { n: state.result.skipped })}` : ""} {t("imp.review")}
            </Alert>
          )}
          {mine && state?.status === "failed" && (
            <Alert severity="error" variant="outlined">
              {t("imp.failed")} {state.error}
            </Alert>
          )}
          {mine && state?.status === "cancelled" && (
            <Alert severity="warning" variant="outlined">
              {t("imp.cancelled")}
            </Alert>
          )}
        </Stack>
      </CardContent>
    </Card>
  );
}
