import { useEffect, useRef, useState } from "react";
import { Alert, Button, Dialog, DialogActions, DialogContent, DialogTitle, Stack, Typography } from "@mui/material";
import MicIcon from "@mui/icons-material/Mic";
import { api, type Recording } from "../api";
import { useI18n } from "../i18n";
import { Recorder } from "../lib/recorder";
import { LevelMeter } from "./LevelMeter";

type Props = { open: boolean; recorder: Recorder; deviceId: string; agc: boolean; sentence: string; recordings: Recording[]; onClose: () => void; onDone?: () => void; onError: (message: string) => void };
type Step = "intro" | "silence" | "speech" | "result";
type Result = { noiseDb: number; speechDb: number; peak: number; snr: number; previousDb: number | null; tone: { tone_db: number | null; dataset_tone_db: number | null; bass_corrected: boolean } | null };

/** Bass this far above the middle of the voice means the microphone is too close (measured the same way as on the takes). */
const BOOMY_DB = 2.5;

const db = (x: number) => 20 * Math.log10(Math.max(x, 1e-6));

/** Levels of a quiet room and of one read sentence, with advice before a long session starts. */
function measure(samples: Float32Array): { rms: number; peak: number; speechRms: number } {
  const frame = 220; // 10 ms at 22.05 kHz
  const rmsFrames: number[] = [];
  let peak = 0;
  for (let i = 0; i + frame <= samples.length; i += frame) {
    let sum = 0;
    for (let j = i; j < i + frame; j++) {
      const v = samples[j];
      sum += v * v;
      if (Math.abs(v) > peak) peak = Math.abs(v);
    }
    rmsFrames.push(Math.sqrt(sum / frame));
  }
  if (!rmsFrames.length) return { rms: 0, peak: 0, speechRms: 0 };
  const total = Math.sqrt(rmsFrames.reduce((a, r) => a + r * r, 0) / rmsFrames.length);
  const top = Math.max(...rmsFrames);
  const loud = rmsFrames.filter((r) => r > top * 0.1); // frames within 20 dB of the loudest: the spoken part
  const speechRms = Math.sqrt(loud.reduce((a, r) => a + r * r, 0) / Math.max(1, loud.length));
  return { rms: total, peak, speechRms };
}

export function MicCheckDialog({ open, recorder, deviceId, agc, sentence, recordings, onClose, onDone, onError }: Props) {
  const { t } = useI18n();
  const [step, setStep] = useState<Step>("intro");
  const [level, setLevel] = useState(0);
  const [peak, setPeak] = useState(0);
  const [result, setResult] = useState<Result | null>(null);
  const noiseRef = useRef(0);

  useEffect(() => {
    if (open) {
      setStep("intro");
      setResult(null);
    }
  }, [open]);

  const run = async () => {
    try {
      await recorder.init(deviceId || undefined, agc);
      setStep("silence");
      const quiet = await recorder.record(3, (l) => setLevel(l.rms * 6), { minSeconds: 3, silenceMs: 100000 });
      noiseRef.current = measure(quiet.samples).rms;
      setStep("speech");
      const spoken = await recorder.record(15, (l) => {
        setLevel(l.rms * 6);
        setPeak(l.peak);
      }, { silenceMs: 1100, minSeconds: 1.2 });
      const m = measure(spoken.samples);
      // the tone is measured by the server, the same way as on the takes, so the numbers compare
      const tone = await api.measureTone(spoken.wav).catch(() => null);
      const previous = recordings.map((r) => r.quality.speech_db).filter((x): x is number => typeof x === "number").sort((a, b) => a - b);
      setResult({
        noiseDb: db(noiseRef.current),
        speechDb: db(m.speechRms),
        peak: m.peak,
        snr: db(m.speechRms) - db(noiseRef.current),
        previousDb: previous.length >= 5 ? previous[Math.floor(previous.length / 2)] : null,
        tone,
      });
      setStep("result");
      onDone?.();
    } catch (e) {
      onError(String(e));
      setStep("intro");
    }
  };

  const advice: { severity: "success" | "warning" | "error"; text: string }[] = [];
  if (result) {
    if (result.noiseDb > -45) advice.push({ severity: "error", text: t("mic.noisy", { db: result.noiseDb.toFixed(0) }) });
    else if (result.noiseDb > -55) advice.push({ severity: "warning", text: t("mic.someNoise", { db: result.noiseDb.toFixed(0) }) });
    else advice.push({ severity: "success", text: t("mic.quiet", { db: result.noiseDb.toFixed(0) }) });
    if (result.peak >= 0.98) advice.push({ severity: "error", text: t("mic.clipping") });
    else if (result.peak < 0.15) advice.push({ severity: "warning", text: t("mic.tooQuiet", { peak: Math.round(result.peak * 100) }) });
    else advice.push({ severity: "success", text: t("mic.levelOk", { peak: Math.round(result.peak * 100) }) });
    if (result.snr < 25) advice.push({ severity: "warning", text: t("mic.lowSnr", { snr: result.snr.toFixed(0) }) });
    if (result.previousDb !== null && Math.abs(result.speechDb - result.previousDb) > 6) {
      advice.push({ severity: "warning", text: t("mic.differentLevel", { now: result.speechDb.toFixed(0), before: result.previousDb.toFixed(0) }) });
    }
    const tone = result.tone;
    if (tone && tone.tone_db !== null) {
      const now = tone.tone_db.toFixed(1);
      if (tone.dataset_tone_db !== null && Math.abs(tone.tone_db - tone.dataset_tone_db) > BOOMY_DB) {
        advice.push({ severity: "warning", text: t(tone.tone_db > tone.dataset_tone_db ? "mic.toneCloser" : "mic.toneFarther", { now, before: tone.dataset_tone_db.toFixed(1) }) });
      } else if (tone.tone_db > BOOMY_DB) {
        advice.push({ severity: "warning", text: t(tone.bass_corrected ? "mic.boomyCorrected" : "mic.boomy", { now }) });
      } else {
        advice.push({ severity: "success", text: t("mic.toneOk", { now }) });
      }
    }
  }

  return (
    <Dialog open={open} onClose={step === "intro" || step === "result" ? onClose : undefined} fullWidth maxWidth="sm">
      <DialogTitle>{t("mic.title")}</DialogTitle>
      <DialogContent>
        <Stack spacing={2}>
          {step === "intro" && <Typography>{t("mic.intro")}</Typography>}
          {step === "silence" && (
            <>
              <Typography variant="h6">{t("mic.silence")}</Typography>
              <LevelMeter level={level} />
            </>
          )}
          {step === "speech" && (
            <>
              <Typography variant="h6">{t("mic.speech")}</Typography>
              <Typography variant="h5" sx={{ fontWeight: 600 }}>
                {sentence}
              </Typography>
              <LevelMeter level={level} peak={peak} />
            </>
          )}
          {step === "result" && result && (
            <>
              {advice.map((a, i) => (
                <Alert key={i} severity={a.severity} variant="outlined">
                  {a.text}
                </Alert>
              ))}
              <Typography variant="caption" color="text.secondary">
                {t("mic.numbers", { noise: result.noiseDb.toFixed(0), speech: result.speechDb.toFixed(0), snr: result.snr.toFixed(0) })}
              </Typography>
            </>
          )}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={step === "silence" || step === "speech"}>
          {t("mic.close")}
        </Button>
        {(step === "intro" || step === "result") && (
          <Button variant="contained" startIcon={<MicIcon />} onClick={run}>
            {step === "intro" ? t("mic.start") : t("mic.again")}
          </Button>
        )}
      </DialogActions>
    </Dialog>
  );
}
