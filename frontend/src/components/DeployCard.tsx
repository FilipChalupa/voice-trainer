import { useMemo, useState } from "react";
import { Alert, Box, Button, Card, CardContent, CardHeader, MenuItem, Stack, TextField, Typography } from "@mui/material";
import RocketLaunchIcon from "@mui/icons-material/RocketLaunch";
import DownloadIcon from "@mui/icons-material/Download";
import { type Job } from "../api";
import { useI18n, type TKey } from "../i18n";

const VARIANTS = new Set(["last", "best_mos", "best_mel"]);

/** Getting the voice out: the ZIP bundle, the single files and the Home Assistant steps. */
export function DeployCard({ jobs }: { jobs: Job[] }) {
  const { t } = useI18n();
  const runs = useMemo(() => jobs.filter((j) => j.exports.length > 0), [jobs]);
  const [jobId, setJobId] = useState("");
  const job = runs.find((j) => j.job_id === jobId) ?? runs[0];
  if (!job) return null;
  const variantLabel = (variant: string) => (VARIANTS.has(variant) ? t(`test.variant.${variant}` as TKey) : variant);
  const main = job.exports.find((e) => e.variant === (job.stopped_early ? "best_mel" : "last")) ?? job.exports[0];
  return (
    <Card>
      <CardHeader avatar={<RocketLaunchIcon color="primary" />} title={t("deploy.title")} subheader={t("deploy.subtitle")} />
      <CardContent>
        <Stack spacing={2}>
          {runs.length > 1 && (
            <TextField select size="small" label={t("test.run")} value={job.job_id} onChange={(e) => setJobId(e.target.value)} sx={{ maxWidth: 320 }}>
              {runs.map((r) => (
                <MenuItem key={r.job_id} value={r.job_id}>
                  {r.name} · {new Date(r.created_at).toLocaleString()}
                </MenuItem>
              ))}
            </TextField>
          )}
          <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap" useFlexGap>
            {job.bundle_url && (
              <Button variant="contained" startIcon={<DownloadIcon />} href={job.bundle_url} download>
                {t("test.download")}
              </Button>
            )}
            <Typography variant="body2" color="text.secondary">
              {t("deploy.bundleHint", { name: main.file.replace(/\.onnx$/, "") })}
            </Typography>
          </Stack>
          <Box>
            <Typography variant="subtitle2" gutterBottom>
              {t("test.files")}
            </Typography>
            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
              {job.exports.map((e) => (
                <Button key={e.file} size="small" href={e.url} download startIcon={<DownloadIcon />} sx={{ textTransform: "none" }}>
                  {e.file} ({(e.size / (1 << 20)).toFixed(0)} MB) · {variantLabel(e.variant)}
                </Button>
              ))}
            </Stack>
          </Box>
          <Alert severity="info" variant="outlined">
            {t("test.ha")}
          </Alert>
          {job.language === "cs" && (
            <Box>
              <Typography variant="subtitle2" gutterBottom>
                {t("deploy.dictTitle")}
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                {t("deploy.dictHelp")}
              </Typography>
              <Button size="small" variant="outlined" href="/api/espeak-dict" download="cs_dict" startIcon={<DownloadIcon />} sx={{ textTransform: "none" }}>
                cs_dict
              </Button>
              <Box component="pre" sx={{ mt: 1, p: 1, bgcolor: "action.hover", borderRadius: 1, fontSize: 12, overflowX: "auto" }}>
                {"volumes:\n  - ./piper-data/cs_dict:/usr/src/.venv/lib/python3.13/site-packages/piper/espeak-ng-data/cs_dict:ro"}
              </Box>
            </Box>
          )}
        </Stack>
      </CardContent>
    </Card>
  );
}
