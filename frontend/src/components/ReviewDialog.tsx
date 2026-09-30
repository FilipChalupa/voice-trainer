import { useCallback, useEffect, useRef, useState } from "react";
import { Box, Button, Chip, Dialog, DialogActions, DialogContent, DialogTitle, LinearProgress, Stack, TextField, Tooltip, Typography, useTheme } from "@mui/material";
import CheckIcon from "@mui/icons-material/Check";
import ReplayIcon from "@mui/icons-material/Replay";
import DeleteIcon from "@mui/icons-material/Delete";
import MicIcon from "@mui/icons-material/Mic";
import SkipNextIcon from "@mui/icons-material/SkipNext";
import { type Recording } from "../api";
import { useI18n, type TKey } from "../i18n";
import { Waveform } from "./RecordingList";

type Props = {
  open: boolean;
  queue: Recording[];
  onClose: () => void;
  onApprove: (rec: Recording, text: string | null) => Promise<void>;
  onDelete: (rec: Recording) => Promise<void>;
  onRedo: (rec: Recording) => Promise<void>;
};

/** Keyboard-driven pass over the recordings that need a look: warnings and Whisper transcripts.
 *  Each take plays by itself; Enter confirms the text, the other actions have Ctrl shortcuts. */
export function ReviewDialog({ open, queue, onClose, onApprove, onDelete, onRedo }: Props) {
  const { t } = useI18n();
  const theme = useTheme();
  const [index, setIndex] = useState(0);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [total, setTotal] = useState(0);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const fieldRef = useRef<HTMLTextAreaElement | null>(null);

  const rec: Recording | undefined = queue[Math.min(index, queue.length - 1)];

  useEffect(() => {
    if (open) {
      setIndex(0);
      setTotal(queue.length);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const play = useCallback(() => {
    if (!rec) return;
    audioRef.current?.pause();
    const audio = new Audio(rec.url);
    audioRef.current = audio;
    audio.play().catch(() => undefined);
  }, [rec]);

  useEffect(() => {
    if (!open || !rec) return;
    setText(rec.text);
    play();
    setTimeout(() => fieldRef.current?.focus(), 50);
    return () => audioRef.current?.pause();
  }, [open, rec, play]);

  const run = async (action: () => Promise<void>) => {
    if (!rec || busy) return;
    setBusy(true);
    try {
      await action();
    } finally {
      setBusy(false);
    }
  };
  // the queue shrinks when an item is approved or deleted, so the index stays; skipping moves on
  const approve = () => run(() => onApprove(rec!, text.trim() !== rec!.text ? text.trim() : null));
  const remove = () => run(() => onDelete(rec!));
  const redo = () => run(() => onRedo(rec!));
  const skip = () => setIndex((i) => i + 1);

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.ctrlKey && !e.shiftKey) {
      e.preventDefault();
      approve();
    } else if (e.ctrlKey && e.key === "Enter") {
      e.preventDefault();
      skip();
    } else if (e.ctrlKey && e.key === " ") {
      e.preventDefault();
      play();
    } else if (e.ctrlKey && e.key === "Delete") {
      e.preventDefault();
      remove();
    } else if (e.ctrlKey && e.shiftKey && e.key.toLowerCase() === "r") {
      e.preventDefault();
      redo();
    }
  };

  const done = total - queue.length;
  const finished = open && (!rec || index >= queue.length);

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="md" onKeyDown={onKey}>
      <DialogTitle>{t("review.title", { done, total })}</DialogTitle>
      <DialogContent>
        <LinearProgress variant="determinate" value={total ? (done / total) * 100 : 0} sx={{ mb: 2 }} />
        {finished ? (
          <Typography>{t("review.finished")}</Typography>
        ) : rec ? (
          <Stack spacing={2}>
            <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
              <Typography variant="caption" color="text.secondary">
                {rec.duration.toFixed(1)} s
              </Typography>
              {rec.source && <Chip size="small" variant="outlined" color="info" label={t(`rec.source.${rec.source}` as TKey)} />}
              {rec.quality.issues.map((issue) => (
                <Tooltip key={issue} title={t(`rec.issueHint.${issue}` as TKey)}>
                  <Chip size="small" color="warning" variant="outlined" label={t(`rec.issue.${issue}` as TKey)} />
                </Tooltip>
              ))}
            </Stack>
            <Box sx={{ cursor: "pointer" }} onClick={play}>
              <Waveform peaks={rec.peaks} color={theme.palette.primary.main} height={48} />
            </Box>
            <TextField inputRef={fieldRef} label={t("review.text")} value={text} onChange={(e) => setText(e.target.value)} multiline minRows={2} fullWidth helperText={t("review.textHint")} />
            <Typography variant="caption" color="text.secondary">
              {t("review.keys")}
            </Typography>
          </Stack>
        ) : null}
      </DialogContent>
      <DialogActions sx={{ flexWrap: "wrap", gap: 1 }}>
        <Button onClick={onClose}>{t("review.close")}</Button>
        <Box sx={{ flex: 1 }} />
        {!finished && rec && (
          <>
            <Button startIcon={<ReplayIcon />} onClick={play} disabled={busy}>
              {t("review.play")}
            </Button>
            <Button startIcon={<SkipNextIcon />} onClick={skip} disabled={busy}>
              {t("review.skip")}
            </Button>
            <Button startIcon={<MicIcon />} onClick={redo} disabled={busy} color="warning">
              {t("review.redo")}
            </Button>
            <Button startIcon={<DeleteIcon />} onClick={remove} disabled={busy} color="error">
              {t("review.delete")}
            </Button>
            <Button variant="contained" startIcon={<CheckIcon />} onClick={approve} disabled={busy || text.trim().length < 3}>
              {t("review.ok")}
            </Button>
          </>
        )}
      </DialogActions>
    </Dialog>
  );
}
