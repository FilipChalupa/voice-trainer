import { useState } from "react";
import { Box } from "@mui/material";
import { formatTime } from "../lib/audio";

type Props = {
  /** seconds, for the time shown above the pointer */
  duration: number;
  /** a click or a drag landed at this point of the sound (0..1) */
  onSeek: (ratio: number) => void;
  children: React.ReactNode;
  sx?: object;
  ariaLabel?: string;
  ariaValueNow?: number;
};

const ratioOf = (e: React.PointerEvent<HTMLElement>) => {
  const rect = e.currentTarget.getBoundingClientRect();
  return Math.min(1, Math.max(0, (e.clientX - rect.left) / Math.max(1, rect.width)));
};

/** The behaviour of a player's progress bar for any waveform: click to jump, hold and drag to scrub, and the
 *  time under the pointer while hovering. */
export function Scrub({ duration, onSeek, children, sx, ariaLabel, ariaValueNow }: Props) {
  const [hover, setHover] = useState<number | null>(null);
  const [dragging, setDragging] = useState(false);
  return (
    <Box
      role="slider"
      aria-label={ariaLabel}
      aria-valuenow={ariaValueNow}
      sx={{ position: "relative", cursor: dragging ? "grabbing" : "pointer", touchAction: "none", userSelect: "none", ...sx }}
      onPointerDown={(e) => {
        if (e.button !== 0) return;
        e.currentTarget.setPointerCapture(e.pointerId);
        setDragging(true);
        onSeek(ratioOf(e));
      }}
      onPointerMove={(e) => {
        const ratio = ratioOf(e);
        setHover(ratio);
        if (dragging) onSeek(ratio);
      }}
      onPointerUp={(e) => {
        if (dragging) onSeek(ratioOf(e));
        setDragging(false);
      }}
      onPointerCancel={() => setDragging(false)}
      onPointerLeave={() => setHover(null)}
    >
      {children}
      {hover !== null && duration > 0 && (
        <Box sx={{ position: "absolute", bottom: "100%", left: `${hover * 100}%`, transform: "translate(-50%, -2px)", px: 0.5, borderRadius: 0.5, bgcolor: "background.paper", border: 1, borderColor: "divider", fontSize: 11, lineHeight: 1.6, pointerEvents: "none", whiteSpace: "nowrap", zIndex: 1 }}>
          {formatTime(hover * duration)}
        </Box>
      )}
    </Box>
  );
}
