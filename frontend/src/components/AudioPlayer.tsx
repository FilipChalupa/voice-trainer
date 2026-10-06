import { useEffect, useMemo, useRef, useState } from "react";
import { Box, IconButton, Stack, Typography, useTheme } from "@mui/material";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import PauseIcon from "@mui/icons-material/Pause";
import { loadPeaks, onExclusiveChange, playExclusive, formatTime } from "../lib/audio";
import { Scrub } from "./Scrub";

type Props = {
  src: string;
  /** Waveform peaks; decoded from the file when not given. */
  peaks?: number[];
  label?: React.ReactNode;
  secondary?: React.ReactNode;
  autoPlay?: boolean;
  /** Smaller button and waveform for lists. */
  dense?: boolean;
  color?: string;
  onEnded?: () => void;
};

/** The app's own player: a round play button, a clickable waveform that fills as it plays, and the time. */
export function AudioPlayer({ src, peaks: given, label, secondary, autoPlay, dense, color, onEnded }: Props) {
  const theme = useTheme();
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [peaks, setPeaks] = useState<number[] | null>(given ?? null);
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const bar = color ?? theme.palette.primary.main;
  const height = dense ? 28 : 40;

  const audio = useMemo(() => {
    const a = new Audio(src);
    a.preload = "metadata";
    return a;
  }, [src]);

  useEffect(() => {
    audioRef.current = audio;
    const onTime = () => setTime(audio.currentTime);
    const onMeta = () => setDuration(audio.duration);
    const onPlay = () => setPlaying(true);
    const onPause = () => setPlaying(false);
    const onEnd = () => {
      setPlaying(false);
      setTime(0);
      onEnded?.();
    };
    audio.addEventListener("timeupdate", onTime);
    audio.addEventListener("loadedmetadata", onMeta);
    audio.addEventListener("durationchange", onMeta);
    audio.addEventListener("play", onPlay);
    audio.addEventListener("pause", onPause);
    audio.addEventListener("ended", onEnd);
    const off = onExclusiveChange((other) => other !== audio && setPlaying(false));
    if (autoPlay) void playExclusive(audio);
    return () => {
      off();
      audio.pause();
      audio.removeEventListener("timeupdate", onTime);
      audio.removeEventListener("loadedmetadata", onMeta);
      audio.removeEventListener("durationchange", onMeta);
      audio.removeEventListener("play", onPlay);
      audio.removeEventListener("pause", onPause);
      audio.removeEventListener("ended", onEnd);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [audio]);

  useEffect(() => {
    if (given) {
      setPeaks(given);
      return;
    }
    let alive = true;
    loadPeaks(src)
      .then((p) => alive && setPeaks(p))
      .catch(() => alive && setPeaks([]));
    return () => {
      alive = false;
    };
  }, [src, given]);

  const toggle = () => {
    if (playing) audio.pause();
    else void playExclusive(audio);
  };

  const seek = (ratio: number) => {
    const jump = () => {
      if (!audio.duration || !isFinite(audio.duration)) return;
      audio.currentTime = ratio * audio.duration;
      setTime(audio.currentTime);
    };
    if (audio.duration && isFinite(audio.duration)) jump();
    else audio.addEventListener("loadedmetadata", jump, { once: true });
    if (!playing) void playExclusive(audio);
  };

  const progress = duration ? time / duration : 0;
  const shown = peaks && peaks.length ? peaks : Array.from({ length: 80 }, () => 0.15);
  const max = Math.max(0.05, ...shown);

  return (
    <Box sx={{ width: "100%", minWidth: 0 }}>
      {(label || secondary) && (
        <Stack direction="row" spacing={1} alignItems="baseline" sx={{ mb: 0.25, minWidth: 0 }}>
          {label && (
            <Typography variant={dense ? "body2" : "body1"} noWrap sx={{ flex: 1, minWidth: 0 }}>
              {label}
            </Typography>
          )}
          {secondary}
        </Stack>
      )}
      {/* the button sits on the waveform row, not on the text above it */}
      <Stack direction="row" spacing={dense ? 1 : 1.5} alignItems="center">
        <IconButton
          onClick={toggle}
          size={dense ? "small" : "medium"}
          sx={{ bgcolor: "primary.main", color: "primary.contrastText", "&:hover": { bgcolor: "primary.dark" }, flexShrink: 0 }}
          aria-label={playing ? "pause" : "play"}
        >
          {playing ? <PauseIcon fontSize={dense ? "small" : "medium"} /> : <PlayArrowIcon fontSize={dense ? "small" : "medium"} />}
        </IconButton>
        <Scrub duration={duration} onSeek={seek} ariaValueNow={Math.round(progress * 100)} sx={{ flex: 1, minWidth: 0, display: "flex", alignItems: "center", gap: "2px", height, opacity: peaks ? 1 : 0.4, transition: "opacity 200ms" }}>
          {shown.map((p, i) => {
            const played = i / shown.length <= progress && (playing || time > 0);
            return <Box key={i} sx={{ flex: 1, height: `${Math.max(8, (p / max) * 100)}%`, bgcolor: bar, borderRadius: 1, opacity: played ? 1 : 0.3, transition: "opacity 80ms" }} />;
          })}
        </Scrub>
        <Typography variant="caption" color="text.secondary" sx={{ minWidth: dense ? 34 : 68, textAlign: "right", fontVariantNumeric: "tabular-nums" }}>
          {dense ? formatTime(duration) : `${formatTime(time)} / ${formatTime(duration)}`}
        </Typography>
      </Stack>
    </Box>
  );
}
