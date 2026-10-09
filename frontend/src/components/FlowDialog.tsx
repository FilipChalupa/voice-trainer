import { useCallback, useEffect, useRef, useState } from "react";
import { Alert, Box, Button, Chip, Dialog, DialogContent, IconButton, Slider, Stack, Tooltip, Typography } from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";
import PauseIcon from "@mui/icons-material/Pause";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import ReplayIcon from "@mui/icons-material/Replay";
import SkipNextIcon from "@mui/icons-material/SkipNext";
import { api, ApiError, type Prompt, type Recording } from "../api";
import { errorText, useI18n } from "../i18n";
import { flushTakes, uploadKept, wasKept } from "../lib/pendingTakes";
import { Recorder } from "../lib/recorder";
import { useScreenAwake } from "../lib/wakeLock";
import { LevelMeter } from "./LevelMeter";

type Props = { open: boolean; voiceId: string; recorder: Recorder; deviceId: string; agc: boolean; maxSeconds: number; onClose: (summary: Summary | null) => void; onError: (message: string) => void };
export type Summary = { taken: number; seconds: number; mismatched: number; pending: number };
type Taken = { prompt: Prompt; rec: Recording };
type Phase = "countdown" | "listening" | "paused" | "finished";

const beep = (() => {
  let ctx: AudioContext | null = null;
  return (ok: boolean) => {
    try {
      ctx = ctx ?? new AudioContext();
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.frequency.value = ok ? 880 : 330;
      gain.gain.value = 0.05;
      osc.connect(gain).connect(ctx.destination);
      osc.start();
      osc.stop(ctx.currentTime + (ok ? 0.08 : 0.25));
    } catch {
      /* no audio output */
    }
  };
})();

/** Reading in one go: the microphone stays open, every spoken stretch becomes the take of the sentence on
 *  screen and the text scrolls on. Whisper checks each take in the background. */
