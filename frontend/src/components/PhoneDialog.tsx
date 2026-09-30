import { useEffect, useState } from "react";
import { Alert, Box, Button, Dialog, DialogActions, DialogContent, DialogTitle, Link, Stack, TextField, Typography } from "@mui/material";
import { api } from "../api";
import { useI18n } from "../i18n";

type Props = { open: boolean; onClose: () => void };
const STORAGE_KEY = "voice-trainer.phone-host";

/** QR code with the HTTPS address of this app, so a phone in the same network can be used as the microphone. */
export function PhoneDialog({ open, onClose }: Props) {
  const { t } = useI18n();
  const [host, setHost] = useState("");
  const [port, setPort] = useState(8444);
  const [https, setHttps] = useState(true);
  const [qr, setQr] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    api
      .system()
      .then((s) => {
        setHttps(s.https);
        setPort(s.public_https_port);
        let stored = "";
        try {
          stored = localStorage.getItem(STORAGE_KEY) ?? "";
        } catch {
          stored = "";
        }
        const fromBrowser = ["localhost", "127.0.0.1"].includes(location.hostname) ? "" : location.hostname;
        setHost(stored || s.public_host || fromBrowser);
      })
      .catch(() => undefined);
  }, [open]);

  const link = host ? `https://${host}:${port}/#record` : "";

  useEffect(() => {
    if (!link) {
      setQr(null);
      return;
    }
    try {
      localStorage.setItem(STORAGE_KEY, host);
    } catch {
      /* private mode */
    }
    import("qrcode")
      .then((QRCode) => QRCode.toDataURL(link, { width: 220, margin: 1 }))
      .then(setQr)
      .catch(() => setQr(null));
  }, [link, host]);

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>{t("phone.title")}</DialogTitle>
      <DialogContent>
        <Stack spacing={2}>
          <Typography variant="body2" color="text.secondary">
            {t("phone.help")}
          </Typography>
          {!https && <Alert severity="warning">{t("phone.noHttps")}</Alert>}
          <TextField label={t("phone.host")} value={host} onChange={(e) => setHost(e.target.value.trim())} helperText={t("phone.hostHint")} size="small" fullWidth />
          {link && (
            <Stack direction={{ xs: "column", sm: "row" }} spacing={2} alignItems="center">
              {qr && <Box component="img" src={qr} alt="QR" sx={{ width: 220, height: 220, borderRadius: 1, bgcolor: "#fff" }} />}
              <Stack spacing={1}>
                <Link href={link} target="_blank" rel="noopener" sx={{ wordBreak: "break-all" }}>
                  {link}
                </Link>
                <Typography variant="caption" color="text.secondary">
                  {t("phone.warning")}
                </Typography>
              </Stack>
            </Stack>
          )}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{t("phone.close")}</Button>
      </DialogActions>
    </Dialog>
  );
}
