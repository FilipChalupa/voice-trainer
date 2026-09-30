import { useRef, useState } from "react";
import { Alert, Box, Button, Card, CardContent, CardHeader, Stack, Typography } from "@mui/material";
import DatasetIcon from "@mui/icons-material/Dataset";
import DownloadIcon from "@mui/icons-material/Download";
import UploadIcon from "@mui/icons-material/Upload";
import { api, type DatasetReport, type ImportResult } from "../api";
import { errorText, useI18n } from "../i18n";

/** What will go into training: amount of audio, warnings, letter coverage, length distribution. */
type Props = { report: DatasetReport | null; disabled: boolean; onImported: () => void; onError: (message: string) => void };

export function DatasetCard({ report, disabled, onImported, onError }: Props) {
  const { t } = useI18n();
  const [importing, setImporting] = useState(false);
  const [result, setResult] = useState<ImportResult | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);

  const importZip = async (file: File | undefined) => {
    if (!file) return;
    setImporting(true);
    setResult(null);
    try {
      const res = await api.importDataset(file);
      setResult(res);
      onImported();
    } catch (e) {
      onError(errorText(t, e));
    } finally {
      setImporting(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  if (!report) return null;
  const skippedReasons = result ? Object.entries(result.skipped.reduce<Record<string, number>>((acc, s) => ({ ...acc, [s.reason]: (acc[s.reason] ?? 0) + 1 }), {})) : [];
  const missing = [!report.has_consent && t("ds.needConsent"), report.minutes < report.min_minutes && t("ds.needMinutes", { min: report.min_minutes })].filter(Boolean) as string[];
  const max = Math.max(1, ...report.duration_histogram);
  const labels = ["0–2", "2–4", "4–6", "6–8", "8–10", "10–12", "12–14", "14+"];

  return (
    <Card>
      <CardHeader avatar={<DatasetIcon color="primary" />} title={t("ds.title")} subheader={t("ds.subtitle")} />
      <CardContent>
        <Stack spacing={2}>
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
            <Stat label={t("ds.minutes")} value={report.minutes.toFixed(1)} />
            <Stat label={t("ds.count")} value={String(report.count)} />
            <Stat label={t("ds.mean")} value={`${report.mean_seconds.toFixed(1)} s`} />
            <Stat label={t("ds.flagged")} value={String(report.flagged)} />
          </Stack>
          {report.count > 0 && (
            <Box>
              <Typography variant="caption" color="text.secondary">
                {t("ds.histogram")}
              </Typography>
              <Stack direction="row" spacing={0.5} alignItems="flex-end" sx={{ height: 80, mt: 0.5 }}>
                {report.duration_histogram.map((n, i) => (
                  <Box key={i} sx={{ flex: 1, textAlign: "center" }}>
                    <Box sx={{ height: `${(n / max) * 60}px`, minHeight: n ? 2 : 0, bgcolor: "primary.main", borderRadius: "4px 4px 0 0", mx: "2px" }} title={String(n)} />
                    <Typography variant="caption" color="text.secondary" sx={{ fontSize: 10 }}>
                      {labels[i]}
                    </Typography>
                  </Box>
                ))}
              </Stack>
            </Box>
          )}
          {report.count > 0 && (
            <Typography variant="body2" color={report.rare_letters.length ? "warning.main" : "text.secondary"}>
              {report.rare_letters.length ? t("ds.rare", { letters: report.rare_letters.join(", ") }) : t("ds.rareNone")}
            </Typography>
          )}
          {(report.issues.level_mismatch > 0 || report.issues.noisy > 0) && (
            <Alert severity="warning" variant="outlined">
              {t("ds.inconsistent", { level: report.issues.level_mismatch, noisy: report.issues.noisy })}
            </Alert>
          )}
          <Alert severity={report.ready ? "success" : "warning"} variant="outlined">
            {report.ready ? t("ds.ready") : t("ds.notReady", { what: missing.join(", ") })}
          </Alert>
          <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap" useFlexGap>
            {report.count > 0 && (
              <Button variant="outlined" size="small" href="/api/dataset/export" download startIcon={<DownloadIcon />}>
                {t("ds.export")}
              </Button>
            )}
            {report.count > 0 && (
              <Button variant="outlined" size="small" href="/api/dataset/export/blocks" download startIcon={<DownloadIcon />}>
                {t("ds.exportBlocks")}
              </Button>
            )}
            <Button variant="outlined" size="small" component="label" startIcon={<UploadIcon />} disabled={disabled || importing}>
              {importing ? t("ds.importing") : t("ds.import")}
              <input ref={fileRef} type="file" accept=".zip,application/zip" hidden onChange={(e) => importZip(e.target.files?.[0])} />
            </Button>
            <Typography variant="caption" color="text.secondary">
              {t("ds.exportHint")} {t("ds.exportBlocksHint")}
            </Typography>
          </Stack>
          {result && (
            <Alert severity={result.imported > 0 ? "success" : "warning"} variant="outlined" onClose={() => setResult(null)}>
              {t("ds.imported", { n: result.imported, minutes: result.minutes.toFixed(1) })}
              {result.consent_imported ? ` ${t("ds.importedConsent")}` : ""}
              {skippedReasons.length > 0 ? ` ${t("ds.importSkipped", { list: skippedReasons.map(([reason, n]) => `${n}× ${reason}`).join(", ") })}` : ""}
            </Alert>
          )}
        </Stack>
      </CardContent>
    </Card>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <Box sx={{ px: 1.5, py: 1, border: 1, borderColor: "divider", borderRadius: 2, minWidth: 120 }}>
      <Typography variant="caption" color="text.secondary" display="block">
        {label}
      </Typography>
      <Typography variant="subtitle1" fontWeight={600}>
        {value}
      </Typography>
    </Box>
  );
}
