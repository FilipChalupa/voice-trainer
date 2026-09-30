import { useCallback, useEffect, useState } from "react";
import { Box, Button, Card, CardContent, CardHeader, LinearProgress, Stack, Table, TableBody, TableCell, TableRow, Tooltip, Typography } from "@mui/material";
import StorageIcon from "@mui/icons-material/Storage";
import DeleteSweepIcon from "@mui/icons-material/DeleteSweep";
import CleaningServicesIcon from "@mui/icons-material/CleaningServices";
import { api, type StorageInfo } from "../api";
import { errorText, useI18n } from "../i18n";

type Props = { version: number; disabled: boolean; onError: (message: string) => void; onChanged: () => void };

export function formatBytes(n: number): string {
  if (n >= 1 << 30) return `${(n / (1 << 30)).toFixed(n >= 10 * (1 << 30) ? 0 : 1)} GB`;
  if (n >= 1 << 20) return `${(n / (1 << 20)).toFixed(0)} MB`;
  if (n >= 1024) return `${(n / 1024).toFixed(0)} kB`;
  return `${n} B`;
}

/** What the data folder holds: shared models, every voice with its recordings and runs, and what can go. */
export function StorageCard({ version, disabled, onError, onChanged }: Props) {
  const { t } = useI18n();
  const [info, setInfo] = useState<StorageInfo | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => api.storage().then(setInfo).catch(() => setInfo(null)), []);
  useEffect(() => {
    load();
  }, [load, version]);

  const act = async (fn: () => Promise<{ freed: number }>) => {
    setBusy(true);
    try {
      await fn();
      await load();
      onChanged();
    } catch (e) {
      onError(errorText(t, e));
    } finally {
      setBusy(false);
    }
  };

  if (!info) return null;
  const used = info.disk_total - info.disk_free;
  const segments = [
    { key: "base", label: t("storage.base"), bytes: info.base_total, color: "#7e57c2" },
    { key: "recordings", label: t("storage.recordings"), bytes: info.voices.reduce((a, v) => a + v.recordings, 0), color: "#26a69a" },
    { key: "runs", label: t("storage.runs"), bytes: info.voices.reduce((a, v) => a + v.jobs_total - v.cache_total, 0), color: "#42a5f5" },
    { key: "cache", label: t("storage.cache"), bytes: info.reclaimable.cache, color: "#ffb300" },
    { key: "trash", label: t("storage.trash"), bytes: info.reclaimable.trash, color: "#ef5350" },
  ].filter((s) => s.bytes > 0);
  const rows: [string, number, string?][] = [
    [t("storage.baseCheckpoints"), info.base.checkpoints],
    [t("storage.baseVoices"), info.base.base_voices],
    [t("storage.whisper"), info.base.whisper],
    [t("storage.torchHub"), info.base.torch_hub],
    [t("storage.prompts"), info.base.prompts],
  ];

  return (
    <Card>
      <CardHeader avatar={<StorageIcon color="primary" />} title={t("storage.title")} subheader={t("storage.subtitle", { total: formatBytes(info.total) })} />
      <CardContent>
        <Stack spacing={2}>
          <Box>
            <Box sx={{ display: "flex", height: 14, borderRadius: 7, overflow: "hidden", bgcolor: "action.hover" }}>
              {segments.map((s) => (
                <Tooltip key={s.key} title={`${s.label}: ${formatBytes(s.bytes)}`}>
                  <Box sx={{ width: `${(s.bytes / Math.max(1, info.total)) * 100}%`, bgcolor: s.color, minWidth: s.bytes > 0 ? 3 : 0 }} />
                </Tooltip>
              ))}
            </Box>
            <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap sx={{ mt: 0.5 }}>
              {segments.map((s) => (
                <Stack key={s.key} direction="row" spacing={0.5} alignItems="center">
                  <Box sx={{ width: 10, height: 10, borderRadius: 5, bgcolor: s.color }} />
                  <Typography variant="caption" color="text.secondary">
                    {s.label} {formatBytes(s.bytes)}
                  </Typography>
                </Stack>
              ))}
            </Stack>
          </Box>

          <Box>
            <Typography variant="caption" color="text.secondary">
              {t("storage.disk", { free: formatBytes(info.disk_free), total: formatBytes(info.disk_total) })}
            </Typography>
            <LinearProgress variant="determinate" value={(used / Math.max(1, info.disk_total)) * 100} sx={{ height: 6, borderRadius: 3, mt: 0.5 }} color={info.disk_free < 20 * (1 << 30) ? "warning" : "primary"} />
          </Box>

          <Table size="small">
            <TableBody>
              {rows.map(([label, bytes]) => (
                <TableRow key={label}>
                  <TableCell sx={{ pl: 0 }}>{label}</TableCell>
                  <TableCell align="right" sx={{ pr: 0, fontVariantNumeric: "tabular-nums" }}>
                    {formatBytes(bytes)}
                  </TableCell>
                </TableRow>
              ))}
              {info.voices.map((v) => (
                <TableRow key={v.id}>
                  <TableCell sx={{ pl: 0 }}>
                    <Typography variant="body2" fontWeight={600}>
                      {v.name}
                      {v.name.toLowerCase() !== v.id ? ` (${v.id})` : ""}
                    </Typography>
                    <Typography variant="caption" color="text.secondary">
                      {t("storage.voiceDetail", { recordings: formatBytes(v.recordings), runs: v.jobs.length, jobs: formatBytes(v.jobs_total), trash: formatBytes(v.trash) })}
                    </Typography>
                  </TableCell>
                  <TableCell align="right" sx={{ pr: 0, fontVariantNumeric: "tabular-nums", verticalAlign: "top" }}>
                    {formatBytes(v.total)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>

          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap alignItems="center">
            <Button size="small" variant="outlined" startIcon={<DeleteSweepIcon />} onClick={() => act(api.emptyTrash)} disabled={busy || info.reclaimable.trash === 0}>
              {t("storage.emptyTrash", { size: formatBytes(info.reclaimable.trash) })}
            </Button>
            <Button size="small" variant="outlined" startIcon={<CleaningServicesIcon />} onClick={() => act(api.clearCache)} disabled={busy || disabled || info.reclaimable.cache === 0}>
              {t("storage.clearCache", { size: formatBytes(info.reclaimable.cache) })}
            </Button>
            <Typography variant="caption" color="text.secondary">
              {t("storage.hint")}
            </Typography>
          </Stack>
        </Stack>
      </CardContent>
    </Card>
  );
}
