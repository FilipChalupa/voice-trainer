import { useEffect, useState } from "react";
import { Button, Card, CardContent, CardHeader, IconButton, Stack, Table, TableBody, TableCell, TableHead, TableRow, TextField, Typography } from "@mui/material";
import SpellcheckIcon from "@mui/icons-material/Spellcheck";
import DeleteIcon from "@mui/icons-material/Delete";
import AddIcon from "@mui/icons-material/Add";
import { api, type VoiceSettings, type VoicesPayload } from "../api";
import { errorText, useI18n } from "../i18n";

type Props = { voice: VoiceSettings; onVoices: (p: VoicesPayload) => void; onError: (message: string) => void };

/** Respellings for words espeak reads wrong (names, brands, abbreviations); applied when this app speaks. */
export function LexiconCard({ voice, onVoices, onError }: Props) {
  const { t } = useI18n();
  const [entries, setEntries] = useState<[string, string][]>(Object.entries(voice.lexicon ?? {}));
  const [word, setWord] = useState("");
  const [spoken, setSpoken] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => setEntries(Object.entries(voice.lexicon ?? {})), [voice.id, voice.lexicon]);

  const save = async (next: [string, string][]) => {
    setBusy(true);
    try {
      onVoices(await api.saveVoice({ lexicon: Object.fromEntries(next) }));
      setEntries(next);
    } catch (e) {
      onError(errorText(t, e));
    } finally {
      setBusy(false);
    }
  };

  const add = () => {
    const w = word.trim();
    const s = spoken.trim();
    if (!w || !s) return;
    save([...entries.filter(([k]) => k.toLowerCase() !== w.toLowerCase()), [w, s]]);
    setWord("");
    setSpoken("");
  };

  return (
    <Card>
      <CardHeader avatar={<SpellcheckIcon color="primary" />} title={t("lex.title")} subheader={t("lex.subtitle")} />
      <CardContent>
        <Stack spacing={2}>
          <Typography variant="body2" color="text.secondary">
            {t("lex.help")}
          </Typography>
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ sm: "flex-start" }}>
            <TextField size="small" label={t("lex.word")} value={word} onChange={(e) => setWord(e.target.value)} sx={{ flex: 1 }} />
            <TextField
              size="small"
              label={t("lex.spoken")}
              value={spoken}
              onChange={(e) => setSpoken(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && add()}
              helperText={t("lex.spokenHint")}
              sx={{ flex: 2 }}
            />
            <Button variant="outlined" startIcon={<AddIcon />} onClick={add} disabled={busy || !word.trim() || !spoken.trim()}>
              {t("lex.add")}
            </Button>
          </Stack>
          {entries.length > 0 && (
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>{t("lex.word")}</TableCell>
                  <TableCell>{t("lex.spoken")}</TableCell>
                  <TableCell />
                </TableRow>
              </TableHead>
              <TableBody>
                {entries.map(([k, v]) => (
                  <TableRow key={k} hover>
                    <TableCell>{k}</TableCell>
                    <TableCell>{v}</TableCell>
                    <TableCell align="right">
                      <IconButton size="small" onClick={() => save(entries.filter(([kk]) => kk !== k))} disabled={busy}>
                        <DeleteIcon fontSize="small" />
                      </IconButton>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </Stack>
      </CardContent>
    </Card>
  );
}
