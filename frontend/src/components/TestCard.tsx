import { useEffect, useMemo, useRef, useState } from "react";
import { Alert, Box, Button, Card, CardContent, CardHeader, Chip, IconButton, MenuItem, Slider, Stack, TextField, Typography } from "@mui/material";
import RecordVoiceOverIcon from "@mui/icons-material/RecordVoiceOver";
import VolumeUpIcon from "@mui/icons-material/VolumeUp";
import DownloadIcon from "@mui/icons-material/Download";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import { api, type Job } from "../api";
import { errorText, useI18n, type TKey } from "../i18n";

type Props = { jobs: Job[]; onError: (message: string) => void };
type Sample = { id: number; url: string; text: string; label: string };

const VARIANTS = new Set(["last", "best_mos", "best_mel"]);

/** Text-to-speech playground for the exported voices of a run, plus downloads and Home Assistant instructions. */
export function TestCard({ jobs, onError }: Props) {
  const { t } = useI18n();
  const runs = useMemo(() => jobs.filter((j) => j.exports.length > 0), [jobs]);
  const [jobId, setJobId] = useState("");
  const [file, setFile] = useState("");
  const [text, setText] = useState(() => t("test.defaultText"));
  const [speed, setSpeed] = useState(1.0);
  const [noise, setNoise] = useState(0.667);
  const [noiseW, setNoiseW] = useState(0.8);
  const [busy, setBusy] = useState(false);
  const [samples, setSamples] = useState<Sample[]>([]);
  const counter = useRef(0);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const job = runs.find((j) => j.job_id === jobId) ?? runs[0];

  useEffect(() => {
    if (job && job.job_id !== jobId) setJobId(job.job_id);
  }, [job, jobId]);
  useEffect(() => {
    if (job && !job.exports.some((e) => e.file === file)) setFile((job.exports.find((e) => e.variant === "last") ?? job.exports[0]).file);
  }, [job, file]);

  const play = (url: string) => {
    audioRef.current?.pause();
    const audio = new Audio(url);
    audioRef.current = audio;
    audio.play().catch(() => undefined);
  };

  const speak = async () => {
    if (!job || !file || !text.trim()) return;
    setBusy(true);
    try {
      const blob = await api.synthesize({ job_id: job.job_id, file, text: text.trim(), length_scale: speed, noise_scale: noise, noise_w_scale: noiseW });
      const url = URL.createObjectURL(blob);
      const variant = job.exports.find((e) => e.file === file)?.variant ?? "";
      counter.current += 1;
      setSamples((prev) => [{ id: counter.current, url, text: text.trim(), label: `${variantLabel(variant)} · ${speed.toFixed(2)}×` }, ...prev].slice(0, 12));
      play(url);
    } catch (e) {
      onError(errorText(t, e));
    } finally {
      setBusy(false);
    }
  };

  const variantLabel = (variant: string) => (VARIANTS.has(variant) ? t(`test.variant.${variant}` as TKey) : variant);

  return (
    <Card>
      <CardHeader avatar={<RecordVoiceOverIcon color="primary" />} title={t("test.title")} subheader={t("test.subtitle")} />
      <CardContent>
        {!job ? (
          <Typography color="text.secondary">{t("test.noModel")}</Typography>
        ) : (
          <Stack spacing={2}>
            <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
              <TextField select size="small" label={t("test.run")} value={job.job_id} onChange={(e) => setJobId(e.target.value)} sx={{ minWidth: 260 }}>
                {runs.map((r) => (
                  <MenuItem key={r.job_id} value={r.job_id}>
                    {r.name} · {new Date(r.created_at).toLocaleString()}
                  </MenuItem>
                ))}
              </TextField>
              <TextField select size="small" label={t("test.variant")} value={file} onChange={(e) => setFile(e.target.value)} sx={{ minWidth: 220 }}>
                {job.exports.map((e) => (
                  <MenuItem key={e.file} value={e.file}>
                    {variantLabel(e.variant)}
                  </MenuItem>
                ))}
              </TextField>
            </Stack>

            <TextField label={t("test.text")} value={text} onChange={(e) => setText(e.target.value)} multiline minRows={2} fullWidth />

            <Box sx={{ display: "grid", gap: 3, gridTemplateColumns: { xs: "1fr", sm: "1fr 1fr 1fr" } }}>
              <Box>
                <Typography variant="caption" color="text.secondary">
                  {t("test.speed")}: {speed.toFixed(2)}
                </Typography>
                <Slider size="small" min={0.6} max={1.6} step={0.05} value={speed} onChange={(_, v) => setSpeed(v as number)} />
              </Box>
              <Box>
                <Typography variant="caption" color="text.secondary">
                  {t("test.noise")}: {noise.toFixed(2)}
                </Typography>
                <Slider size="small" min={0} max={1.2} step={0.05} value={noise} onChange={(_, v) => setNoise(v as number)} />
              </Box>
              <Box>
                <Typography variant="caption" color="text.secondary">
                  {t("test.noiseW")}: {noiseW.toFixed(2)}
                </Typography>
                <Slider size="small" min={0} max={1.2} step={0.05} value={noiseW} onChange={(_, v) => setNoiseW(v as number)} />
              </Box>
            </Box>

            <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap" useFlexGap>
              <Button variant="contained" size="large" startIcon={<VolumeUpIcon />} onClick={speak} disabled={busy || !text.trim()}>
                {busy ? t("test.speaking") : t("test.speak")}
              </Button>
              {job.bundle_url && (
                <Button variant="outlined" startIcon={<DownloadIcon />} href={job.bundle_url} download>
                  {t("test.download")}
                </Button>
              )}
            </Stack>

            {samples.length > 0 && (
              <Box>
                <Typography variant="subtitle2" gutterBottom>
                  {t("test.history")}
                </Typography>
                <Stack spacing={0.5}>
                  {samples.map((s) => (
                    <Stack key={s.id} direction="row" spacing={1} alignItems="center">
                      <IconButton size="small" onClick={() => play(s.url)}>
                        <PlayArrowIcon />
                      </IconButton>
                      <Chip size="small" variant="outlined" label={s.label} />
                      <Typography variant="body2" noWrap sx={{ flex: 1 }}>
                        {s.text}
                      </Typography>
                    </Stack>
                  ))}
                </Stack>
              </Box>
            )}

            <Box>
              <Typography variant="subtitle2" gutterBottom>
                {t("test.files")}
              </Typography>
              <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                {job.exports.map((e) => (
                  <Button key={e.file} size="small" href={e.url} download startIcon={<DownloadIcon />}>
                    {e.file} ({(e.size / (1 << 20)).toFixed(0)} MB)
                  </Button>
                ))}
              </Stack>
            </Box>
            <Alert severity="info" variant="outlined">
              {t("test.ha")}
            </Alert>
          </Stack>
        )}
      </CardContent>
    </Card>
  );
}
