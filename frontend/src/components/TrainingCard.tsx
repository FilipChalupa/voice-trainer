import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { Accordion, AccordionDetails, AccordionSummary, Alert, Box, Button, Card, CardContent, CardHeader, Chip, Collapse, FormControlLabel, LinearProgress, MenuItem, Stack, Switch, TextField, Tooltip, Typography } from "@mui/material";
import ModelTrainingIcon from "@mui/icons-material/ModelTraining";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import StopIcon from "@mui/icons-material/Stop";
import RestartAltIcon from "@mui/icons-material/RestartAlt";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import ExpandLessIcon from "@mui/icons-material/ExpandLess";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import ErrorOutlineIcon from "@mui/icons-material/ErrorOutline";
import IosShareIcon from "@mui/icons-material/IosShare";
import { api, type BaseItem, type Calibration, type DatasetReport, type SystemInfo, type TrainingParams, type TrainingState, type VoiceSettings, type VoicesPayload } from "../api";
import { errorText, useI18n, type TKey } from "../i18n";
import { AudioPlayer } from "./AudioPlayer";

const TrainingCharts = lazy(() => import("./TrainingCharts").then((m) => ({ default: m.TrainingCharts })));

type Props = {
  state: TrainingState;
  log: string[];
  voice: VoiceSettings;
  defaults: TrainingParams;
  system: SystemInfo | null;
  report: DatasetReport | null;
  onVoices: (p: VoicesPayload) => void;
  onError: (message: string) => void;
  onFinished: () => void;
  onGo: (tab: "voice" | "record") => void;
};

const STATUS_COLOR: Record<TrainingState["status"], "default" | "info" | "success" | "error" | "warning"> = {
  idle: "default",
  downloading: "info",
  preparing: "info",
  training: "info",
  exporting: "info",
  done: "success",
  failed: "error",
  cancelled: "warning",
  interrupted: "warning",
};
const STAGES = new Set(["checking_base", "downloading_base", "preparing", "training", "stopping", "exporting", "done", "failed", "cancelled", "interrupted"]);
const FIELDS: { key: Exclude<keyof TrainingParams, "quiet_pauses">; step: number; min: number }[] = [
  { key: "epochs", step: 50, min: 10 },
  { key: "batch_size", step: 2, min: 2 },
  { key: "validation_every", step: 5, min: 1 },
  { key: "preview_every", step: 10, min: 1 },
  { key: "learning_rate", step: 0.00005, min: 0.00001 },
  { key: "patience", step: 1, min: 0 },
];

function duration(seconds: number): string {
  if (seconds < 90) return `${Math.round(seconds)} s`;
  if (seconds < 5400) return `${Math.round(seconds / 60)} min`;
  return `${(seconds / 3600).toFixed(1)} h`;
}

