import { useState } from "react";
import { Box, Chip, IconButton, ListItemIcon, ListItemText, Menu, MenuItem, Stack, Table, TableBody, TableCell, TableHead, TableRow, Tooltip, Typography } from "@mui/material";
import DownloadIcon from "@mui/icons-material/Download";
import DeleteIcon from "@mui/icons-material/Delete";
import FactCheckIcon from "@mui/icons-material/FactCheck";
import HearingIcon from "@mui/icons-material/Hearing";
import MoreVertIcon from "@mui/icons-material/MoreVert";
import CloudDoneIcon from "@mui/icons-material/CloudDone";
import { CheckDialog } from "./CheckDialog";
import { IntelligibilityDialog } from "./IntelligibilityDialog";
import { NextSteps } from "./NextSteps";
import { api, type Job } from "../api";
import { errorText, useI18n, type TKey } from "../i18n";

type Props = { jobs: Job[]; liveEpoch: number; disabled: boolean; onChanged: () => void; onError: (message: string) => void; onGo: (tab: "test") => void };

const COLORS: Record<string, "success" | "error" | "warning" | "info" | "default"> = { done: "success", failed: "error", cancelled: "warning", running: "info", interrupted: "warning" };
const STATUSES = new Set(["done", "failed", "cancelled", "running", "interrupted"]);

export function JobsCard({ jobs, liveEpoch, disabled, onChanged, onError, onGo }: Props) {
  const { t } = useI18n();
  const [checking, setChecking] = useState<Job | null>(null);
  const [testing, setTesting] = useState<Job | null>(null);
  const [menu, setMenu] = useState<{ job: Job; anchor: HTMLElement } | null>(null);
  const remove = async (id: string) => {
    try {
      await api.deleteJob(id);
      onChanged();
    } catch (e) {
      onError(errorText(t, e));
    }
  };
  // the newest finished run with a voice: the one to listen to, test and deploy next
  const latest = jobs.find((j) => j.status === "done" && j.exports.length > 0);

  return (
    <Box sx={{ px: 1, pb: 1 }}>
      {latest && (
        <Box sx={{ p: 1 }}>
          <NextSteps job={latest} onListen={() => onGo("test")} onTest={() => setTesting(latest)} onCheck={() => setChecking(latest)} onCompare={() => onGo("test")} onDeploy={() => onGo("test")} />
        </Box>
      )}
      {jobs.length === 0 ? (
        <Typography color="text.secondary" sx={{ p: 1 }}>
          {t("jobs.empty")}
        </Typography>
      ) : (
        <Box sx={{ overflowX: "auto" }}>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>{t("jobs.started")}</TableCell>
                <TableCell>{t("jobs.status")}</TableCell>
                <TableCell>{t("jobs.data")}</TableCell>
                <TableCell>{t("jobs.epochs")}</TableCell>
                <TableCell>{t("jobs.quality")}</TableCell>
                <TableCell />
              </TableRow>
            </TableHead>
            <TableBody>
              {jobs.map((job) => (
                <TableRow key={job.job_id} hover>
                  <TableCell sx={{ whiteSpace: "nowrap" }}>{new Date(job.created_at).toLocaleString()}</TableCell>
                  <TableCell>
                    <Stack direction="row" spacing={0.5} alignItems="center" flexWrap="wrap" useFlexGap>
                      <Chip size="small" label={t((STATUSES.has(job.status) ? `jobs.s.${job.status}` : "jobs.s.failed") as TKey)} color={COLORS[job.status] ?? "default"} />
                      {job.deployed && (
                        <Tooltip title={t("jobs.deployedHint", { host: job.deployed.host, when: new Date(job.deployed.at).toLocaleString() })}>
                          <Chip size="small" color="primary" variant="outlined" icon={<CloudDoneIcon />} label={t("jobs.deployed")} />
                        </Tooltip>
                      )}
                    </Stack>
                  </TableCell>
                  <TableCell>
                    {t("jobs.dataValue", { minutes: job.minutes?.toFixed(1) ?? "–", recordings: job.recordings ?? "–" })}
                    {job.processing && (
                      <Tooltip title={`${job.processing.highpass_hz ? `${job.processing.highpass_hz} Hz · ` : ""}${job.processing.bass_db} dB / ${job.processing.bass_hz} Hz · ${job.processing.treble_db} dB / ${job.processing.treble_hz} Hz`}>
                        <Chip size="small" variant="outlined" label={t("jobs.processed")} sx={{ ml: 1 }} />
                      </Tooltip>
                    )}
                  </TableCell>
                  <TableCell sx={{ whiteSpace: "nowrap" }}>
                    {job.status === "running" ? liveEpoch : (job.epoch ?? 0)} / {job.max_epochs}
                  </TableCell>
                  <TableCell sx={{ whiteSpace: "nowrap" }}>
                    <Tooltip title={t("jobs.qualityHint")}>
                      <span>
                        {job.validation_last?.val_mos != null ? `MOS ${job.validation_last.val_mos.toFixed(2)}` : "–"}
                        {job.intelligibility != null ? ` · ${job.intelligibility.toFixed(1)} %` : ""}
                      </span>
                    </Tooltip>
                  </TableCell>
                  <TableCell align="right">
                    <IconButton size="small" onClick={(e) => setMenu({ job, anchor: e.currentTarget })} aria-label={t("jobs.actions")}>
                      <MoreVertIcon />
                    </IconButton>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Box>
      )}
      <Menu open={!!menu} anchorEl={menu?.anchor} onClose={() => setMenu(null)}>
        {menu?.job.exports.length ? (
          <MenuItem
            onClick={() => {
              setTesting(menu.job);
              setMenu(null);
            }}
          >
            <ListItemIcon>
              <HearingIcon fontSize="small" />
            </ListItemIcon>
            <ListItemText>{t("jobs.intelligibilityTooltip")}</ListItemText>
          </MenuItem>
        ) : null}
        {menu?.job.exports.length ? (
          <MenuItem
            onClick={() => {
              setChecking(menu.job);
              setMenu(null);
            }}
          >
            <ListItemIcon>
              <FactCheckIcon fontSize="small" />
            </ListItemIcon>
            <ListItemText>{t("jobs.checkTooltip")}</ListItemText>
          </MenuItem>
        ) : null}
        {menu?.job.bundle_url ? (
          <MenuItem component="a" href={menu.job.bundle_url} download onClick={() => setMenu(null)}>
            <ListItemIcon>
              <DownloadIcon fontSize="small" />
            </ListItemIcon>
            <ListItemText>{t("jobs.downloadZip")}</ListItemText>
          </MenuItem>
        ) : null}
        <MenuItem
          disabled={disabled || menu?.job.status === "running"}
          onClick={() => {
            if (menu) remove(menu.job.job_id);
            setMenu(null);
          }}
        >
          <ListItemIcon>
            <DeleteIcon fontSize="small" />
          </ListItemIcon>
          <ListItemText>{t("jobs.deleteTooltip")}</ListItemText>
        </MenuItem>
      </Menu>
      <CheckDialog job={checking} onClose={() => setChecking(null)} onError={onError} />
      <IntelligibilityDialog job={testing} onClose={() => setTesting(null)} onChanged={onChanged} onError={onError} />
    </Box>
  );
}
