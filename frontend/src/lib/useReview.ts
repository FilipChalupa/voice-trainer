import { useCallback, useMemo } from "react";
import { api, type Recording } from "../api";
import { errorText, useI18n } from "../i18n";

/** The takes that need a person's look (warnings, machine transcripts) and the actions of the review dialog. */
export function useReview(recordings: Recording[], refresh: () => Promise<void>, onChanged: () => void, onError: (message: string) => void) {
  const { t } = useI18n();
  const queue = useMemo(() => recordings.filter((r) => !r.reviewed && (r.quality.issues.length > 0 || r.source === "transcribed")), [recordings]);

  const approve = useCallback(
    async (rec: Recording, newText: string | null) => {
      try {
        await api.reviewRecording(rec.id, newText);
        await refresh();
      } catch (e) {
        onError(errorText(t, e));
      }
    },
    [refresh, onError, t],
  );

  const redo = useCallback(
    async (rec: Recording) => {
      try {
        // the take goes to the trash and its sentence comes up next (one server call, nothing half done)
        await api.redoRecording(rec.id);
        await refresh();
        onChanged();
      } catch (e) {
        onError(errorText(t, e));
      }
    },
    [refresh, onChanged, onError, t],
  );

  return { queue, approve, redo };
}
