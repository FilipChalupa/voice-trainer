import { useEffect, useMemo, useRef, useState } from "react";
import { Alert, Box, Button, Card, CardContent, CardHeader, Slider, Stack, Typography, useTheme } from "@mui/material";
import TuneIcon from "@mui/icons-material/Tune";
import { api, type Processing, type ProcessingAnalysis, type Recording, type VoiceSettings, type VoicesPayload } from "../api";
import { errorText, useI18n, type TKey } from "../i18n";
import { AudioPlayer } from "./AudioPlayer";

type Props = { voice: VoiceSettings; payload: VoicesPayload; disabled: boolean; onVoices: (p: VoicesPayload) => void; onError: (message: string) => void };

const CONTROLS: { key: keyof Processing; step: number; unit: "Hz" | "dB" }[] = [
  { key: "highpass_hz", step: 10, unit: "Hz" },
  { key: "bass_db", step: 0.5, unit: "dB" },
  { key: "bass_hz", step: 10, unit: "Hz" },
  { key: "treble_db", step: 0.5, unit: "dB" },
  { key: "treble_hz", step: 250, unit: "Hz" },
];
const same = (a: Processing, b: Processing) => CONTROLS.every((c) => a[c.key] === b[c.key]);
const signed = (v: number) => `${v > 0 ? "+" : ""}${v.toFixed(1)}`;

/** Tone correction of the copies that go into training: sliders, the spectrum before and after, and one take
 *  to compare by ear. The takes themselves are never changed. */
