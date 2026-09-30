import { Box, Typography, useTheme } from "@mui/material";
import { LineChart } from "@mui/x-charts/LineChart";
import type { ValidationEntry } from "../api";
import { useI18n } from "../i18n";

/** Validation mel loss and estimated MOS over epochs – two measures of different scale, so two charts. */
export function TrainingCharts({ validation }: { validation: ValidationEntry[] }) {
  const { t } = useI18n();
  const theme = useTheme();
  const epochs = validation.map((v) => v.epoch);
  const hasMos = validation.some((v) => v.val_mos !== null);
  const common = { height: 200, margin: { left: 8, right: 16, top: 16, bottom: 8 }, grid: { horizontal: true } as const, hideLegend: true };
  return (
    <Box sx={{ display: "grid", gap: 2, gridTemplateColumns: { xs: "1fr", md: hasMos ? "1fr 1fr" : "1fr" } }}>
      <Box>
        <Typography variant="subtitle2">{t("charts.valMel")}</Typography>
        <LineChart
          {...common}
          colors={[theme.palette.primary.main]}
          xAxis={[{ data: epochs, label: t("charts.epochAxis"), valueFormatter: (v: number) => String(v) }]}
          series={[{ data: validation.map((v) => v.val_mel), label: t("charts.valMel"), showMark: validation.length < 40, curve: "monotoneX" }]}
        />
      </Box>
      {hasMos && (
        <Box>
          <Typography variant="subtitle2">{t("charts.valMos")}</Typography>
          <LineChart
            {...common}
            colors={[theme.palette.secondary.main]}
            xAxis={[{ data: epochs, label: t("charts.epochAxis"), valueFormatter: (v: number) => String(v) }]}
            yAxis={[{ min: 1, max: 5 }]}
            series={[{ data: validation.map((v) => v.val_mos), label: t("charts.valMos"), showMark: validation.length < 40, curve: "monotoneX" }]}
          />
        </Box>
      )}
    </Box>
  );
}
