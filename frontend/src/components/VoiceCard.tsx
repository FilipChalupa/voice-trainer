import { useEffect, useRef, useState } from "react";
import { Alert, Box, Button, Card, CardContent, CardHeader, Chip, Dialog, DialogActions, DialogContent, DialogTitle, Divider, IconButton, LinearProgress, MenuItem, Stack, TextField, Tooltip, Typography } from "@mui/material";
import PersonIcon from "@mui/icons-material/Person";
import AddIcon from "@mui/icons-material/Add";
import DeleteIcon from "@mui/icons-material/Delete";
import MicIcon from "@mui/icons-material/Mic";
import StopIcon from "@mui/icons-material/Stop";
import VerifiedUserIcon from "@mui/icons-material/VerifiedUser";
import SaveIcon from "@mui/icons-material/Save";
import DownloadIcon from "@mui/icons-material/Download";
import UploadIcon from "@mui/icons-material/Upload";
import { api, type VoicesPayload } from "../api";
import { errorText, useI18n } from "../i18n";
import { AudioPlayer } from "./AudioPlayer";
import { Recorder } from "../lib/recorder";

type Props = { payload: VoicesPayload; disabled: boolean; onChange: (p: VoicesPayload) => void; onError: (m: string) => void };

/** Voice selection/creation, owner and the spoken consent that gates training. */
export function VoiceCard({ payload, disabled, onChange, onError }: Props) {
  const { t } = useI18n();
  const voice = payload.voice;
  const [dialog, setDialog] = useState(payload.voices.length === 0);
  const [newName, setNewName] = useState("");
  const [newOwner, setNewOwner] = useState("");
  const [newLanguage, setNewLanguage] = useState(payload.languages[0]?.id ?? "cs");
  const [name, setName] = useState(voice?.name ?? "");
  const [owner, setOwner] = useState(voice?.owner ?? "");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const restoreRef = useRef<HTMLInputElement | null>(null);
  const [recording, setRecording] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [level, setLevel] = useState(0);
  const recorderRef = useRef(new Recorder());
  const stopRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    setName(voice?.name ?? "");
    setOwner(voice?.owner ?? "");
  }, [voice?.id, voice?.name, voice?.owner]);

  useEffect(() => {
    const recorder = recorderRef.current;
    return () => recorder.close();
  }, []);

  const run = async (fn: () => Promise<VoicesPayload>) => {
    setBusy(true);
    try {
      onChange(await fn());
      return true;
    } catch (e) {
      onError(errorText(t, e));
      return false;
    } finally {
      setBusy(false);
    }
  };

  const create = async () => {
    if (await run(() => api.createVoice(newName.trim(), newOwner.trim(), newLanguage))) {
      setDialog(false);
      setNewName("");
      setNewOwner("");
    }
  };

  const remove = () => {
    if (!voice || !window.confirm(t("voice.deleteConfirm", { name: voice.name }))) return;
    run(() => api.deleteVoice(voice.id));
  };

  const recordConsent = async () => {
    if (recording) {
      stopRef.current?.();
      return;
    }
    setRecording(true);
    setElapsed(0);
    try {
      const { wav } = await recorderRef.current.record(
        30,
        ({ rms, elapsed: e }) => {
          setLevel(Math.min(1, rms * 6));
          setElapsed(e);
        },
        { silenceMs: 1500, minSeconds: 2.5, onStart: (stop) => (stopRef.current = stop) },
      );
      await run(() => api.uploadConsent(wav));
    } catch (e) {
      onError(errorText(t, e));
    } finally {
      stopRef.current = null;
      setRecording(false);
      setLevel(0);
    }
  };

  const language = payload.languages.find((l) => l.id === voice?.language);
  const dirty = !!voice && (name !== voice.name || owner !== voice.owner);

  return (
    <Card>
      <CardHeader
        avatar={<PersonIcon color="primary" />}
        title={t("voice.title")}
        subheader={t("voice.subtitle")}
        action={
          <Stack direction="row" spacing={0.5} alignItems="center" flexWrap="wrap" useFlexGap>
            {voice && (
              <Tooltip title={t("voice.backupHint")}>
                <Button startIcon={<DownloadIcon />} href={api.backupUrl} download disabled={disabled || busy}>
                  {t("voice.backup")}
                </Button>
              </Tooltip>
            )}
            <Tooltip title={t("voice.restoreHint")}>
              <span>
                <Button startIcon={<UploadIcon />} onClick={() => restoreRef.current?.click()} disabled={disabled || busy}>
                  {t("voice.restore")}
                </Button>
              </span>
            </Tooltip>
            <input
              ref={restoreRef}
              type="file"
              accept=".zip,application/zip"
              hidden
              onChange={(e) => {
                const file = e.target.files?.[0];
                e.target.value = "";
                if (!file) return;
                run(async () => {
                  const res = await api.restoreBackup(file);
                  setNotice(t("voice.restored", { name: res.name, files: res.files }));
                  return api.voices();
                });
              }}
            />
            <Button startIcon={<AddIcon />} onClick={() => setDialog(true)} disabled={disabled || busy}>
              {t("voice.new")}
            </Button>
          </Stack>
        }
      />
      <CardContent>
        {notice && (
          <Alert severity="success" onClose={() => setNotice(null)} sx={{ mb: 2 }}>
            {notice}
          </Alert>
        )}
        {!voice ? (
          <Alert severity="info">{t("voice.empty")}</Alert>
        ) : (
          <Stack spacing={2}>
            <Stack direction={{ xs: "column", sm: "row" }} spacing={2} alignItems={{ sm: "center" }}>
              <TextField select label={t("voice.select")} value={voice.id} onChange={(e) => run(() => api.selectVoice(e.target.value))} disabled={disabled || busy} sx={{ minWidth: 260 }}>
                {payload.voices.map((v) => (
                  <MenuItem key={v.id} value={v.id}>
                    <Stack>
                      <Typography variant="body2">
                        {v.name} · {v.owner}
                      </Typography>
                      <Typography variant="caption" color="text.secondary">
                        {t("voice.summary", { recordings: v.recordings, jobs: v.jobs })}
                      </Typography>
                    </Stack>
                  </MenuItem>
                ))}
              </TextField>
              <Chip label={language?.label ?? voice.language} variant="outlined" />
              <Box sx={{ flex: 1 }} />
              <Tooltip title={t("voice.delete")}>
                <span>
                  <IconButton onClick={remove} disabled={disabled || busy}>
                    <DeleteIcon />
                  </IconButton>
                </span>
              </Tooltip>
            </Stack>

            <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
              <TextField label={t("voice.name")} value={name} onChange={(e) => setName(e.target.value)} helperText={t("voice.nameHelp")} fullWidth disabled={disabled} />
              <TextField label={t("voice.owner")} value={owner} onChange={(e) => setOwner(e.target.value)} helperText={t("voice.ownerHelp")} fullWidth disabled={disabled} />
            </Stack>
            <Stack direction="row" spacing={2} alignItems="center">
              <Button variant="contained" startIcon={<SaveIcon />} onClick={() => run(() => api.saveVoice({ name, owner }))} disabled={disabled || busy || !dirty || !name.trim() || !owner.trim()}>
                {t("voice.save")}
              </Button>
              <Typography variant="body2" color="text.secondary">
                {dirty ? t("voice.unsaved") : t("voice.saved")}
              </Typography>
            </Stack>
            {language && (
              <Typography variant="caption" color="text.secondary">
                {t("voice.base", { name: language.base.name, license: language.base.license })}
              </Typography>
            )}

            <Divider />
            <Box>
              <Stack direction="row" spacing={1} alignItems="center">
                <VerifiedUserIcon fontSize="small" color={voice.has_consent ? "success" : "warning"} />
                <Typography variant="subtitle2">{t("consent.title")}</Typography>
              </Stack>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5, mb: 1.5 }}>
                {t("consent.help")}
              </Typography>
              <Box sx={{ p: 2, border: 1, borderColor: "divider", borderRadius: 2, mb: 1.5 }}>
                <Typography variant="caption" color="text.secondary">
                  {t("consent.statement")}
                </Typography>
                <Typography variant="h6">„{voice.consent_statement}“</Typography>
              </Box>
              {recording && <LinearProgress variant="determinate" value={level * 100} color="success" sx={{ height: 8, borderRadius: 4, mb: 1 }} />}
              <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
                <Button variant={voice.has_consent ? "outlined" : "contained"} color={recording ? "error" : "primary"} startIcon={recording ? <StopIcon /> : <MicIcon />} onClick={recordConsent} disabled={disabled || busy || !voice.owner || dirty}>
                  {recording ? t("consent.recording", { s: elapsed.toFixed(1) }) : voice.has_consent ? t("consent.recordAgain") : t("consent.record")}
                </Button>
                {voice.has_consent && (
                  <>
                    <Button color="error" onClick={() => run(() => api.deleteConsent())} disabled={disabled || busy}>
                      {t("consent.delete")}
                    </Button>
                  </>
                )}
              </Stack>
              {voice.has_consent && voice.consent && (
                <Box sx={{ mt: 1.5 }}>
                  <AudioPlayer src={`/api/consent/audio?ts=${voice.consent.at}`} dense label={t("consent.play")} />
                </Box>
              )}
              <Typography variant="body2" sx={{ mt: 1 }} color={voice.has_consent ? "success.main" : "warning.main"}>
                {voice.has_consent && voice.consent
                  ? t("consent.recorded", { owner: voice.consent.owner, date: new Date(voice.consent.at).toLocaleString() })
                  : !voice.owner || dirty
                    ? t("consent.ownerFirst")
                    : t("consent.missing")}
              </Typography>
            </Box>
          </Stack>
        )}
      </CardContent>

      <Dialog open={dialog} onClose={() => setDialog(false)} fullWidth maxWidth="xs">
        <DialogTitle>{t("voice.new")}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <TextField autoFocus label={t("voice.name")} value={newName} onChange={(e) => setNewName(e.target.value)} helperText={t("voice.nameHelp")} />
            <TextField label={t("voice.owner")} value={newOwner} onChange={(e) => setNewOwner(e.target.value)} helperText={t("voice.ownerHelp")} />
            <TextField select label={t("voice.language")} value={newLanguage} onChange={(e) => setNewLanguage(e.target.value)}>
              {payload.languages.map((l) => (
                <MenuItem key={l.id} value={l.id}>
                  {l.label}
                </MenuItem>
              ))}
            </TextField>
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDialog(false)}>{t("voice.cancel")}</Button>
          <Button variant="contained" onClick={create} disabled={busy || !newName.trim() || !newOwner.trim()}>
            {t("voice.create")}
          </Button>
        </DialogActions>
      </Dialog>
    </Card>
  );
}
