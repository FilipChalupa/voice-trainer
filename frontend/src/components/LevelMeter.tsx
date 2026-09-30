import { useEffect, useRef, useState } from "react";
import { Box, Typography } from "@mui/material";
import { useI18n } from "../i18n";

type Props = { level: number; peak?: number; height?: number };

/** Input level as a fixed green-amber-red scale that fills from the left, with a peak-hold marker.
 *  The colours stay put, only the fill moves, so loud speech does not flash. */
export function LevelMeter({ level, peak = 0, height = 10 }: Props) {
  const { t } = useI18n();
  const [hold, setHold] = useState(0);
  const [clipped, setClipped] = useState(false);
  const holdTimer = useRef<number | null>(null);
  const clipTimer = useRef<number | null>(null);

  useEffect(() => {
    if (level >= hold) {
      setHold(level);
      if (holdTimer.current) window.clearTimeout(holdTimer.current);
      holdTimer.current = window.setTimeout(() => setHold(0), 900);
    }
  }, [level, hold]);

  useEffect(() => {
    if (peak >= 0.98) {
      setClipped(true);
      if (clipTimer.current) window.clearTimeout(clipTimer.current);
      clipTimer.current = window.setTimeout(() => setClipped(false), 1500);
    }
  }, [peak]);

  useEffect(
    () => () => {
      if (holdTimer.current) window.clearTimeout(holdTimer.current);
      if (clipTimer.current) window.clearTimeout(clipTimer.current);
    },
    [],
  );

  const pct = Math.min(100, Math.max(0, level * 100));
  return (
    <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
      <Box sx={{ position: "relative", flex: 1, height, borderRadius: height / 2, overflow: "hidden", bgcolor: "action.hover" }}>
        <Box
          sx={{
            position: "absolute",
            inset: 0,
            background: "linear-gradient(90deg, #2e7d32 0%, #66bb6a 55%, #ffb300 75%, #f4511e 88%, #d32f2f 100%)",
            clipPath: `inset(0 ${100 - pct}% 0 0)`,
            transition: "clip-path 60ms linear",
          }}
        />
        {hold > 0.02 && <Box sx={{ position: "absolute", top: 0, bottom: 0, left: `calc(${Math.min(100, hold * 100)}% - 2px)`, width: 2, bgcolor: "text.primary", opacity: 0.7 }} />}
      </Box>
      <Typography variant="caption" sx={{ minWidth: 44, textAlign: "right", color: clipped ? "error.main" : "text.secondary", fontWeight: clipped ? 700 : 400 }}>
        {clipped ? t("meter.clip") : `${Math.round(pct)} %`}
      </Typography>
    </Box>
  );
}
