import { useEffect, useMemo, useRef, useState } from "react";
import { Accordion, AccordionDetails, AccordionSummary, Box, Button, Card, CardContent, CardHeader, Chip, MenuItem, Slider, Stack, TextField, Typography } from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import HearingIcon from "@mui/icons-material/Hearing";
import { EmptyState } from "./EmptyState";
import { LexiconEditor } from "./LexiconCard";
import RecordVoiceOverIcon from "@mui/icons-material/RecordVoiceOver";
import VolumeUpIcon from "@mui/icons-material/VolumeUp";
import { api, type Job, type VoiceSettings, type VoicesPayload } from "../api";
import { errorText, useI18n, type TKey } from "../i18n";
import { playSequence } from "../lib/audio";
import { AudioPlayer } from "./AudioPlayer";

type Props = { jobs: Job[]; voice: VoiceSettings; baseVoiceName: string | null; onVoices: (p: VoicesPayload) => void; onError: (message: string) => void; onGo: (tab: "record" | "train") => void };
type Target = { jobId: string; file: string; label: string; voiceId?: string };
type Sample = { id: number; url: string; text: string; label: string };

const VARIANTS = new Set(["last", "best_mos", "best_mel"]);
const DEFAULT_TEXT: Record<string, string> = {
  cs: "Dobrý den, tohle je můj nový hlas. Jak se vám líbí?",
  en: "Hello, this is my new voice. How do you like it?",
};

/** Text-to-speech playground for the exported voices of a run, plus downloads and Home Assistant instructions. */
export function TestCard({ jobs, voice, baseVoiceName, onVoices, onError, onGo }: Props) {
  const { t } = useI18n();
  const runs = useMemo(() => jobs.filter((j) => j.exports.length > 0), [jobs]);
  const [jobId, setJobId] = useState("");
  const [file, setFile] = useState("");
  const [text, setText] = useState("");
  const [edited, setEdited] = useState(false);
  const [speed, setSpeed] = useState(1.0);
  const [noise, setNoise] = useState(0.667);
  const [noiseW, setNoiseW] = useState(0.8);
  const [busy, setBusy] = useState(false);
  const [samples, setSamples] = useState<Sample[]>([]);
  const [compare, setCompare] = useState(""); // "<job_id>|<file>" of a second voice to hear right after the first
  const counter = useRef(0);

  const job = runs.find((j) => j.job_id === jobId) ?? runs[0];

  useEffect(() => {
    if (job && job.job_id !== jobId) setJobId(job.job_id);
  }, [job, jobId]);
  // the sample text follows the language of the voice, not the language of the interface
  useEffect(() => {
    if (job && !edited) setText(DEFAULT_TEXT[job.language] ?? DEFAULT_TEXT.en);
  }, [job, edited]);
  useEffect(() => {
    // a run that stopped early is best represented by its best checkpoint, not by the last epoch
    const preferred = job?.stopped_early ? "best_mel" : "last";
    if (job && !job.exports.some((e) => e.file === file)) setFile((job.exports.find((e) => e.variant === preferred) ?? job.exports[0]).file);
  }, [job, file]);

  const variantLabel = (variant: string) => (VARIANTS.has(variant) ? t(`test.variant.${variant}` as TKey) : variant);
  const runLabel = (r: Job) => new Date(r.created_at).toLocaleString();
  const compareOptions = [
    // the untouched base voice first: it shows what fine-tuning changed
    ...(job && baseVoiceName ? [{ value: `base|${job.language}`, label: t("test.baseVoice", { name: baseVoiceName }) }] : []),
    ...runs.flatMap((r) => r.exports.map((e) => ({ value: `${r.job_id}|${e.file}`, label: `${runLabel(r)} · ${variantLabel(e.variant)}` }))),
  ].filter((o) => o.value !== `${job?.job_id}|${file}`);

  const speak = async () => {
    if (!job || !file || !text.trim()) return;
    const variantOf = (j: Job, f: string) => variantLabel(j.exports.find((e) => e.file === f)?.variant ?? "");
    const targets: Target[] = [{ jobId: job.job_id, file, label: variantOf(job, file) }];
    const [cmpJob, cmpFile] = compare.split("|");
    const other = runs.find((r) => r.job_id === cmpJob);
    if (cmpJob === "base" && cmpFile === job.language && baseVoiceName) targets.push({ jobId: "base", file: job.language, label: t("test.baseVoice", { name: baseVoiceName }), voiceId: job.voice_id ?? undefined });
    else if (other && other.exports.some((e) => e.file === cmpFile)) targets.push({ jobId: other.job_id, file: cmpFile, label: `${runLabel(other)} · ${variantOf(other, cmpFile)}` });
    if (targets.length > 1) targets[0].label = `${runLabel(job)} · ${targets[0].label}`;
    setBusy(true);
    try {
      const urls: string[] = [];
      const made: Sample[] = [];
      for (const target of targets) {
        const blob = await api.synthesize({ job_id: target.jobId, file: target.file, voice_id: target.voiceId, text: text.trim(), length_scale: speed, noise_scale: noise, noise_w_scale: noiseW });
        const url = URL.createObjectURL(blob);
        counter.current += 1;
        made.push({ id: counter.current, url, text: text.trim(), label: `${target.label} · ${speed.toFixed(2)}×` });
        urls.push(url);
      }
      setSamples((prev) => [...made.slice().reverse(), ...prev].slice(0, 12));
      playSequence(urls);
    } catch (e) {
      onError(errorText(t, e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHeader avatar={<RecordVoiceOverIcon color="primary" />} title={t("test.title")} subheader={t("test.subtitle")} />
      <CardContent>
        {!job ? (
          <EmptyState icon={<HearingIcon color="disabled" sx={{ fontSize: 48 }} />} title={t("test.noModel")} text={t("test.noModelHint")} action={{ label: t("test.noModelAction"), onClick: () => onGo("train") }} />
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
              {compareOptions.length > 0 && (
                <TextField select size="small" label={t("test.compare")} value={compareOptions.some((o) => o.value === compare) ? compare : ""} onChange={(e) => setCompare(e.target.value)} sx={{ minWidth: 260 }} helperText={t("test.compareHint")}>
                  <MenuItem value="">{t("test.compareNone")}</MenuItem>
                  {compareOptions.map((o) => (
                    <MenuItem key={o.value} value={o.value}>
                      {o.label}
                    </MenuItem>
                  ))}
                </TextField>
              )}
            </Stack>

            <TextField label={t("test.text")} value={text} onChange={(e) => {
                setEdited(true);
                setText(e.target.value);
              }} multiline minRows={2} fullWidth />

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
            </Stack>

            {samples.length > 0 && (
              <Box>
                <Typography variant="subtitle2" gutterBottom>
                  {t("test.history")}
                </Typography>
                <Stack spacing={0.5}>
                  {samples.map((s) => (
                    <AudioPlayer key={s.id} src={s.url} dense label={s.text} secondary={<Chip size="small" variant="outlined" label={s.label} sx={{ flexShrink: 0 }} />} />
                  ))}
                </Stack>
              </Box>
            )}

            <Accordion disableGutters variant="outlined">
              <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                <Typography variant="subtitle2">{t("lex.title")}</Typography>
                <Typography variant="body2" color="text.secondary" sx={{ ml: 1 }}>
                  {t("lex.subtitle")}
                </Typography>
              </AccordionSummary>
              <AccordionDetails>
                <LexiconEditor voice={voice} onVoices={onVoices} onError={onError} />
              </AccordionDetails>
            </Accordion>
          </Stack>
        )}
      </CardContent>
    </Card>
  );
}
