import { useEffect, useState } from "react";
import { Alert, Box, Button, Collapse, MenuItem, Stack, TextField, Typography } from "@mui/material";
import CloudUploadIcon from "@mui/icons-material/CloudUpload";
import { api, type DeployInfo, type DeploySettings, type Job } from "../api";
import { errorText, useI18n, type TKey } from "../i18n";

const VARIANTS = new Set(["last", "best_mos", "best_mel"]);
type Outcome = { ok: boolean; output: string; files?: string[] };

/** Sends the voice (and the pronunciation dictionary) to the machine Piper runs on and restarts Piper there. */
export function ServerDeploy({ job, onError }: { job: Job; onError: (message: string) => void }) {
  const { t } = useI18n();
  const [info, setInfo] = useState<DeployInfo | null>(null);
  const [draft, setDraft] = useState<DeploySettings | null>(null);
  const [editing, setEditing] = useState(false);
  const [file, setFile] = useState("");
  const [busy, setBusy] = useState<"test" | "deploy" | "save" | null>(null);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    api
      .deploy()
      .then((d) => {
        setInfo(d);
        setDraft(d.settings);
        setEditing(!d.configured);
      })
      .catch(() => setInfo(null));
  }, []);
  if (!info || !draft) return null;

  const chosen = job.exports.find((e) => e.file === file) ?? job.exports.find((e) => e.variant === (job.stopped_early ? "best_mel" : "last")) ?? job.exports[0];
  const run = async (kind: "test" | "deploy" | "save", action: () => Promise<Outcome | null>) => {
    setBusy(kind);
    setOutcome(null);
    try {
      setOutcome(await action());
    } catch (e) {
      onError(errorText(t, e));
    } finally {
      setBusy(null);
    }
  };
  const save = () =>
    run("save", async () => {
      const next = await api.saveDeploy(draft);
      setInfo(next);
      setDraft(next.settings);
      return null;
    });
  const field = (key: keyof DeploySettings, width: number, type: "text" | "number" = "text") => (
    <TextField
      size="small"
      type={type}
      label={t(`deploy.f.${key}` as TKey)}
      value={draft[key]}
      onChange={(e) => setDraft({ ...draft, [key]: type === "number" ? Number(e.target.value) : e.target.value })}
      sx={{ flex: width, minWidth: 120 }}
    />
  );
  const unsaved = JSON.stringify(draft) !== JSON.stringify(info.settings);

  return (
    <Box>
      <Typography variant="subtitle2" gutterBottom>
        {t("deploy.serverTitle")}
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
        {t("deploy.serverHelp")}
      </Typography>
      {info.configured && (
        <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap sx={{ mb: 1 }}>
          {job.exports.length > 1 && (
            <TextField select size="small" label={t("test.variant")} value={chosen.file} onChange={(e) => setFile(e.target.value)} sx={{ minWidth: 200 }}>
              {job.exports.map((e) => (
                <MenuItem key={e.file} value={e.file}>
                  {VARIANTS.has(e.variant) ? t(`test.variant.${e.variant}` as TKey) : e.variant}
                </MenuItem>
              ))}
            </TextField>
          )}
          <Button variant="contained" startIcon={<CloudUploadIcon />} disabled={busy !== null || unsaved} onClick={() => run("deploy", () => api.deployJob(job.job_id, chosen.file))}>
            {busy === "deploy" ? t("deploy.deploying") : t("deploy.deploy", { host: info.settings.host })}
          </Button>
          <Button disabled={busy !== null || unsaved} onClick={() => run("test", () => api.testDeploy())}>
            {t("deploy.test")}
          </Button>
          <Button onClick={() => setEditing((v) => !v)}>{editing ? t("deploy.hideSettings") : t("deploy.settings")}</Button>
        </Stack>
      )}
      {outcome && (
        <Alert severity={outcome.ok ? "success" : "error"} variant="outlined" sx={{ mb: 1 }}>
          {outcome.ok ? (outcome.files ? t("deploy.done", { files: outcome.files.join(", ") }) : t("deploy.testOk")) : t("deploy.failed")}
          {outcome.output && (
            <Box component="pre" sx={{ m: 0, mt: 0.5, fontSize: 12, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
              {outcome.output}
            </Box>
          )}
        </Alert>
      )}
      <Collapse in={editing}>
        <Stack spacing={1.5} sx={{ mt: 1 }}>
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
            {field("host", 3)}
            {field("user", 1)}
            {field("port", 1, "number")}
          </Stack>
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
            {field("directory", 2)}
            {field("restart", 3)}
          </Stack>
          <Stack direction="row" spacing={1} alignItems="center">
            <Button variant="outlined" onClick={save} disabled={busy !== null || !unsaved || !draft.host.trim()}>
              {t("deploy.save")}
            </Button>
            <Typography variant="caption" color="text.secondary">
              {t("deploy.settingsHint")}
            </Typography>
          </Stack>
          {info.configured && !unsaved && (
            <Box>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 0.5 }}>
                {t("deploy.setupHelp", { user: info.settings.user, host: info.settings.host })}
              </Typography>
              <Box component="pre" sx={{ m: 0, p: 1, bgcolor: "action.hover", borderRadius: 1, fontSize: 11, maxHeight: 220, overflow: "auto" }} data-testid="deploy-setup">
                {info.setup}
              </Box>
              <Button
                size="small"
                sx={{ mt: 0.5 }}
                onClick={() => {
                  navigator.clipboard?.writeText(info.setup).then(
                    () => setCopied(true),
                    () => undefined,
                  );
                  setTimeout(() => setCopied(false), 1500);
                }}
              >
                {copied ? t("test.copied") : t("test.copy")}
              </Button>
            </Box>
          )}
        </Stack>
      </Collapse>
    </Box>
  );
}
