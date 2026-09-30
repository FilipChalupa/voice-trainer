import { Typography } from "@mui/material";
import { type Recording } from "../api";
import { useI18n } from "../i18n";

type Props = { recordings: Recording[]; minutes: { min: number; recommended: number; target: number }; totalMinutes: number };

/** Today's work and the pace of the last quarter of an hour, with the time to the next goal at that pace. */
export function sessionStats(recordings: Recording[], minutes: Props["minutes"], totalMinutes: number, now = Date.now()) {
  const today = new Date(now).toDateString();
  const todays = recordings.filter((r) => new Date(r.created).toDateString() === today);
  if (!todays.length) return null;
  const recent = recordings.filter((r) => now - new Date(r.created).getTime() < 15 * 60 * 1000);
  const spanHours = recent.length >= 3 ? (now - new Date(recent[0].created).getTime()) / 3600000 : 0;
  const perHour = spanHours > 0 ? Math.round(recent.length / spanHours) : 0;
  const minutesPerHour = spanHours > 0 ? recent.reduce((a, r) => a + r.duration, 0) / 60 / spanHours : 0;
  const goal = totalMinutes < minutes.min ? minutes.min : totalMinutes < minutes.recommended ? minutes.recommended : totalMinutes < minutes.target ? minutes.target : null;
  const toGoal = goal !== null && minutesPerHour > 0 ? Math.max(1, Math.round(((goal - totalMinutes) / minutesPerHour) * 60)) : null;
  return { count: todays.length, minutes: todays.reduce((a, r) => a + r.duration, 0) / 60, perHour, goal, toGoal };
}

export function SessionStats({ recordings, minutes, totalMinutes }: Props) {
  const { t } = useI18n();
  const session = sessionStats(recordings, minutes, totalMinutes);
  if (!session) return null;
  return (
    <Typography variant="body2" color="text.secondary">
      {t("studio.session", { n: session.count, minutes: session.minutes.toFixed(1) })}
      {session.perHour ? ` · ${t("studio.pace", { n: session.perHour })}` : ""}
      {session.perHour && session.toGoal !== null && session.goal !== null ? ` · ${t("studio.toGoal", { goal: session.goal, minutes: session.toGoal })}` : ""}
    </Typography>
  );
}