export function ProcessingCard({ voice, payload, disabled, onVoices, onError }: Props) {
  const { t } = useI18n();
  const [params, setParams] = useState<Processing>(voice.processing);
  const [analysis, setAnalysis] = useState<ProcessingAnalysis | null>(null);
  const [takes, setTakes] = useState<Recording[]>([]);
  const [take, setTake] = useState(0);
  const [preview, setPreview] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const previewUrl = useRef<string | null>(null);

  useEffect(() => setParams(voice.processing), [voice.id, voice.processing]);
  useEffect(() => {
    api
      .recordings({ brief: true })
      .then((r) => {
        // the longer takes say more about the tone
        const usable = r.items.filter((x) => x.duration >= 3).slice(-40);
        setTakes(usable);
        setTake(Math.max(0, usable.length - 1));
      })
      .catch(() => setTakes([]));
  }, [voice.id]);

  // the chart and the take follow the sliders with a short delay
  const current = takes[take];
  useEffect(() => {
    const timer = setTimeout(() => {
      api
        .processingAnalysis(params)
        .then(setAnalysis)
        .catch(() => setAnalysis(null));
      if (!current) return;
      api
        .processingPreview(current.id, params)
        .then((blob) => {
          if (previewUrl.current) URL.revokeObjectURL(previewUrl.current);
          previewUrl.current = URL.createObjectURL(blob);
          setPreview(previewUrl.current);
        })
        .catch(() => setPreview(null));
    }, 350);
    return () => clearTimeout(timer);
  }, [params, current?.id]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(
    () => () => {
      if (previewUrl.current) URL.revokeObjectURL(previewUrl.current);
    },
    [],
  );

  const save = async () => {
    setSaving(true);
    try {
      onVoices(await api.saveVoice({ processing: params }));
    } catch (e) {
      onError(errorText(t, e));
    } finally {
      setSaving(false);
    }
  };

  const active = !same(params, payload.processing_defaults);
  const bass = analysis?.bands.find((b) => b.band === "bass");
  const label = (c: (typeof CONTROLS)[number]) => {
    const value = params[c.key];
    if (c.key === "highpass_hz" && value === 0) return t("proc.off");
    return c.unit === "dB" ? `${signed(value)} dB` : `${value} Hz`;
  };

  return (
    <Card>
      <CardHeader avatar={<TuneIcon color="primary" />} title={t("proc.title")} subheader={t("proc.subtitle")} />
      <CardContent>
        <Stack spacing={2}>
          <Typography variant="body2" color="text.secondary">
            {t("proc.help")}
          </Typography>
          <Box sx={{ display: "grid", gap: 3, gridTemplateColumns: { xs: "1fr", sm: "1fr 1fr", md: "1fr 1fr 1fr" } }}>
            {CONTROLS.map((c) => (
              <Box key={c.key}>
                <Typography variant="body2">
                  {t(`proc.f.${c.key}` as TKey)}: <b>{label(c)}</b>
                </Typography>
                <Slider
                  size="small"
                  min={payload.processing_limits[c.key][0]}
                  max={payload.processing_limits[c.key][1]}
                  step={c.step}
                  value={params[c.key]}
                  onChange={(_, v) => setParams({ ...params, [c.key]: c.key === "highpass_hz" && (v as number) > 0 && (v as number) < 40 ? 40 : (v as number) })}
                  disabled={disabled}
                  aria-label={t(`proc.f.${c.key}` as TKey)}
                />
                <Typography variant="caption" color="text.secondary">
                  {t(`proc.h.${c.key}` as TKey)}
                </Typography>
              </Box>
            ))}
          </Box>

          {analysis?.available && (
            <Box>
              <Spectrum curve={analysis.curve} />
              <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap sx={{ mt: 0.5 }}>
                <Legend color="text.disabled" label={t("proc.before")} />
                <Legend color="primary.main" label={t("proc.after")} />
                {bass && (
                  <Typography variant="caption" color={bass.after_db > 2 ? "warning.main" : "text.secondary"}>
                    {t("proc.bassLine", { before: signed(bass.before_db), after: signed(bass.after_db) })}
                  </Typography>
                )}
              </Stack>
            </Box>
          )}

          {current && (
            <Stack spacing={0.5}>
              <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
                <Typography variant="subtitle2">{t("proc.listen")}</Typography>
                <Button size="small" onClick={() => setTake((i) => (i + takes.length - 1) % takes.length)} disabled={takes.length < 2}>
                  {t("proc.otherTake")}
                </Button>
              </Stack>
              <Typography variant="body2" color="text.secondary" noWrap>
                {current.text}
              </Typography>
              <AudioPlayer src={current.url} dense label={t("proc.before")} />
              {preview && <AudioPlayer key={preview} src={preview} dense label={t("proc.after")} />}
            </Stack>
          )}

          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap alignItems="center">
            <Button variant="outlined" onClick={() => analysis?.suggested && setParams(analysis.suggested)} disabled={disabled || !analysis?.suggested}>
              {t("proc.suggest")}
            </Button>
            <Button onClick={() => setParams(payload.processing_defaults)} disabled={disabled || !active}>
              {t("proc.reset")}
            </Button>
            <Box sx={{ flex: 1 }} />
            <Button variant="contained" onClick={save} disabled={disabled || saving || same(params, voice.processing)}>
              {t("proc.save")}
            </Button>
          </Stack>
          {!same(voice.processing, payload.processing_defaults) && same(params, voice.processing) && (
            <Alert severity="info" variant="outlined">
              {t("proc.saved")}
            </Alert>
          )}
        </Stack>
      </CardContent>
    </Card>
  );
}

function Legend({ color, label }: { color: string; label: string }) {
  return (
    <Stack direction="row" spacing={0.5} alignItems="center">
      <Box sx={{ width: 14, height: 3, borderRadius: 1, bgcolor: color }} />
      <Typography variant="caption" color="text.secondary">
        {label}
      </Typography>
    </Stack>
  );
}

const W = 600;
const H = 150;
const FLOOR = -50;
const TICKS = [50, 100, 250, 500, 1000, 2000, 4000, 8000];

/** Average spectrum of the takes before and after the correction, on a logarithmic frequency axis. */
function Spectrum({ curve }: { curve: [number, number, number][] }) {
  const theme = useTheme();
  const { x, lines } = useMemo(() => {
    const lo = Math.log(curve[0]?.[0] ?? 40);
    const hi = Math.log(curve[curve.length - 1]?.[0] ?? 10000);
    const x = (f: number) => ((Math.log(f) - lo) / (hi - lo || 1)) * W;
    const y = (db: number) => (Math.min(0, Math.max(FLOOR, db)) / FLOOR) * (H - 16) + 4;
    const line = (index: 1 | 2) => curve.map((p) => `${x(p[0]).toFixed(1)},${y(p[index]).toFixed(1)}`).join(" ");
    return { x, lines: [line(1), line(2)] };
  }, [curve]);
  if (curve.length < 2) return null;
  return (
    <Box component="svg" viewBox={`0 0 ${W} ${H}`} sx={{ width: "100%", height: "auto", display: "block", bgcolor: "action.hover", borderRadius: 1 }} role="img" aria-label="spectrum">
      {TICKS.filter((f) => f >= curve[0][0] && f <= curve[curve.length - 1][0]).map((f) => (
        <g key={f}>
          <line x1={x(f)} x2={x(f)} y1={0} y2={H - 14} stroke={theme.palette.divider} strokeWidth={1} />
          <text x={x(f)} y={H - 3} fontSize={10} textAnchor="middle" fill={theme.palette.text.secondary}>
            {f >= 1000 ? `${f / 1000} kHz` : `${f} Hz`}
          </text>
        </g>
      ))}
      <polyline points={lines[0]} fill="none" stroke={theme.palette.text.disabled} strokeWidth={2} />
      <polyline points={lines[1]} fill="none" stroke={theme.palette.primary.main} strokeWidth={2.5} />
    </Box>
  );
}
