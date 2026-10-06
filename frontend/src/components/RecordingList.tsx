import { useEffect, useMemo, useRef, useState } from "react";
import { Box, Button, Chip, IconButton, Stack, TextField, Tooltip, Typography, useTheme } from "@mui/material";
import SearchIcon from "@mui/icons-material/Search";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import StopIcon from "@mui/icons-material/Stop";
import DeleteIcon from "@mui/icons-material/Delete";
import MicIcon from "@mui/icons-material/Mic";
import EditIcon from "@mui/icons-material/Edit";
import CheckIcon from "@mui/icons-material/Check";
import CloseIcon from "@mui/icons-material/Close";
import FlagIcon from "@mui/icons-material/Flag";
import OutlinedFlagIcon from "@mui/icons-material/OutlinedFlag";
import type { Recording } from "../api";
import { useI18n, type TKey } from "../i18n";
import { Scrub } from "./Scrub";

type Filter = "all" | "warnings" | "transcribed" | "unreviewed";
const PAGE = 50;

type Props = {
  items: Recording[];
  disabled: boolean;
  playingId: string | null;
  playingProgress?: number;
  onTogglePlay: (rec: Recording) => void;
  /** play from this point of the take (0..1), like any player's progress bar */
  onSeek: (rec: Recording, ratio: number) => void;
  onDelete: (rec: Recording) => void;
  onRedo: (rec: Recording) => void;
  /** toggles the "record again" mark */
  onMark: (rec: Recording) => void;
  onEdit: (rec: Recording, text: string) => Promise<void>;
};

/** What a warning is about, for its chip: the words in question, or how far off the take is. */
export function issueWords(rec: Recording, issue: string, t: (key: TKey, params?: Record<string, string | number>) => string): string {
  const words = issue === "spelling" ? rec.quality.unknown_words : issue === "tricky_word" ? rec.quality.tricky_words : undefined;
  if (words?.length) return `: ${words.join(", ")}`;
  const level = rec.quality.level_delta_db;
  if (issue === "level_mismatch" && level != null) return `: ${t(level > 0 ? "rec.louder" : "rec.quieter", { db: Math.abs(level).toFixed(0) })}`;
  const tone = rec.quality.tone_delta_db;
  if (issue === "tone_mismatch" && tone != null) return `: ${t(tone > 0 ? "rec.moreBass" : "rec.lessBass", { db: Math.abs(tone).toFixed(0) })}`;
  return "";
}

