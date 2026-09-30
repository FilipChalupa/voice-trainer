import { Chip, Tooltip } from "@mui/material";
import ModelTrainingIcon from "@mui/icons-material/ModelTraining";
import { type TrainingState } from "../api";
import { useI18n, type TKey } from "../i18n";

/** Header chip while training runs, visible on every tab; a click goes to the training tab. */
export function TrainingChip({ state, onClick }: { state: TrainingState; onClick: () => void }) {
  const { t } = useI18n();
  if (!["downloading", "preparing", "training", "exporting"].includes(state.status)) return null;
  const eta = state.status === "training" && state.epoch_seconds ? (state.total_epochs - state.epoch) * state.epoch_seconds : null;
  const label =
    state.status === "training"
      ? `${t("chip.training", { epoch: state.epoch, total: state.total_epochs })}${eta ? ` · ${eta < 5400 ? `${Math.round(eta / 60)} min` : `${(eta / 3600).toFixed(1)} h`}` : ""}`
      : t(`train.status.${state.status}` as TKey);
  return (
    <Tooltip title={t("chip.tooltip", { name: state.name ?? "" })}>
      <Chip size="small" color="info" icon={<ModelTrainingIcon />} label={label} onClick={onClick} sx={{ mr: 1, maxWidth: 220 }} />
    </Tooltip>
  );
}