export function TrainingCard({ state, log, voice, report, defaults, system, onVoices, onError, onFinished, onGo }: Props) {
  const { t } = useI18n();
  const [showLog, setShowLog] = useState(false);
  const [busy, setBusy] = useState(false);
  const [params, setParams] = useState<TrainingParams>(voice.training);
  const [extra, setExtra] = useState(200);
  const [base, setBase] = useState<BaseItem | null>(null);
  const [calibration, setCalibration] = useState<Calibration | null>(null);
  const [previewEpoch, setPreviewEpoch] = useState<number | null>(null);
  const logRef = useRef<HTMLDivElement | null>(null);
  const prevStatus = useRef(state.status);

  useEffect(() => setParams(voice.training), [voice.id, voice.training]);
  useEffect(() => {
    api.calibration().then(setCalibration).catch(() => setCalibration(null));
    api
      .base()
      .then((r) => setBase(r.items.find((b) => b.language === voice.language) ?? null))
      .catch(() => setBase(null));
  }, [voice.language, state.status]);
  useEffect(() => {
    if (showLog && logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [log, showLog]);
  useEffect(() => {
    if (prevStatus.current !== state.status && ["done", "failed", "cancelled"].includes(state.status)) onFinished();
    prevStatus.current = state.status;
  }, [state.status, onFinished]);
  useEffect(() => {
    if (state.previews.length) setPreviewEpoch(state.previews[state.previews.length - 1].epoch);
  }, [state.previews.length]); // eslint-disable-line react-hooks/exhaustive-deps

  const running = ["downloading", "preparing", "training", "exporting"].includes(state.status);
  const mine = !state.voice_id || state.voice_id === voice.id;

  const call = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await fn();
      setShowLog(true);
    } catch (e) {
      onError(errorText(t, e));
    } finally {
      setBusy(false);
    }
  };

  const saveParams = async () => {
    setBusy(true);
    try {
      onVoices(await api.saveVoice({ training: params }));
    } catch (e) {
      onError(errorText(t, e));
    } finally {
      setBusy(false);
    }
  };

  const gpuOk = !!system?.gpu_available && !!system?.torch_cuda;
  const canStart = !!report?.ready && !running;
  const paramsDirty = JSON.stringify(params) !== JSON.stringify(voice.training);
  const isTraining = state.status === "training";
  const total = isTraining || state.status === "done" ? state.total_epochs : state.progress.total;
  const current = isTraining || state.status === "done" ? state.epoch : state.progress.current;
  const withinEpoch = isTraining && state.batches > 0 ? state.batch / state.batches : 0;
  const pct = total > 0 ? Math.min(100, ((current + withinEpoch) / total) * 100) : 0;
  const lastVal = state.validation[state.validation.length - 1];
  const eta = isTraining && state.epoch_seconds ? (state.total_epochs - state.epoch) * state.epoch_seconds : null;
  const estimate = calibration?.rate && report ? params.epochs * calibration.rate * report.minutes : null;
  const stageText = state.stage_key && STAGES.has(state.stage_key) ? t(`train.stage.${state.stage_key}` as TKey, state.message_params ?? {}) : null;
  const preview = state.previews.find((p) => p.epoch === previewEpoch) ?? state.previews[state.previews.length - 1];

  const requirement = (ok: boolean, okText: string, badText: string, soft = false, action?: { label: string; onClick: () => void }) => (
    <Stack direction="row" spacing={1} alignItems="center" key={okText}>
      {ok ? <CheckCircleIcon fontSize="small" color="success" /> : <ErrorOutlineIcon fontSize="small" color={soft ? "info" : "warning"} />}
      <Typography variant="body2">{ok ? okText : badText}</Typography>
      {!ok && action && (
        <Button size="small" onClick={action.onClick} sx={{ py: 0 }}>
          {action.label}
        </Button>
      )}
    </Stack>
  );

  return (
    <Card>
      <CardHeader avatar={<ModelTrainingIcon color="primary" />} title={t("train.title")} subheader={t("train.subtitle")} action={<Chip label={t(`train.status.${state.status}` as TKey)} color={STATUS_COLOR[state.status] ?? "default"} />} />
      <CardContent>
        <Stack spacing={2}>
          {!running && (
            <Stack spacing={0.5}>
              {requirement(!!report?.has_consent, t("train.req.consent"), t("train.req.consentMissing"), false, !report?.has_consent ? { label: t("train.req.goVoice"), onClick: () => onGo("voice") } : undefined)}
              {requirement((report?.minutes ?? 0) >= (report?.min_minutes ?? 5), t("train.req.minutes", { minutes: (report?.minutes ?? 0).toFixed(1), min: report?.min_minutes ?? 5 }), t("train.req.minutes", { minutes: (report?.minutes ?? 0).toFixed(1), min: report?.min_minutes ?? 5 }), false, (report?.minutes ?? 0) < (report?.min_minutes ?? 5) ? { label: t("train.req.goRecord"), onClick: () => onGo("record") } : undefined)}
              {base && requirement(base.installed, t("train.req.base", { name: base.name }), t("train.req.baseMissing", { name: base.name, size: base.size_mb }), true)}
              {requirement(gpuOk, t("train.req.gpu"), t("train.req.gpuMissing"))}
              {calibration && report && report.count > 0 && (
                <Typography variant="body2" color="text.secondary" sx={{ pt: 0.5 }}>
                  {calibration.basis === "none" ? t("train.estimate.none") : t(`train.estimate.${calibration.basis}` as TKey, { time: duration(estimate ?? 0) })}
                </Typography>
              )}
            </Stack>
          )}

          <Accordion disableGutters variant="outlined" disabled={running}>
            <AccordionSummary expandIcon={<ExpandMoreIcon />}>
              <Typography variant="subtitle2">{t("train.params")}</Typography>
            </AccordionSummary>
            <AccordionDetails>
              <Box sx={{ display: "grid", gap: 2, gridTemplateColumns: { xs: "1fr", sm: "1fr 1fr", md: "1fr 1fr 1fr" } }}>
                {FIELDS.map((f) => (
                  <TextField key={f.key} type="number" size="small" label={t(`train.f.${f.key}` as TKey)} helperText={t(`train.h.${f.key}` as TKey)} value={params[f.key]} onChange={(e) => setParams({ ...params, [f.key]: Number(e.target.value) })} inputProps={{ step: f.step, min: f.min }} />
                ))}
              </Box>
              <Tooltip title={t("train.h.quiet_pauses")}>
                <FormControlLabel sx={{ mt: 1 }} control={<Switch checked={params.quiet_pauses} onChange={(e) => setParams({ ...params, quiet_pauses: e.target.checked })} />} label={t("train.f.quiet_pauses")} />
              </Tooltip>
              <Stack direction="row" spacing={1} sx={{ mt: 1 }}>
                <Button size="small" variant="contained" onClick={saveParams} disabled={busy || !paramsDirty}>
                  {t("train.saveParams")}
                </Button>
                <Button size="small" onClick={() => setParams({ ...defaults })}>
                  {t("train.reset")}
                </Button>
              </Stack>
            </AccordionDetails>
          </Accordion>

          <Stack direction={{ xs: "column", sm: "row" }} spacing={2} alignItems={{ sm: "center" }}>
            {!running ? (
              <Button variant="contained" size="large" startIcon={<PlayArrowIcon />} onClick={() => call(() => api.startTraining())} disabled={busy || !canStart || paramsDirty}>
                {t("train.start")}
              </Button>
            ) : (
              <Button variant="outlined" color="error" size="large" startIcon={<StopIcon />} onClick={() => call(() => api.cancelTraining())} disabled={busy || state.stage_key === "stopping"}>
                {t("train.cancel")}
              </Button>
            )}
            <Box sx={{ flex: 1 }}>
              <Typography variant="subtitle2">{mine ? (stageText ?? t("train.waiting")) : t("train.waiting")}</Typography>
              {isTraining && (
                <Typography variant="body2" color="text.secondary">
                  {t("train.epoch", { epoch: state.epoch, total: state.total_epochs })} · {t("train.batch", { batch: state.batch, batches: state.batches })}
                  {eta !== null && eta > 0 ? ` · ${t("train.eta", { time: duration(eta) })}` : ""}
                </Typography>
              )}
            </Box>
          </Stack>

          {(running || state.status === "done") && mine && (
            <Box>
              <LinearProgress variant={total > 0 ? "determinate" : "indeterminate"} value={pct} sx={{ height: 10, borderRadius: 5 }} />
              <Stack direction="row" justifyContent="space-between" sx={{ mt: 0.5 }}>
                <Typography variant="caption" color="text.secondary">
                  {state.status === "downloading" && total > 0 ? `${(current / (1 << 20)).toFixed(0)} / ${(total / (1 << 20)).toFixed(0)} MB` : total > 0 ? `${current} / ${total}` : ""}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  {pct.toFixed(0)} %
                </Typography>
              </Stack>
            </Box>
          )}

          {mine && (state.metrics || lastVal) && (
            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
              {state.metrics?.loss_g != null && <Metric label={t("train.m.lossG")} value={state.metrics.loss_g.toFixed(2)} />}
              {state.metrics?.loss_d != null && <Metric label={t("train.m.lossD")} value={state.metrics.loss_d.toFixed(2)} />}
              {lastVal?.val_mel != null && <Metric label={t("train.m.valMel")} value={lastVal.val_mel.toFixed(3)} />}
              {lastVal?.val_mos != null && <Metric label={t("train.m.valMos")} value={lastVal.val_mos.toFixed(2)} />}
            </Stack>
          )}

          {mine && state.validation.length > 1 && (
            <Suspense fallback={<LinearProgress />}>
              <TrainingCharts validation={state.validation} />
            </Suspense>
          )}

          {mine && (running || state.previews.length > 0) && (
            <Box sx={{ p: 1.5, border: 1, borderColor: "divider", borderRadius: 2 }}>
              <Stack direction="row" spacing={2} alignItems="center" sx={{ mb: 1 }}>
                <Typography variant="subtitle2" sx={{ flex: 1 }}>
                  {t("train.previews")}
                </Typography>
                {state.previews.length > 0 && (
                  <TextField select size="small" value={preview?.epoch ?? ""} onChange={(e) => setPreviewEpoch(Number(e.target.value))} sx={{ minWidth: 150 }}>
                    {state.previews.map((p) => (
                      <MenuItem key={p.epoch} value={p.epoch}>
                        {t("train.previewEpoch", { epoch: p.epoch })}
                      </MenuItem>
                    ))}
                  </TextField>
                )}
              </Stack>
              {preview ? (
                <Stack spacing={1}>
                  {preview.items.map((item) => (
                    <AudioPlayer key={item.url} src={item.url} label={item.text} dense />
                  ))}
                </Stack>
              ) : (
                <Typography variant="body2" color="text.secondary">
                  {t("train.noPreviews", { n: voice.training.preview_every })}
                </Typography>
              )}
            </Box>
          )}

          {mine && !running && state.resumable && state.status !== "idle" && (
            <Alert severity={state.status === "done" ? "success" : "warning"} variant="outlined">
              <Stack spacing={1}>
                <Typography variant="body2">
                  {state.status === "done" ? t("train.done") : t("train.resumeHint")}
                  {state.status === "done" && state.stopped_early ? ` ${t("train.stoppedEarly", { epoch: state.epoch, patience: voice.training.patience })}` : ""}
                </Typography>
                <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
                  {state.status !== "done" && (
                    <Button variant="contained" size="small" startIcon={<RestartAltIcon />} onClick={() => call(() => api.resumeTraining(0))} disabled={busy}>
                      {t("train.resume")}
                    </Button>
                  )}
                  <TextField type="number" size="small" label={t("train.extraEpochs")} value={extra} onChange={(e) => setExtra(Math.max(10, Number(e.target.value)))} inputProps={{ step: 50, min: 10 }} sx={{ width: 140 }} />
                  <Button size="small" variant="outlined" startIcon={<RestartAltIcon />} onClick={() => call(() => api.resumeTraining(extra))} disabled={busy}>
                    {t("train.extraEpochs")}
                  </Button>
                  {state.status !== "done" && state.job_id && (
                    <Button size="small" startIcon={<IosShareIcon />} onClick={() => call(() => api.exportJob(state.job_id!))} disabled={busy}>
                      {t("train.exportNow")}
                    </Button>
                  )}
                </Stack>
              </Stack>
            </Alert>
          )}

          {mine && state.status === "failed" && (
            <Alert severity="error">
              {state.error ?? t("train.failed")} {t("train.failedHint")}
            </Alert>
          )}

          {system && (
            <Typography variant="caption" color="text.secondary">
              {t("train.diskHint", { free: system.disk_free_gb })}
            </Typography>
          )}

          <Box>
            <Button size="small" onClick={() => setShowLog((v) => !v)} startIcon={showLog ? <ExpandLessIcon /> : <ExpandMoreIcon />}>
              {t("train.log", { n: log.length })}
            </Button>
            <Collapse in={showLog}>
              <Box
                ref={logRef}
                sx={{ mt: 1, maxHeight: 320, overflow: "auto", p: 1.5, borderRadius: 2, bgcolor: (th) => (th.palette.mode === "dark" ? "#05080f" : "#0f172a"), color: "#cbd5e1", fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace", fontSize: 11, lineHeight: 1.5, whiteSpace: "pre-wrap", wordBreak: "break-all" }}
              >
                {log.length === 0 ? "—" : log.join("\n")}
              </Box>
            </Collapse>
          </Box>
        </Stack>
      </CardContent>
    </Card>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <Box sx={{ px: 1.5, py: 1, border: 1, borderColor: "divider", borderRadius: 2, minWidth: 130 }}>
      <Typography variant="caption" color="text.secondary" display="block">
        {label}
      </Typography>
      <Typography variant="subtitle1" fontWeight={600}>
        {value}
      </Typography>
    </Box>
  );
}
