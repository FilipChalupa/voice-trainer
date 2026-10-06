import { useEffect, useState } from "react";
import { Alert, Button, Dialog, DialogActions, DialogContent, DialogTitle, IconButton, LinearProgress, Stack, Table, TableBody, TableCell, TableHead, TableRow, Tooltip, Typography } from "@mui/material";
import GraphicEqIcon from "@mui/icons-material/GraphicEq";
import { api, type IntelligibilityState, type Job } from "../api";
import { errorText, useI18n } from "../i18n";
import { playSequence } from "../lib/audio";
import { notifyDone } from "../lib/notify";

type Props = { job: Job | null; onClose: () => void; onChanged: () => void; onError: (message: string) => void };

/** The trained voice reads a fixed set of sentences, Whisper writes down what it hears: one number to compare
 *  runs by and the sentences the voice garbles. */
export function IntelligibilityDialog({ job, onClose, onChanged, onError }: Props) {
  const { t } = useI18n();
  const [state, setState] = useState<IntelligibilityState | null>(null);
  const running = state?.status === "running";

  // another run: start from nothing (not on every change of `running`, that would wipe the progress just shown)
  useEffect(() => setState(null), [job?.job_id]);
  useEffect(() => {
    if (!job) return;
    let alive = true;
    const poll = () =>
      api
        .intelligibility(job.job_id)
        .then((s) => alive && setState(s))
        .catch(() => undefined);
    poll();
    const timer = setInterval(poll, running ? 1500 : 15000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [job, running]);
  // the score in the list of runs follows a finished test
  useEffect(() => {
    if (state?.status === "done") {
      onChanged();
      if (state.result) notifyDone(t("notify.testDone", { score: state.result.score.toFixed(1) }));
    }
  }, [state?.status, state?.result?.created_at]); // eslint-disable-line react-hooks/exhaustive-deps

  const start = async () => {
    if (!job) return;
    try {
      setState(await api.startIntelligibility(job.job_id));
    } catch (e) {
      onError(errorText(t, e));
    }
  };

  const result = state?.result ?? null;
  const pct = state?.progress && state.progress.total > 0 ? (state.progress.current / state.progress.total) * 100 : 0;
  // the voice reads first, then the base voice (when it has no stored result yet)
  const half = state?.progress && state.progress.total > 0 ? state.progress.total / 2 : 0;
  const stage = !state?.progress || state.progress.total === 0 ? "start" : half >= 24 && state.progress.current >= half ? "base" : "voice";
  const imperfect = result?.items.filter((row) => row.similarity < 0.999) ?? [];

  return (
    <Dialog open={!!job} onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle>{t("intel.title")}</DialogTitle>
      <DialogContent>
        <Stack spacing={2}>
          <Typography variant="body2" color="text.secondary">
            {t("intel.help")}
          </Typography>
          {running && (
            <Stack spacing={0.5} data-testid="intel-progress">
              <Typography variant="subtitle2">{stage === "start" ? t("intel.starting") : t("intel.running", { current: state?.progress?.current ?? 0, total: state?.progress?.total ?? 0 })}</Typography>
              <LinearProgress variant={pct > 0 ? "determinate" : "indeterminate"} value={pct} />
              <Typography variant="caption" color="text.secondary">
                {stage === "base" ? t("intel.stageBase") : t("intel.stageVoice")}
              </Typography>
            </Stack>
          )}
          {state?.status === "failed" && <Alert severity="error">{state.error}</Alert>}
          {result && !running && (
            <>
              <Alert severity={result.garbled > 0 ? "warning" : "success"} variant="outlined">
                {t("intel.summary", { score: result.score.toFixed(1), words: result.word_accuracy.toFixed(1), garbled: result.garbled, count: result.count })}{" "}
                {result.baseline ? t("intel.baseline", { score: result.baseline.score.toFixed(1), garbled: result.baseline.garbled }) : t("intel.noBaseline")}
              </Alert>
              {imperfect.length > 0 ? (
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>{t("intel.sentence")}</TableCell>
                      <TableCell align="right">{t("intel.match")}</TableCell>
                      <TableCell />
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {imperfect.map((row) => (
                      <TableRow key={row.index} hover>
                        <TableCell>
                          <Typography variant="body2">{row.text}</Typography>
                          <Typography variant="body2" color={row.similarity < 0.9 ? "warning.main" : "text.secondary"}>
                            {t("flow.heard", { text: row.heard || "—" })}
                          </Typography>
                          {row.missed.length > 0 && (
                            <Typography variant="caption" color="text.secondary">
                              {t("intel.missed", { words: row.missed.join(", ") })}
                            </Typography>
                          )}
                        </TableCell>
                        <TableCell align="right">{Math.round(row.similarity * 100)} %</TableCell>
                        <TableCell align="right">
                          <Tooltip title={t("check.playModel")}>
                            <IconButton size="small" onClick={() => playSequence([`/api/jobs/${result.job_id}/intelligibility/audio/${row.index}?t=${encodeURIComponent(result.created_at)}`])}>
                              <GraphicEqIcon />
                            </IconButton>
                          </Tooltip>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              ) : null}
              <Typography variant="caption" color="text.secondary">
                {t("intel.rest", { n: result.count - imperfect.length, when: new Date(result.created_at).toLocaleString() })}
              </Typography>
            </>
          )}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{t("check.close")}</Button>
        <Button variant="contained" onClick={start} disabled={running || !job?.exports.length}>
          {running ? t("intel.runningShort") : result ? t("check.again") : t("intel.start")}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
