import { useEffect, useState } from "react";
import { Alert, Button, Stack, Typography } from "@mui/material";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import RadioButtonUncheckedIcon from "@mui/icons-material/RadioButtonUnchecked";
import type { Job } from "../api";
import { useI18n, type TKey } from "../i18n";

type Step = "listen" | "test" | "compare" | "deploy";
const KEY = "voice-trainer.steps.";

function readDone(jobId: string): Set<Step> {
  try {
    return new Set(JSON.parse(localStorage.getItem(KEY + jobId) ?? "[]") as Step[]);
  } catch {
    return new Set();
  }
}

/** What to do with a finished run: listen, test, compare, deploy. The server knows about the test and the
 *  deployment; a listen or a comparison counts as done once the person went there. */
export function NextSteps({ job, onListen, onTest, onCompare, onDeploy }: { job: Job; onListen: () => void; onTest: () => void; onCompare: () => void; onDeploy: () => void }) {
  const { t } = useI18n();
  const [done, setDone] = useState<Set<Step>>(() => readDone(job.job_id));
  useEffect(() => setDone(readDone(job.job_id)), [job.job_id]);
  const mark = (step: Step) => {
    const next = new Set(done).add(step);
    setDone(next);
    try {
      localStorage.setItem(KEY + job.job_id, JSON.stringify([...next]));
    } catch {
      /* private mode */
    }
  };
  const steps: { step: Step; done: boolean; action: () => void }[] = [
    { step: "listen", done: done.has("listen"), action: () => (mark("listen"), onListen()) },
    { step: "test", done: job.intelligibility != null, action: onTest },
    { step: "compare", done: done.has("compare"), action: () => (mark("compare"), onCompare()) },
    { step: "deploy", done: !!job.deployed, action: onDeploy },
  ];
  const left = steps.filter((s) => !s.done).length;
  return (
    <Alert severity={left ? "info" : "success"} variant="outlined" icon={false} data-testid="next-steps">
      <Typography variant="subtitle2" gutterBottom>
        {t("next.title", { when: new Date(job.created_at).toLocaleString() })}
      </Typography>
      <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
        {steps.map((s) => (
          <Button key={s.step} size="small" variant={s.done ? "text" : "outlined"} color={s.done ? "success" : "primary"} startIcon={s.done ? <CheckCircleIcon /> : <RadioButtonUncheckedIcon />} onClick={s.action}>
            {t(`next.${s.step}` as TKey)}
          </Button>
        ))}
      </Stack>
    </Alert>
  );
}
