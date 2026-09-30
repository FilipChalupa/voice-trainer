import { useEffect, useState } from "react";
import { Alert, Box, Button, Card, CardContent, CardHeader, Stack, Typography } from "@mui/material";
import DatasetIcon from "@mui/icons-material/Dataset";
import DownloadIcon from "@mui/icons-material/Download";
import { api, type DatasetReport } from "../api";
import { useI18n } from "../i18n";

/** What will go into training: amount of audio, warnings, letter coverage, length distribution. */
export function DatasetCard({ version }: { version: number }) {
  const { t } = useI18n();
  const [report, setReport] = useState<DatasetReport | null>(null);

  useEffect(() => {
    api.dataset().then(setReport).catch(() => setReport(null));
  }, [version]);

  if (!report) return null;
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
          <Alert severity={report.ready ? "success" : "warning"} variant="outlined">
            {report.ready ? t("ds.ready") : t("ds.notReady", { what: missing.join(", ") })}
          </Alert>
          {report.count > 0 && (
            <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap" useFlexGap>
              <Button variant="outlined" size="small" href="/api/dataset/export" download startIcon={<DownloadIcon />}>
                {t("ds.export")}
              </Button>
              <Typography variant="caption" color="text.secondary">
                {t("ds.exportHint")}
              </Typography>
            </Stack>
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