/** Newest-first list of recordings: waveform, transcript (editable), quality warnings, play and delete. */
export function RecordingList({ items, disabled, playingId, playingProgress, onTogglePlay, onSeek, onDelete, onRedo, onMark, onEdit }: Props) {
  const { t } = useI18n();
  const theme = useTheme();
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [limit, setLimit] = useState(PAGE);

  const newestFirst = useMemo(() => [...items].reverse(), [items]);
  const q = query.trim().toLowerCase();
  const filtered = newestFirst.filter((rec) => {
    if (q && !rec.text.toLowerCase().includes(q)) return false;
    if (filter === "warnings") return rec.quality.issues.length > 0;
    if (filter === "transcribed") return rec.source === "transcribed";
    if (filter === "unreviewed") return !rec.reviewed && (rec.quality.issues.length > 0 || rec.source === "transcribed");
    return true;
  });
  const shown = filtered.slice(0, limit);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const moreRef = useRef<HTMLButtonElement | null>(null);
  const more = filtered.length > shown.length;
  useEffect(() => {
    const button = moreRef.current;
    if (!more || !button || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver((entries) => entries.some((e) => e.isIntersecting) && setLimit((n) => n + PAGE), { root: scrollRef.current, rootMargin: "120px" });
    observer.observe(button);
    return () => observer.disconnect();
  }, [more, shown.length]);
  const index = (rec: Recording) => items.length - newestFirst.indexOf(rec);

  const save = async (rec: Recording) => {
    await onEdit(rec, draft);
    setEditing(null);
  };

  const withWarnings = items.filter((r) => r.quality.issues.length > 0).length;
  const transcribed = items.filter((r) => r.source === "transcribed").length;

  return (
    <Box>
      {items.length > 8 && (
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ sm: "center" }} sx={{ mb: 1 }}>
          <TextField size="small" placeholder={t("rec.search")} value={query} onChange={(e) => setQuery(e.target.value)} InputProps={{ startAdornment: <SearchIcon fontSize="small" sx={{ mr: 0.5, color: "text.secondary" }} /> }} sx={{ flex: 1 }} />
          <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap>
            {(["all", "warnings", "transcribed", "unreviewed"] as Filter[]).map((f) => {
              const n = f === "all" ? items.length : f === "warnings" ? withWarnings : f === "transcribed" ? transcribed : items.filter((r) => !r.reviewed && (r.quality.issues.length > 0 || r.source === "transcribed")).length;
              if (f !== "all" && n === 0) return null;
              return <Chip key={f} size="small" label={`${t(`rec.filter.${f}` as TKey)} (${n})`} color={filter === f ? "primary" : "default"} variant={filter === f ? "filled" : "outlined"} onClick={() => setFilter(f)} />;
            })}
          </Stack>
        </Stack>
      )}
    <Box ref={scrollRef} sx={{ maxHeight: 420, overflow: "auto", border: 1, borderColor: "divider", borderRadius: 2 }}>
      {items.length === 0 && (
        <Typography sx={{ p: 2 }} color="text.secondary">
          {t("rec.empty")}
        </Typography>
      )}
      {items.length > 0 && filtered.length === 0 && (
        <Typography sx={{ p: 2 }} color="text.secondary">
          {t("rec.noMatch")}
        </Typography>
      )}
      {shown.map((rec, idx) => {
        const isPlaying = playingId === rec.id;
        return (
          <Stack key={rec.id} direction="row" spacing={1} alignItems="center" sx={{ px: 1, py: 0.75, borderBottom: idx < shown.length - 1 ? 1 : 0, borderColor: "divider", bgcolor: isPlaying ? "action.selected" : "transparent" }}>
            <IconButton size="small" onClick={() => onTogglePlay(rec)} color={isPlaying ? "primary" : "default"}>
              {isPlaying ? <StopIcon /> : <PlayArrowIcon />}
            </IconButton>
            <Scrub duration={rec.duration} onSeek={(ratio) => onSeek(rec, ratio)} ariaLabel={rec.text} ariaValueNow={isPlaying ? Math.round((playingProgress ?? 0) * 100) : 0} sx={{ width: 110, flexShrink: 0, display: { xs: "none", sm: "block" } }}>
              <Waveform peaks={rec.peaks} color={isPlaying ? theme.palette.primary.main : theme.palette.text.secondary} height={26} progress={isPlaying ? playingProgress : undefined} />
            </Scrub>
            <Box sx={{ flex: 1, minWidth: 0 }}>
              {editing === rec.id ? (
                <TextField size="small" fullWidth multiline value={draft} onChange={(e) => setDraft(e.target.value)} autoFocus />
              ) : (
                // the sentence itself plays the take: the natural target, above all on a phone
                <Typography variant="body2" onClick={() => onTogglePlay(rec)} sx={{ cursor: "pointer" }} title={t(isPlaying ? "rec.stopTooltip" : "rec.playTooltip")}>
                  {rec.text}
                </Typography>
              )}
              {isPlaying && (
                // on a phone the waveform is hidden: a thin bar shows where the playback is, and seeks too
                <Scrub duration={rec.duration} onSeek={(ratio) => onSeek(rec, ratio)} ariaLabel={rec.text} ariaValueNow={Math.round((playingProgress ?? 0) * 100)} sx={{ display: { xs: "block", sm: "none" }, py: 0.5 }}>
                  <Box sx={{ height: 4, borderRadius: 2, bgcolor: "action.hover" }}>
                    <Box sx={{ height: "100%", width: `${(playingProgress ?? 0) * 100}%`, borderRadius: 2, bgcolor: "primary.main" }} />
                  </Box>
                </Scrub>
              )}
              {rec.spoken && editing !== rec.id && (
                <Typography variant="caption" color="text.secondary" sx={{ display: "block" }}>
                  {t("rec.spoken", { text: rec.spoken })}
                </Typography>
              )}
              <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap alignItems="center">
                <Typography variant="caption" color="text.secondary">
                  #{index(rec)} · {rec.duration.toFixed(1)} s · {t("rec.peakInfo", { peak: Math.round((rec.quality.peak ?? 0) * 100), db: rec.quality.rms_db ?? 0 })}
                </Typography>
                {rec.source && (
                  <Tooltip title={t(`rec.sourceHint.${rec.source}` as TKey)}>
                    <Chip size="small" variant="outlined" label={t(`rec.source.${rec.source}` as TKey)} sx={{ height: 18, fontSize: 11 }} />
                  </Tooltip>
                )}
                {rec.quality.issues.map((issue) => (
                  <Tooltip key={issue} title={t(`rec.issueHint.${issue}` as TKey)}>
                    <Chip size="small" color="warning" variant="outlined" label={`${t(`rec.issue.${issue}` as TKey)}${issueWords(rec, issue, t)}`} sx={{ height: 18, fontSize: 11 }} />
                  </Tooltip>
                ))}
              </Stack>
            </Box>
            {editing === rec.id ? (
              <>
                <Tooltip title={t("rec.save")}>
                  <IconButton size="small" color="primary" onClick={() => save(rec)} disabled={draft.trim().length < 3}>
                    <CheckIcon />
                  </IconButton>
                </Tooltip>
                <Tooltip title={t("rec.cancel")}>
                  <IconButton size="small" onClick={() => setEditing(null)}>
                    <CloseIcon />
                  </IconButton>
                </Tooltip>
              </>
            ) : (
              <>
                <Tooltip title={t("rec.editTooltip")}>
                  <span>
                    <IconButton
                      size="small"
                      disabled={disabled}
                      onClick={() => {
                        setEditing(rec.id);
                        setDraft(rec.text);
                      }}
                    >
                      <EditIcon fontSize="small" />
                    </IconButton>
                  </span>
                </Tooltip>
                <Tooltip title={t(rec.redo ? "rec.unmarkRedo" : "rec.markRedo")}>
                  <span>
                    <IconButton size="small" onClick={() => onMark(rec)} disabled={disabled} color={rec.redo ? "warning" : "default"}>
                      {rec.redo ? <FlagIcon fontSize="small" /> : <OutlinedFlagIcon fontSize="small" />}
                    </IconButton>
                  </span>
                </Tooltip>
                <Tooltip title={t("rec.redoTooltip")}>
                  <span>
                    <IconButton size="small" onClick={() => onRedo(rec)} disabled={disabled}>
                      <MicIcon fontSize="small" />
                    </IconButton>
                  </span>
                </Tooltip>
                <Tooltip title={t("rec.deleteTooltip")}>
                  <span>
                    <IconButton size="small" onClick={() => onDelete(rec)} disabled={disabled}>
                      <DeleteIcon fontSize="small" />
                    </IconButton>
                  </span>
                </Tooltip>
              </>
            )}
          </Stack>
        );
      })}
      {filtered.length > shown.length && (
        // scrolling to the end loads the next page by itself; the button stays for a click (and screen readers)
        <Button ref={moreRef} fullWidth size="small" onClick={() => setLimit((n) => n + PAGE)}>
          {t("rec.showMore", { n: filtered.length - shown.length })}
        </Button>
      )}
    </Box>
    </Box>
  );
}

export function Waveform({ peaks, color, height, progress }: { peaks: number[]; color: string; height: number; progress?: number }) {
  const max = Math.max(0.05, ...peaks);
  return (
    <Box sx={{ display: "flex", alignItems: "center", gap: "1px", height }}>
      {peaks.map((p, i) => {
        const played = progress !== undefined && i / peaks.length <= progress;
        return <Box key={i} sx={{ flex: 1, height: `${Math.max(6, (p / max) * 100)}%`, bgcolor: color, borderRadius: 1, opacity: played ? 1 : progress !== undefined ? 0.35 : 0.75 }} />;
      })}
    </Box>
  );
}
