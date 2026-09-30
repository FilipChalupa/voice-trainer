import { useEffect, useState } from "react";
import { Alert, Button, Chip, Dialog, DialogActions, DialogContent, DialogTitle, IconButton, LinearProgress, Stack, Table, TableBody, TableCell, TableHead, TableRow, Tooltip, Typography } from "@mui/material";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import GraphicEqIcon from "@mui/icons-material/GraphicEq";
import { api, type CheckState, type Job } from "../api";
import { errorText, useI18n } from "../i18n";
import { playSequence } from "../lib/audio";

type Props = { job: Job | null; onClose: () => void; onError: (message: string) => void };

/** Every training sentence read by the trained voice and compared with the take: the worst ones are listed. */
export function CheckDialog({ job, onClose, onError }: Props) {
  const { t } = useI18n();
  const [state, setState] = useState<CheckState | null>(null);
  const running = state?.status === "running";

  useEffect(() => {
    if (!job) return;
    let alive = true;
    const poll = () => api.check(job.job_id).then((s) => alive && setState(s)).catch(() => undefined);
    poll();
    const timer = setInterval(poll, running ? 1500 : 15000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [job, running]);

  const start = async () => {
    if (!job) return;
    try {
      setState(await api.startCheck(job.job_id));
    } catch (e) {
      onError(errorText(t, e));
    }
  };

  const play = (url: string) => playSequence([url]);

  const result = state?.result ?? null;
  const pct = state?.progress && state.progress.total > 0 ? (state.progress.current / state.progress.total) * 100 : 0;

  return (
    <Dialog open={!!job} onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle>{t("check.title")}</DialogTitle>
      <DialogContent>
        <Stack spacing={2}>
          <Typography variant="body2" color="text.secondary">
            {t("check.help")}
          </Typography>
          {running && (
            <Stack spacing={0.5}>
              <Typography variant="subtitle2">{t("check.running", { current: state?.progress?.current ?? 0, total: state?.progress?.total ?? 0 })}</Typography>
              <LinearProgress variant="determinate" value={pct} />
            </Stack>
          )}
          {state?.status === "failed" && <Alert severity="error">{state.error}</Alert>}
          {result && !running && (
            <>
              <Alert severity={result.flagged > 0 ? "warning" : "success"} variant="outlined">
                {t("check.summary", { count: result.count, flagged: result.flagged, when: new Date(result.created_at).toLocaleString() })}
              </Alert>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>{t("check.sentence")}</TableCell>
                    <TableCell align="right">{t("check.distance")}</TableCell>
                    <TableCell align="right">{t("check.listen")}</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {result.items.slice(0, 15).map((row) => (
                    <TableRow key={row.id} hover>
                      <TableCell>
                        <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
                          <Typography variant="body2">{row.text}</Typography>
                          {row.flagged && <Chip size="small" color="warning" variant="outlined" label={t("check.flagged")} sx={{ height: 18, fontSize: 11 }} />}
                        </Stack>
                      </TableCell>
                      <TableCell align="right">
                        <Typography variant="body2" color={row.flagged ? "warning.main" : "text.secondary"}>
                          {row.distance.toFixed(3)} · z {row.z.toFixed(1)}
                        </Typography>
                      </TableCell>
                      <TableCell align="right" sx={{ whiteSpace: "nowrap" }}>
                        <Tooltip title={t("check.playOriginal")}>
                          <IconButton size="small" onClick={() => play(`/api/recordings/${row.id}/audio`)}>
                            <PlayArrowIcon />
                          </IconButton>
                        </Tooltip>
                        <Tooltip title={t("check.playModel")}>
                          <IconButton size="small" onClick={() => play(`/api/jobs/${result.job_id}/check/audio/${row.id}`)}>
                            <GraphicEqIcon />
                          </IconButton>
                        </Tooltip>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </>
          )}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{t("check.close")}</Button>
        <Button variant="contained" onClick={start} disabled={running || !job?.exports.length}>
          {result ? t("check.again") : t("check.start")}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