export function FlowDialog({ open, voiceId, recorder, deviceId, agc, maxSeconds, onClose, onError }: Props) {
  const { t } = useI18n();
  const [queue, setQueue] = useState<Prompt[]>([]);
  const [taken, setTaken] = useState<Taken[]>([]);
  const [phase, setPhase] = useState<Phase>("countdown");
  const [count, setCount] = useState(3);
  const [level, setLevel] = useState({ rms: 0, peak: 0, noise: 0, speaking: false });
  const [snr, setSnr] = useState<number | null>(null);
  const [uploading, setUploading] = useState(false);
  const [verifyOn, setVerifyOn] = useState(true);
  const verifyRef = useRef(true); // read inside the capture callback, which outlives state changes
  verifyRef.current = verifyOn;
  const [silenceMs, setSilenceMs] = useState(() => {
    try {
      return Number(localStorage.getItem("voice-trainer.flow.silence") ?? 700) || 700;
    } catch {
      return 700;
    }
  });
  const queueRef = useRef<Prompt[]>([]);
  const phaseRef = useRef<Phase>("countdown");
  const stopRef = useRef<(() => void) | null>(null);
  const uploadsRef = useRef(Promise.resolve());

  const current = queue[0];
  phaseRef.current = phase;
  // nobody touches the screen while reading, so a phone would lock in the middle of a paragraph
  useScreenAwake(open && phase !== "paused");

  const refill = useCallback(async () => {
    const res = await api.prompts(12);
    // a sentence goes into the queue once, whatever the server sends (a sentence queued again at the front
    // used to come back twice, as its custom copy and from the corpus)
    const seen = new Set(queueRef.current.map((q) => q.id));
    const fresh = res.items.filter((p) => !seen.has(p.id) && Boolean(seen.add(p.id)));
    queueRef.current = [...queueRef.current, ...fresh];
    setQueue([...queueRef.current]);
  }, []);

  // one upload after the other, in the order the segments arrived
  const handleSegment = useCallback(
    (segment: { wav: Blob; seconds: number; snrDb: number }) => {
      if (phaseRef.current !== "listening") return;
      const prompt = queueRef.current[0];
      if (!prompt) return;
      queueRef.current = queueRef.current.slice(1);
      setQueue([...queueRef.current]);
      setSnr(segment.snrDb);
      uploadsRef.current = uploadsRef.current.then(async () => {
        setUploading(true);
        try {
          const rec = await uploadKept(voiceId, segment.wav, prompt.text, prompt.id);
          setTaken((list) => [...list, { prompt, rec }]);
          beep(true);
          if (verifyRef.current) api.verifyRecording(rec.id).catch(() => undefined);
        } catch (e) {
          // a stretch without speech (the server's own check) is just dropped; anything else is reported
          const silent = e instanceof ApiError && e.code === "silent_recording";
          if (wasKept(e)) {
            // the server is out of reach: the take waits in the browser, reading stops until it is back
            beep(false);
            stopRef.current?.();
            stopRef.current = null;
            setPhase("paused");
            onError(t("pending.offline"));
          } else if (!silent) {
            beep(false);
            onError(errorText(t, e));
          }
          queueRef.current = [prompt, ...queueRef.current]; // the sentence comes back for another go
          setQueue([...queueRef.current]);
        } finally {
          setUploading(false);
        }
        if (queueRef.current.length < 6) await refill().catch(() => undefined);
      });
    },
    [onError, refill, t, voiceId],
  );

  const start = useCallback(async () => {
    try {
      await recorder.init(deviceId || undefined, agc);
      stopRef.current = await recorder.flow(handleSegment, setLevel, { silenceMs, minSeconds: 0.4, maxSeconds: Math.max(maxSeconds, 28), prerollMs: 400 });
    } catch (e) {
      onError(errorText(t, e));
      setPhase("paused");
    }
  }, [agc, deviceId, handleSegment, maxSeconds, onError, recorder, silenceMs, t]);

  // a changed pause length takes effect at once: the capture restarts with the new setting
  const changeSilence = (value: number) => {
    setSilenceMs(value);
    try {
      localStorage.setItem("voice-trainer.flow.silence", String(value));
    } catch {
      /* private mode */
    }
  };
  useEffect(() => {
    if (phase !== "listening") return;
    stopCapture();
    start().then(() => setPhase("listening"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [silenceMs]);

  // leaving the page while the microphone runs or a take is still uploading would lose it
  useEffect(() => {
    if (!open) return;
    const guard = (e: BeforeUnloadEvent) => {
      if (phase === "listening" || uploading) {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", guard);
    return () => window.removeEventListener("beforeunload", guard);
  }, [open, phase, uploading]);

  const stopCapture = useCallback(() => {
    stopRef.current?.();
    stopRef.current = null;
  }, []);

  useEffect(() => {
    if (!open) return;
    queueRef.current = [];
    setQueue([]);
    setTaken([]);
    setSnr(null);
    setPhase("countdown");
    setCount(3);
    refill().catch((e) => onError(errorText(t, e)));
    return () => stopCapture();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  useEffect(() => {
    if (!open || phase !== "countdown") return;
    if (!stopRef.current) start(); // the microphone opens with the countdown: noise floor and pre-roll are ready before the first word
    if (count <= 0) {
      setPhase("listening");
      return;
    }
    const timer = setTimeout(() => setCount((c) => c - 1), 800);
    return () => clearTimeout(timer);
  }, [open, phase, count, start]);

  const pause = () => {
    stopCapture();
    setPhase("paused");
  };
  const resume = () => {
    // takes that waited for the server go up first; their sentences then leave the queue
    uploadsRef.current = uploadsRef.current.then(async () => {
      const res = await flushTakes(voiceId).catch(() => null);
      if (!res?.uploaded.length) return;
      const done = new Set(res.uploaded.map((r) => r.prompt_id));
      const prompts = queueRef.current.filter((p) => done.has(p.id));
      queueRef.current = queueRef.current.filter((p) => !done.has(p.id));
      setQueue([...queueRef.current]);
      setTaken((list) => [...list, ...res.uploaded.map((rec) => ({ prompt: prompts.find((p) => p.id === rec.prompt_id) ?? { id: rec.prompt_id ?? rec.id, text: rec.text }, rec }) as Taken)]);
    });
    setCount(2);
    setPhase("countdown");
  };
  const skip = () => {
    const prompt = queueRef.current[0];
    if (!prompt) return;
    api.skipPrompt(prompt.id).catch(() => undefined);
    queueRef.current = queueRef.current.slice(1);
    setQueue([...queueRef.current]);
    if (queueRef.current.length < 6) refill().catch(() => undefined);
  };
  const redoLast = async () => {
    const last = taken[taken.length - 1];
    if (!last) return;
    try {
      await api.deleteRecording(last.rec.id);
      setTaken((list) => list.slice(0, -1));
      queueRef.current = [last.prompt, ...queueRef.current];
      setQueue([...queueRef.current]);
    } catch (e) {
      onError(errorText(t, e));
    }
  };
  const finish = async () => {
    stopCapture();
    setPhase("finished");
    await uploadsRef.current;
    // give the verifier a moment, then read the verdicts
    let mismatched = 0;
    let pending = 0;
    try {
      const items = (await api.recordings({ brief: true, ids: taken.map((tk) => tk.rec.id) })).items;
      for (const tk of taken) {
        const rec = items.find((r) => r.id === tk.rec.id);
        if (rec?.verify?.status === "mismatch") mismatched += 1;
        else if (rec?.verify?.status === "pending") pending += 1;
      }
    } catch {
      /* the summary just lacks the verdicts */
    }
    onClose({ taken: taken.length, seconds: taken.reduce((a, tk) => a + tk.rec.duration, 0), mismatched, pending });
  };

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey) return; // Ctrl+R reloads the page, Ctrl+Space and the like belong to the browser
      if (e.code === "Space") {
        e.preventDefault();
        if (phase === "listening") pause();
        else if (phase === "paused") resume();
      } else if (e.key === "Escape") {
        e.preventDefault();
        finish();
      } else if (e.key.toLowerCase() === "r") {
        e.preventDefault();
        redoLast();
      } else if (e.key === "ArrowRight") {
        e.preventDefault();
        skip();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, phase, taken, queue]);

  const previous = taken[taken.length - 1]?.prompt.text;
  const lowSnr = snr !== null && snr < 20;
  const lastVerdict = taken.slice(-3).map((tk) => tk.rec.id);

  return (
    <Dialog open={open} fullScreen onClose={() => finish()}>
      <DialogContent sx={{ display: "flex", flexDirection: "column", bgcolor: "background.default", p: { xs: 2, sm: 4 } }}>
        <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 2 }}>
          <Chip
            color={phase === "listening" ? (level.speaking ? "success" : "info") : "default"}
            label={phase === "countdown" ? t("flow.countdown", { n: count }) : phase === "listening" ? (level.speaking ? t("flow.hearing") : t("flow.listening")) : phase === "paused" ? t("flow.paused") : t("flow.finishing")}
          />
          <Typography variant="body2" color="text.secondary">
            {t("flow.taken", { n: taken.length })}
            {uploading ? " …" : ""}
          </Typography>
          {snr !== null && (
            <Tooltip title={t("flow.snrHint")}>
              <Chip size="small" variant="outlined" color={lowSnr ? "warning" : "default"} label={t("flow.snr", { db: snr.toFixed(0) })} />
            </Tooltip>
          )}
          <Box sx={{ flex: 1 }} />
          <Tooltip title={t("flow.verify")}>
            <Chip size="small" variant={verifyOn ? "filled" : "outlined"} color={verifyOn ? "primary" : "default"} label={t("flow.verifyShort")} onClick={() => setVerifyOn((v) => !v)} />
          </Tooltip>
          <IconButton onClick={finish} aria-label="close">
            <CloseIcon />
          </IconButton>
        </Stack>

        <Box sx={{ flex: 1, display: "flex", flexDirection: "column", justifyContent: "center", maxWidth: 1100, width: "100%", mx: "auto" }}>
          <Typography variant="h6" color="text.disabled" sx={{ minHeight: 40, opacity: 0.7 }} noWrap>
            {previous ?? ""}
          </Typography>
          <Typography variant="h3" component="p" sx={{ fontWeight: 600, lineHeight: 1.25, my: 2, fontSize: { xs: 28, sm: 40, md: 48 }, transition: "opacity 150ms" }}>
            {current ? current.text : t("flow.empty")}
          </Typography>
          {current?.read_as && (
            <Typography variant="h6" color="primary" sx={{ mb: 1 }}>
              {t("studio.readAs", { text: current.read_as })}
            </Typography>
          )}
          {queue.slice(1, 4).map((p, i) => (
            <Typography key={p.id} variant="h5" color="text.secondary" sx={{ opacity: 0.75 - i * 0.2, fontSize: { xs: 18, sm: 22, md: 26 }, lineHeight: 1.3, mt: 1 }}>
              {p.text}
            </Typography>
          ))}
        </Box>

        {lowSnr && (
          <Alert severity="warning" sx={{ mb: 2 }}>
            {t("flow.lowSnr", { db: snr!.toFixed(0) })}
          </Alert>
        )}

        <Box sx={{ maxWidth: 1100, width: "100%", mx: "auto" }}>
          <Stack direction="row" spacing={2} alignItems="center" sx={{ mb: 1 }}>
            <Typography variant="caption" color="text.secondary" sx={{ whiteSpace: "nowrap" }}>
              {t("flow.pauseLength", { s: (silenceMs / 1000).toFixed(1) })}
            </Typography>
            <Slider size="small" min={500} max={1500} step={100} value={silenceMs} onChange={(_, v) => setSilenceMs(v as number)} onChangeCommitted={(_, v) => changeSilence(v as number)} sx={{ maxWidth: 260 }} />
            <Typography variant="caption" color="text.secondary">
              {t("flow.pauseHint")}
            </Typography>
          </Stack>
          <LevelMeter level={Math.min(1, level.rms * 6)} peak={level.peak} />
          <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap sx={{ mt: 2 }}>
            {phase === "listening" ? (
              <Button variant="outlined" startIcon={<PauseIcon />} onClick={pause}>
                {t("flow.pause")}
              </Button>
            ) : (
              <Button variant="contained" startIcon={<PlayArrowIcon />} onClick={resume} disabled={phase === "countdown" || phase === "finished"}>
                {t("flow.resume")}
              </Button>
            )}
            <Button startIcon={<ReplayIcon />} onClick={redoLast} disabled={!taken.length}>
              {t("flow.redo")}
            </Button>
            <Button startIcon={<SkipNextIcon />} onClick={skip} disabled={!current}>
              {t("flow.skip")}
            </Button>
            <Box sx={{ flex: 1 }} />
            <Typography variant="caption" color="text.secondary">
              {t("flow.keys")}
            </Typography>
          </Stack>
          {lastVerdict.length > 0 && <VerdictRow ids={lastVerdict} />}
        </Box>
      </DialogContent>
    </Dialog>
  );
}

/** Whisper's verdicts for the last few takes, polled while they are pending. */
function VerdictRow({ ids }: { ids: string[] }) {
  const { t } = useI18n();
  const [items, setItems] = useState<Recording[]>([]);
  useEffect(() => {
    let alive = true;
    const poll = () => api.recordings({ brief: true, ids }).then((r) => alive && setItems(r.items)).catch(() => undefined);
    poll();
    const timer = setInterval(poll, 2000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [ids.join(",")]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <Stack direction="row" spacing={1} sx={{ mt: 1 }} flexWrap="wrap" useFlexGap>
      {ids.map((id) => {
        const rec = items.find((r) => r.id === id);
        const v = rec?.verify;
        const color = v?.status === "ok" ? "success" : v?.status === "mismatch" ? "warning" : "default";
        const label = v?.status === "ok" ? t("flow.vOk") : v?.status === "mismatch" ? t("flow.vMismatch") : v?.status === "error" ? t("flow.vError") : v ? t("flow.vPending") : "";
        return (
          <Tooltip key={id} title={v?.transcript ? t("flow.heard", { text: v.transcript }) : ""}>
            <Chip size="small" color={color} variant="outlined" label={`${rec?.text.slice(0, 32) ?? "…"}… ${label}`} />
          </Tooltip>
        );
      })}
    </Stack>
  );
}
