import { Box, Step, StepButton, StepLabel, Stepper, Typography } from "@mui/material";
import { type DatasetReport, type Job, type TrainingState, type VoiceSettings } from "../api";
import { useI18n } from "../i18n";

export type TabId = "voice" | "record" | "data" | "train" | "test";
type Props = { voice: VoiceSettings | null; report: DatasetReport | null; jobs: Job[]; state: TrainingState; tab: TabId; onGo: (tab: TabId) => void };

/** Where the project stands: the four steps with what is done and what comes next, clickable. */
export function ProgressSteps({ voice, report, jobs, state, tab, onGo }: Props) {
  const { t } = useI18n();
  const minutes = report?.minutes ?? 0;
  const goal = report ? (minutes < report.min_minutes ? report.min_minutes : minutes < report.recommended_minutes ? report.recommended_minutes : report.target_minutes) : 30;
  const running = ["downloading", "preparing", "training", "exporting"].includes(state.status);
  const trained = jobs.some((j) => j.exports.length > 0);
  const steps: { id: TabId; label: string; detail: string; done: boolean }[] = [
    { id: "voice", label: t("steps.voice"), detail: !voice ? t("steps.voiceMissing") : voice.has_consent ? voice.name : t("steps.consentMissing"), done: !!voice?.has_consent },
    { id: "record", label: t("steps.record"), detail: report ? t("steps.recordDetail", { minutes: minutes.toFixed(0), goal }) : "", done: !!report && minutes >= report.recommended_minutes },
    { id: "train", label: t("steps.train"), detail: running ? t("steps.trainRunning", { epoch: state.epoch, total: state.total_epochs }) : trained ? t("steps.trainDone", { n: jobs.length }) : report?.ready ? t("steps.trainReady") : t("steps.trainWaiting"), done: trained },
    { id: "test", label: t("steps.test"), detail: trained ? t("steps.testReady") : t("steps.testWaiting"), done: false },
  ];
  const active = steps.findIndex((s) => !s.done);
  return (
    <Box sx={{ px: { xs: 0, sm: 1 }, pb: 1 }}>
      <Stepper nonLinear activeStep={active < 0 ? steps.length : active} alternativeLabel sx={{ "& .MuiStepLabel-label": { mt: 0.5 } }}>
        {steps.map((s) => (
          <Step key={s.id} completed={s.done} active={tab === s.id || (s.id === "record" && tab === "data")}>
            <StepButton onClick={() => onGo(s.id)} disabled={!voice && s.id !== "voice"} sx={{ py: 0.5, my: -0.5 /* MUI gives the button a -24px margin for its 24px padding; a smaller padding needs a matching margin or the circle is pushed out and clipped */ }}>
              <StepLabel>
                <Typography variant="body2" fontWeight={tab === s.id ? 700 : 500} lineHeight={1.2}>
                  {s.label}
                </Typography>
                <Typography variant="caption" color="text.secondary" display="block" lineHeight={1.2}>
                  {s.detail}
                </Typography>
              </StepLabel>
            </StepButton>
          </Step>
        ))}
      </Stepper>
    </Box>
  );
}
