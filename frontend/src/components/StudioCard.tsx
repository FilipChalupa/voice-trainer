import { useCallback, useEffect, useRef, useState } from "react";
import { Alert, Box, Button, Card, CardContent, CardHeader, Chip, CircularProgress, Dialog, DialogActions, DialogContent, DialogTitle, FormControlLabel, IconButton, LinearProgress, ListItemIcon, ListItemText, Menu, MenuItem, Snackbar, Stack, Switch, TextField, Tooltip, Typography, useTheme } from "@mui/material";
import MicIcon from "@mui/icons-material/Mic";
import StopIcon from "@mui/icons-material/Stop";
import GraphicEqIcon from "@mui/icons-material/GraphicEq";
import SkipNextIcon from "@mui/icons-material/SkipNext";
import ReplayIcon from "@mui/icons-material/Replay";
import PlaylistAddIcon from "@mui/icons-material/PlaylistAdd";
import FactCheckIcon from "@mui/icons-material/FactCheck";
import SettingsVoiceIcon from "@mui/icons-material/SettingsVoice";
import PhoneIphoneIcon from "@mui/icons-material/PhoneIphone";
import MoreHorizIcon from "@mui/icons-material/MoreHoriz";
import { api, type Prompt, type Prompts, type Recording, type VoiceSettings } from "../api";
import { errorText, useI18n } from "../i18n";
import { Recorder, waveformPeaks } from "../lib/recorder";
import { discardTakes, flushTakes, uploadKept, waitingTakes, wasKept } from "../lib/pendingTakes";
import { useScreenAwake } from "../lib/wakeLock";
import { onExclusiveChange, playExclusive } from "../lib/audio";
import { RecordingList, Waveform } from "./RecordingList";
import { AudioPlayer } from "./AudioPlayer";
import { ReviewDialog } from "./ReviewDialog";
import { MicCheckDialog } from "./MicCheckDialog";
import { PhoneDialog } from "./PhoneDialog";
import { LevelMeter } from "./LevelMeter";
import { SessionStats } from "./SessionStats";
import { useReview } from "../lib/useReview";
import { ParagraphsDialog } from "./ParagraphsDialog";
import { FlowDialog, type Summary } from "./FlowDialog";
import RecordVoiceOverIcon from "@mui/icons-material/RecordVoiceOver";
import MenuBookIcon from "@mui/icons-material/MenuBook";

/** An alert with buttons on its right: the buttons sit in the middle of the text, not at its top. */
const ACTION_ALERT = { alignItems: "center", "& .MuiAlert-action": { pt: 0, alignItems: "center" } } as const;

const PREF_PREFIX = "voice-trainer.studio.";
function readPref(key: string): string | null {
  try {
    return localStorage.getItem(PREF_PREFIX + key);
  } catch {
    return null;
  }
}
function writePref(key: string, value: string): void {
  try {
    localStorage.setItem(PREF_PREFIX + key, value);
  } catch {
    /* private mode */
  }
}

type Props = {
  voice: VoiceSettings;
  minutes: { min: number; recommended: number; target: number };
  disabled: boolean;
  onChanged: () => void;
  onError: (message: string) => void;
};

type Phase = "idle" | "prepare" | "recording" | "uploading";

