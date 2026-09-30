import { Box, Button, Card, CardContent, CardHeader, Chip, IconButton, Table, TableBody, TableCell, TableHead, TableRow, Tooltip, Typography } from "@mui/material";
import HistoryIcon from "@mui/icons-material/History";
import DownloadIcon from "@mui/icons-material/Download";
import DeleteIcon from "@mui/icons-material/Delete";
import { api, type Job } from "../api";
import { errorText, useI18n, type TKey } from "../i18n";

type Props = { jobs: Job[]; liveEpoch: number; disabled: boolean; onChanged: () => void; onError: (message: string) => void };

const COLORS: Record<string, "success" | "error" | "warning" | "info" | "default"> = { done: "success", failed: "error", cancelled: "warning", running: "info", interrupted: "warning" };
const STATUSES = new Set(["done", "failed", "cancelled", "running", "interrupted"]);

export function JobsCard({ jobs, liveEpoch, disabled, onChanged, onError }: Props) {
  const { t } = useI18n();
  const remove = async (id: string) => {
    try {
      await api.deleteJob(id);
      onChanged();
    } catch (e) {
      onError(errorText(t, e));
    }
  };

  return (
    <Card>
      <CardHeader avatar={<HistoryIcon color="primary" />} title={t("jobs.title")} subheader={t("jobs.subtitle")} />
      <CardContent>
        {jobs.length === 0 ? (
          <Typography color="text.secondary">{t("jobs.empty")}</Typography>
        ) : (
          <Box sx={{ overflowX: "auto" }}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>{t("jobs.started")}</TableCell>
                  <TableCell>{t("jobs.status")}</TableCell>
                  <TableCell>{t("jobs.data")}</TableCell>
                  <TableCell>{t("jobs.epochs")}</TableCell>
                  <TableCell>{t("jobs.quality")}</TableCell>
                  <TableCell>{t("jobs.voice")}</TableCell>
                  <TableCell />
                </TableRow>
              </TableHead>
              <TableBody>
                {jobs.map((job) => (
                  <TableRow key={job.job_id} hover>
                    <TableCell>{new Date(job.created_at).toLocaleString()}</TableCell>
                    <TableCell>
                      <Chip size="small" label={t((STATUSES.has(job.status) ? `jobs.s.${job.status}` : "jobs.s.failed") as TKey)} color={COLORS[job.status] ?? "default"} />
                    </TableCell>
                    <TableCell>{t("jobs.dataValue", { minutes: job.minutes?.toFixed(1) ?? "–", recordings: job.recordings ?? "–" })}</TableCell>
                    <TableCell>
                      {job.status === "running" ? liveEpoch : (job.epoch ?? 0)} / {job.max_epochs}
                    </TableCell>
                    <TableCell>{job.validation_last?.val_mos != null ? job.validation_last.val_mos.toFixed(2) : "–"}</TableCell>
                    <TableCell>
                      {job.bundle_url ? (
                        <Button size="small" variant="outlined" startIcon={<DownloadIcon />} href={job.bundle_url} download>
                          ZIP
                        </Button>
                      ) : (
                        "—"
                      )}
                    </TableCell>
                    <TableCell align="right">
                      <Tooltip title={t("jobs.deleteTooltip")}>
                        <span>
                          <IconButton size="small" onClick={() => remove(job.job_id)} disabled={disabled || job.status === "running"}>
                            <DeleteIcon />
                          </IconButton>
                        </span>
                      </Tooltip>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Box>
        )}
      </CardContent>
    </Card>
  );
}