/** Prompt-by-prompt recording: shows a sentence, records until the reader stops, stores it with its transcript. */
export function StudioCard({ voice, minutes, disabled, onChanged, onError }: Props) {
  const { t } = useI18n();
  const theme = useTheme();
  const [prompts, setPrompts] = useState<Prompts | null>(null);
  const [recordings, setRecordings] = useState<Recording[]>([]);
  const [totalMinutes, setTotalMinutes] = useState(0);
  const [text, setText] = useState("");
  const [current, setCurrent] = useState<Prompt | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [elapsed, setElapsed] = useState(0);
  const [level, setLevel] = useState(0);
  const [peak, setPeak] = useState(0);
  const [lastPeaks, setLastPeaks] = useState<number[] | null>(null);
  const [justSaved, setJustSaved] = useState<Recording | null>(null);
  // per-browser preferences that survive a reload
  const [autoPlay, setAutoPlay] = useState(() => readPref("autoplay") === "1");
  const [devices, setDevices] = useState<{ deviceId: string; label: string }[]>([]);
  const [deviceId, setDeviceId] = useState(() => readPref("mic") ?? "");
  const [agc, setAgc] = useState(() => readPref("agc") === "1");
  const [playing, setPlaying] = useState<{ id: string; progress: number } | null>(null);
  const [undo, setUndo] = useState<string | null>(null);
  const [customOpen, setCustomOpen] = useState(false);
  const [reviewOpen, setReviewOpen] = useState(false);
  const [micCheckOpen, setMicCheckOpen] = useState(false);
  // a new session (no take in the last two hours) suggests the microphone test first, once per browser tab
  const [micChecked, setMicChecked] = useState(() => {
    try {
      return sessionStorage.getItem("voice-trainer.mic-checked") === "1";
    } catch {
      return false;
    }
  });
  useEffect(() => {
    try {
      if (micChecked) sessionStorage.setItem("voice-trainer.mic-checked", "1");
    } catch {
      /* private mode */
    }
  }, [micChecked]);
  const [phoneOpen, setPhoneOpen] = useState(false);
  const [moreAnchor, setMoreAnchor] = useState<HTMLElement | null>(null);
  const [paragraphsOpen, setParagraphsOpen] = useState(false);
  const [flowOpen, setFlowOpen] = useState(false);
  const [customText, setCustomText] = useState("");
  const [info, setInfo] = useState<string | null>(null);

  const recorderRef = useRef(new Recorder());
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const stopRef = useRef<(() => void) | null>(null);
  const busyRef = useRef(false);

  useEffect(() => writePref("autoplay", autoPlay ? "1" : "0"), [autoPlay]);
  useEffect(() => writePref("mic", deviceId), [deviceId]);
  useEffect(() => writePref("agc", agc ? "1" : "0"), [agc]);
  // a remembered microphone that is no longer plugged in falls back to the default
  useEffect(() => {
    if (deviceId && devices.length && !devices.some((d) => d.deviceId === deviceId)) setDeviceId("");
  }, [devices, deviceId]);

  // takes an earlier upload could not deliver (connection lost, server restarted, tab closed) wait in the browser
  const [waiting, setWaiting] = useState(0);
  const [flushing, setFlushing] = useState(false);
  const loadWaiting = useCallback(() => {
    waitingTakes(voice.id)
      .then((list) => setWaiting(list.length))
      .catch(() => undefined);
  }, [voice.id]);
  useEffect(loadWaiting, [loadWaiting]);

  const refresh = useCallback(async () => {
    try {
      const [p, r] = await Promise.all([api.prompts(4), api.recordings()]);
      setPrompts(p);
      setRecordings(r.items);
      setTotalMinutes(r.minutes);
      const next = p.items[0] ?? null;
      setCurrent((prev) => {
        if (prev?.id !== next?.id) setText(next?.text ?? "");
        return next;
      });
    } catch (e) {
      onError(errorText(t, e));
    }
  }, [onError, t]);

  useEffect(() => {
    refresh();
    Recorder.listDevices().then(setDevices).catch(() => undefined);
    const recorder = recorderRef.current;
    return () => recorder.close();
  }, [refresh, voice.id]);

  // while the downloaded corpus is being prepared, poll until it replaces the built-in set
  useEffect(() => {
    if (prompts?.source !== "builtin" || prompts.preparing?.state === "error") return;
    const timer = setInterval(refresh, 4000);
    return () => clearInterval(timer);
  }, [prompts?.source, prompts?.preparing?.state, refresh]);

  /** A click on a waveform: moves inside the take that plays, or starts another one from that point. */
  const seekTo = (rec: Recording, ratio: number) => {
    const audio = audioRef.current;
    if (playing?.id === rec.id && audio && audio.duration) {
      audio.currentTime = ratio * audio.duration;
      setPlaying({ id: rec.id, progress: ratio });
    } else void playOne(rec, ratio);
  };

  const stopPlayback = useCallback(() => {
    if (audioRef.current) {
      audioRef.current.onended = null;
      audioRef.current.ontimeupdate = null;
      audioRef.current.pause();
      audioRef.current = null;
    }
    setPlaying(null);
  }, []);

  // another player on the page took over: show the list as stopped
  useEffect(() => onExclusiveChange((other) => other !== audioRef.current && audioRef.current && stopPlayback()), [stopPlayback]);

  const playOne = useCallback(
    (rec: Recording, from = 0) =>
      new Promise<void>((resolve) => {
        stopPlayback();
        const audio = new Audio(rec.url);
        audioRef.current = audio;
        setPlaying({ id: rec.id, progress: from });
        if (from > 0) audio.onloadedmetadata = () => (audio.currentTime = from * audio.duration);
        audio.ontimeupdate = () => setPlaying({ id: rec.id, progress: audio.duration ? audio.currentTime / audio.duration : 0 });
        audio.onended = () => {
          setPlaying(null);
          resolve();
        };
        audio.onerror = () => {
          setPlaying(null);
          resolve();
        };
        playExclusive(audio).then(() => undefined, () => resolve());
      }),
    [stopPlayback],
  );

  const record = useCallback(async () => {
    if (phase === "recording") {
      stopRef.current?.();
      return;
    }
    if (busyRef.current || disabled || text.trim().length < 3) return;
    busyRef.current = true;
    stopPlayback();
    setLastPeaks(null);
    setJustSaved(null);
    try {
      setPhase("prepare");
      await recorderRef.current.init(deviceId || undefined, agc);
      if (devices.length === 0) Recorder.listDevices().then(setDevices).catch(() => undefined);
      await new Promise((r) => setTimeout(r, 250));
      setPhase("recording");
      setElapsed(0);
      // sentences contain pauses at commas, so wait a little longer for silence than for a single word
      const { wav, samples } = await recorderRef.current.record(
        voice.max_record_seconds,
        ({ rms, peak: p, elapsed: e }) => {
          setLevel(Math.min(1, rms * 6));
          setPeak(p);
          setElapsed(e);
        },
        { silenceMs: 1100, minSeconds: 1.2, onStart: (stop) => (stopRef.current = stop) },
      );
      stopRef.current = null;
      setLevel(0);
      setPeak(0);
      setLastPeaks(waveformPeaks(samples));
      setPhase("uploading");
      const saved = await uploadKept(voice.id, wav, text.trim(), current?.id ?? null);
      setJustSaved(saved);
      // Whisper checks the take against its text in the background (refused while training runs: then no check)
      api
        .verifyRecording(saved.id)
        .then(() => setTimeout(() => refresh().catch(() => undefined), 4000))
        .catch(() => undefined);
      await refresh();
      onChanged();
      setPhase("idle");
      if (autoPlay) await playOne(saved);
    } catch (e) {
      onError(wasKept(e) ? t("pending.offline") : errorText(t, e));
      loadWaiting();
    } finally {
      setLevel(0);
      setPeak(0);
      setPhase("idle");
      busyRef.current = false;
    }
  }, [agc, autoPlay, current?.id, deviceId, devices.length, disabled, loadWaiting, onChanged, onError, phase, playOne, refresh, stopPlayback, t, text, voice.id, voice.max_record_seconds]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.tagName === "SELECT" || target.isContentEditable)) return;
      if (e.code === "Space") {
        e.preventDefault();
        record();
      } else if (e.key === "Escape") {
        stopRef.current?.();
        stopPlayback();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [record, stopPlayback]);

  const skip = async () => {
    if (!current) return;
    try {
      await api.skipPrompt(current.id);
      await refresh();
    } catch (e) {
      onError(errorText(t, e));
    }
  };

  const remove = async (rec: Recording) => {
    try {
      if (playing?.id === rec.id) stopPlayback();
      await api.deleteRecording(rec.id);
      setUndo(rec.id);
      await refresh();
      onChanged();
    } catch (e) {
      onError(errorText(t, e));
    }
  };

  const redoLast = async () => {
    const last = recordings[recordings.length - 1];
    if (last) await remove(last);
  };

  const restore = async () => {
    if (!undo) return;
    try {
      await api.restoreRecording(undo);
      setUndo(null);
      await refresh();
      onChanged();
    } catch (e) {
      onError(errorText(t, e));
    }
  };

  const edit = async (rec: Recording, newText: string) => {
    try {
      await api.updateRecording(rec.id, newText);
      await refresh();
    } catch (e) {
      onError(errorText(t, e));
    }
  };

  const review = useReview(recordings, refresh, onChanged, onError);
  const lastTake = recordings.length ? new Date(recordings[recordings.length - 1].created).getTime() : 0;
  const sessionStart = prompts !== null && Date.now() - lastTake > 2 * 60 * 60 * 1000;
  const [summaryMismatched, setSummaryMismatched] = useState(0);

  // closing the tab in the middle of a take would lose it without a word
  useEffect(() => {
    const guard = (e: BeforeUnloadEvent) => {
      if (phase === "recording" || phase === "uploading") {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", guard);
    return () => window.removeEventListener("beforeunload", guard);
  }, [phase]);

  const addCustom = async () => {
    try {
      const res = await api.addCustomPrompts(customText);
      setInfo(t("studio.customAdded", { n: res.added }));
      setCustomText("");
      setCustomOpen(false);
      await refresh();
    } catch (e) {
      onError(errorText(t, e));
    }
  };

  const uploadWaiting = async () => {
    setFlushing(true);
    try {
      const res = await flushTakes(voice.id);
      if (res.left > 0) onError(t("pending.stillOffline", { n: res.left }));
      else setInfo(t("pending.uploaded", { n: res.uploaded.length, dropped: res.dropped }));
      for (const rec of res.uploaded) api.verifyRecording(rec.id).catch(() => undefined);
      await refresh();
      onChanged();
    } finally {
      setFlushing(false);
      loadWaiting();
    }
  };
  const discardWaiting = async () => {
    await discardTakes(voice.id);
    loadWaiting();
  };

  const progress = Math.min(100, (totalMinutes / minutes.target) * 100);
  const busy = phase !== "idle";
  useScreenAwake(busy);

  return (
    <Card>
      <CardHeader
        avatar={<GraphicEqIcon color="primary" />}
        title={t("studio.title")}
        subheader={t("studio.subtitle")}
        action={<Chip color={totalMinutes >= minutes.recommended ? "success" : totalMinutes >= minutes.min ? "primary" : "default"} variant={totalMinutes >= minutes.min ? "filled" : "outlined"} label={t("studio.progress", { minutes: totalMinutes.toFixed(1), target: minutes.target })} />}
      />
      <CardContent>
        <Stack spacing={2}>
          {waiting > 0 && !flowOpen && (
            <Alert
              severity="warning"
              sx={ACTION_ALERT}
              action={
                <Stack direction="row" spacing={1} alignItems="center" sx={{ whiteSpace: "nowrap" }}>
                  <Button size="small" variant="contained" color="warning" onClick={uploadWaiting} disabled={flushing || busy}>
                    {t("pending.upload")}
                  </Button>
                  <Button size="small" color="inherit" onClick={discardWaiting} disabled={flushing}>
                    {t("pending.discard")}
                  </Button>
                </Stack>
              }
            >
              {t("pending.waiting", { n: waiting })}
            </Alert>
          )}
          {sessionStart && !micChecked && (
            <Alert
              severity="info"
              variant="outlined"
              sx={ACTION_ALERT}
              action={
                <Stack direction="row" spacing={1} alignItems="center" sx={{ whiteSpace: "nowrap" }}>
                  <Button size="small" variant="contained" startIcon={<SettingsVoiceIcon />} onClick={() => setMicCheckOpen(true)} disabled={disabled || busy}>
                    {t("studio.micCheck")}
                  </Button>
                  <Button size="small" onClick={() => setMicChecked(true)}>
                    {t("studio.sessionSkip")}
                  </Button>
                </Stack>
              }
            >
              {t("studio.sessionStart")}
            </Alert>
          )}
          <Box>
            <Box sx={{ position: "relative" }}>
              <LinearProgress variant="determinate" value={progress} sx={{ height: 10, borderRadius: 5 }} color={totalMinutes >= minutes.recommended ? "success" : "primary"} />
              {[minutes.min, minutes.recommended].map((m) => (
                <Box key={m} sx={{ position: "absolute", top: -2, bottom: -2, left: `${(m / minutes.target) * 100}%`, width: 2, bgcolor: "text.secondary", opacity: 0.6 }} />
              ))}
            </Box>
            <Typography variant="caption" color="text.secondary">
              {t("studio.milestones", minutes)}
            </Typography>
          </Box>

          {prompts?.source === "builtin" && (
            <Alert severity={prompts.preparing?.state === "error" ? "warning" : "info"} variant="outlined">
              {prompts.preparing?.state === "error" ? t("studio.corpusError", { err: prompts.preparing.error ?? "" }) : t("studio.builtin")}
            </Alert>
          )}

          {current ? (
            <Box sx={{ p: 2, border: 1, borderColor: phase === "recording" ? "error.main" : "divider", borderRadius: 2 }}>
              {recordings.length > 0 && (
                <Typography variant="body2" color="text.secondary" noWrap sx={{ mb: 0.5 }}>
                  {t("studio.previous")}: {recordings[recordings.length - 1].text}
                </Typography>
              )}
              <Stack direction="row" justifyContent="space-between" alignItems="center">
                <Typography variant="caption" color="text.secondary">
                  {t("studio.prompt")}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  {prompts ? t("studio.remaining", { n: prompts.remaining }) : ""}
                </Typography>
              </Stack>
              <TextField
                value={text}
                onChange={(e) => setText(e.target.value)}
                multiline
                fullWidth
                variant="standard"
                disabled={disabled}
                InputProps={{ readOnly: busy, disableUnderline: true, sx: { fontSize: { xs: 22, sm: 28 }, lineHeight: 1.3, fontWeight: 500 } }}
              />
              {current.read_as && text.trim() === current.text && (
                <Typography variant="body2" color="primary" sx={{ mt: 0.5 }}>
                  {t("studio.readAs", { text: current.read_as })}
                </Typography>
              )}
              {prompts && prompts.items.length > 1 && (
                <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }} noWrap>
                  {t("studio.next")}: {prompts.items[1].text}
                </Typography>
              )}
            </Box>
          ) : (
            <Alert severity="success">{t("studio.done")}</Alert>
          )}

          <Stack direction={{ xs: "column", sm: "row" }} spacing={3} alignItems="center">
            <Box sx={{ position: "relative", display: "inline-flex" }}>
              <IconButton
                onClick={record}
                disabled={disabled || !current || (busy && phase !== "recording")}
                sx={{
                  width: { xs: 140, sm: 110 },
                  height: { xs: 140, sm: 110 },
                  bgcolor: phase === "recording" ? "error.main" : "primary.main",
                  color: phase === "recording" ? "error.contrastText" : "primary.contrastText",
                  "&:hover": { bgcolor: phase === "recording" ? "error.dark" : "primary.dark" },
                  "&.Mui-disabled": { bgcolor: "action.disabledBackground" },
                  transform: phase === "recording" ? `scale(${1 + level * 0.08})` : "none",
                  transition: "transform 80ms linear",
                }}
              >
                {phase === "uploading" || phase === "prepare" ? <CircularProgress size={36} color="inherit" /> : phase === "recording" ? <StopIcon sx={{ fontSize: 48 }} /> : <MicIcon sx={{ fontSize: 50 }} />}
              </IconButton>
            </Box>
            <Box sx={{ flex: 1, width: "100%" }}>
              <Typography variant="h6">
                {phase === "idle" && t("studio.idle")}
                {phase === "prepare" && t("studio.prepare")}
                {phase === "recording" && t("studio.recording", { s: elapsed.toFixed(1) })}
                {phase === "uploading" && t("studio.uploading")}
              </Typography>
              <Typography variant="body2" color="text.secondary" gutterBottom>
                {t("studio.instructions")}
              </Typography>
              <Box sx={{ mb: 1 }}>
                <LevelMeter level={level} peak={peak} />
              </Box>
              {justSaved ? (
                <AudioPlayer src={justSaved.url} peaks={justSaved.peaks} dense label={t("studio.lastTake")} />
              ) : (
                lastPeaks && <Waveform peaks={lastPeaks} color={theme.palette.primary.main} height={36} />
              )}
            </Box>
          </Stack>

          <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
            <Button startIcon={<SkipNextIcon />} onClick={skip} disabled={disabled || busy || !current}>
              {t("studio.skip")}
            </Button>
            <Button startIcon={<ReplayIcon />} onClick={redoLast} disabled={disabled || busy || recordings.length === 0}>
              {t("studio.redo")}
            </Button>
            <Button variant="outlined" startIcon={<RecordVoiceOverIcon />} onClick={() => setFlowOpen(true)} disabled={disabled || busy || !current}>
              {t("studio.flow")}
            </Button>
            {review.queue.length > 0 && (
              <Button startIcon={<FactCheckIcon />} onClick={() => setReviewOpen(true)} disabled={disabled || busy} color="warning">
                {t("studio.review", { n: review.queue.length })}
              </Button>
            )}
            <Button startIcon={<MoreHorizIcon />} onClick={(e) => setMoreAnchor(e.currentTarget)} disabled={busy}>
              {t("studio.more")}
            </Button>
            <Menu anchorEl={moreAnchor} open={!!moreAnchor} onClose={() => setMoreAnchor(null)}>
              {[
                { icon: <PlaylistAddIcon fontSize="small" />, label: t("studio.custom"), open: () => setCustomOpen(true), disabled: disabled },
                { icon: <MenuBookIcon fontSize="small" />, label: t("studio.paragraphs"), open: () => setParagraphsOpen(true), disabled: disabled },
                { icon: <SettingsVoiceIcon fontSize="small" />, label: t("studio.micCheck"), open: () => setMicCheckOpen(true), disabled: disabled },
                { icon: <PhoneIphoneIcon fontSize="small" />, label: t("studio.phone"), open: () => setPhoneOpen(true), disabled: false },
              ].map((item) => (
                <MenuItem
                  key={item.label}
                  disabled={item.disabled}
                  onClick={() => {
                    setMoreAnchor(null);
                    item.open();
                  }}
                >
                  <ListItemIcon>{item.icon}</ListItemIcon>
                  <ListItemText>{item.label}</ListItemText>
                </MenuItem>
              ))}
            </Menu>
            <FormControlLabel control={<Switch checked={autoPlay} onChange={(e) => setAutoPlay(e.target.checked)} />} label={t("studio.autoplay")} />
            <Tooltip title={t("studio.agcHint")}>
              <FormControlLabel control={<Switch checked={agc} onChange={(e) => setAgc(e.target.checked)} disabled={busy} />} label={t("studio.agc")} />
            </Tooltip>
            <TextField select size="small" label={t("studio.mic")} value={deviceId} onChange={(e) => setDeviceId(e.target.value)} sx={{ minWidth: 200 }} disabled={busy}>
              <MenuItem value="">{t("studio.micDefault")}</MenuItem>
              {devices.map((d) => (
                <MenuItem key={d.deviceId} value={d.deviceId}>
                  {d.label}
                </MenuItem>
              ))}
            </TextField>
          </Stack>

          <Typography variant="subtitle2">{t("rec.count", { n: recordings.length, minutes: totalMinutes.toFixed(1) })}</Typography>
          <SessionStats recordings={recordings} minutes={minutes} totalMinutes={totalMinutes} />
          <RecordingList
            items={recordings}
            disabled={disabled}
            playingId={playing?.id ?? null}
            playingProgress={playing?.progress}
            onTogglePlay={(rec) => (playing?.id === rec.id ? stopPlayback() : playOne(rec))}
            onSeek={seekTo}
            onDelete={remove}
            onRedo={(rec) => {
              if (playing?.id === rec.id) stopPlayback();
              review.redo(rec).then(() => setInfo(t("studio.redoQueued")));
            }}
            onMark={(rec) =>
              api
                .markRedo(rec.id, !rec.redo)
                .then(() => refresh())
                .catch((e) => onError(errorText(t, e)))
            }
            onEdit={edit}
          />
        </Stack>
      </CardContent>

      <PhoneDialog open={phoneOpen} onClose={() => setPhoneOpen(false)} />
      <FlowDialog
        open={flowOpen}
        voiceId={voice.id}
        recorder={recorderRef.current}
        deviceId={deviceId}
        agc={agc}
        maxSeconds={voice.max_record_seconds}
        onClose={async (summary: Summary | null) => {
          setFlowOpen(false);
          loadWaiting();
          await refresh();
          onChanged();
          if (summary && summary.taken > 0) {
            setSummaryMismatched(summary.mismatched + summary.pending);
            setInfo(t("flow.summary", { n: summary.taken, minutes: (summary.seconds / 60).toFixed(1), mismatched: summary.mismatched, pending: summary.pending }));
          }
        }}
        onError={onError}
      />
      <ParagraphsDialog
        open={paragraphsOpen}
        onClose={() => setParagraphsOpen(false)}
        onQueued={async (n) => {
          if (n > 0) setInfo(t("studio.customAdded", { n }));
          await refresh();
        }}
        onError={onError}
      />
      <MicCheckDialog
        open={micCheckOpen}
        recorder={recorderRef.current}
        deviceId={deviceId}
        agc={agc}
        sentence={text || t("mic.fallbackSentence")}
        recordings={recordings}
        onClose={() => setMicCheckOpen(false)}
        onDone={() => setMicChecked(true)}
        onError={onError}
      />
      <ReviewDialog open={reviewOpen} queue={review.queue} onClose={() => setReviewOpen(false)} onApprove={review.approve} onDelete={remove} onRedo={review.redo} />

      <Dialog open={customOpen} onClose={() => setCustomOpen(false)} fullWidth maxWidth="sm">
        <DialogTitle>{t("studio.customTitle")}</DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            {t("studio.customHelp")}
          </Typography>
          <TextField value={customText} onChange={(e) => setCustomText(e.target.value)} multiline minRows={6} fullWidth autoFocus />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCustomOpen(false)}>{t("rec.cancel")}</Button>
          <Button variant="contained" onClick={addCustom} disabled={customText.trim().length < 8}>
            {t("studio.customAdd")}
          </Button>
        </DialogActions>
      </Dialog>
      <Snackbar
        open={!!undo}
        autoHideDuration={8000}
        onClose={() => setUndo(null)}
        message={t("rec.deleted")}
        action={
          <Button color="primary" size="small" onClick={restore}>
            {t("rec.undo")}
          </Button>
        }
      />
      <Snackbar
        open={!!info}
        autoHideDuration={summaryMismatched > 0 ? 12000 : 4000}
        onClose={() => {
          setInfo(null);
          setSummaryMismatched(0);
        }}
        message={info ?? ""}
        action={
          summaryMismatched > 0 ? (
            <Button
              color="warning"
              size="small"
              onClick={() => {
                setInfo(null);
                setSummaryMismatched(0);
                setReviewOpen(true);
              }}
            >
              {t("studio.review", { n: review.queue.length })}
            </Button>
          ) : undefined
        }
      />
    </Card>
  );
}
