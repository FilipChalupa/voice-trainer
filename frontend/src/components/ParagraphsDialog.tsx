import { useEffect, useState } from "react";
import { Accordion, AccordionDetails, AccordionSummary, Button, CircularProgress, Dialog, DialogActions, DialogContent, DialogTitle, IconButton, List, ListItem, ListItemText, Stack, TextField, Tooltip, Typography } from "@mui/material";
import DeleteIcon from "@mui/icons-material/Delete";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import { api, type Book, type Paragraph } from "../api";
import { errorText, useI18n } from "../i18n";

type Props = { open: boolean; onClose: () => void; onQueued: (added: number) => void; onError: (message: string) => void };
type Chapter = { page: string; title: string };

/** Connected texts read sentence by sentence: built-in paragraphs, public-domain books, any page or pasted text. */
export function ParagraphsDialog({ open, onClose, onQueued, onError }: Props) {
  const { t } = useI18n();
  const [items, setItems] = useState<Paragraph[]>([]);
  const [books, setBooks] = useState<Book[]>([]);
  const [chapters, setChapters] = useState<Record<string, Chapter[] | "loading">>({});
  const [source, setSource] = useState("");
  const [busy, setBusy] = useState(false);
  const [batches, setBatches] = useState<{ source: string; total: number; remaining: number }[]>([]);

  const loadBatches = () => api.customBatches().then((r) => setBatches(r.batches.filter((b) => b.remaining > 0))).catch(() => setBatches([]));
  useEffect(() => {
    if (!open) return;
    api.paragraphs().then((r) => setItems(r.items)).catch(() => setItems([]));
    api.library().then((r) => setBooks(r.items)).catch(() => setBooks([]));
    loadBatches();
  }, [open]);

  const removeBatch = async (src: string | null) => {
    setBusy(true);
    try {
      await api.removeCustom(src);
      await loadBatches();
      onQueued(0);
    } catch (e) {
      onError(errorText(t, e));
    } finally {
      setBusy(false);
    }
  };

  const run = async (fn: () => Promise<{ added: number }>) => {
    setBusy(true);
    try {
      const res = await fn();
      onQueued(res.added);
      onClose();
    } catch (e) {
      onError(errorText(t, e));
    } finally {
      setBusy(false);
    }
  };

  const loadChapters = (book: Book) => {
    if (chapters[book.id]) return;
    setChapters((c) => ({ ...c, [book.id]: "loading" }));
    api
      .book(book.id)
      .then((r) => setChapters((c) => ({ ...c, [book.id]: r.chapters })))
      .catch((e) => {
        setChapters((c) => ({ ...c, [book.id]: [] }));
        onError(errorText(t, e));
      });
  };

  const submitSource = () => {
    const value = source.trim();
    if (!value) return;
    run(() => api.queueText(/^https?:\/\//.test(value) ? { url: value } : { text: value }));
  };

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>{t("para.title")}</DialogTitle>
      <DialogContent>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
          {t("para.help")}
        </Typography>
        {batches.length > 0 && (
          <Stack spacing={0.5} sx={{ mb: 2, p: 1.5, border: 1, borderColor: "divider", borderRadius: 2 }}>
            <Stack direction="row" alignItems="center" spacing={1}>
              <Typography variant="subtitle2" sx={{ flex: 1 }}>
                {t("para.queued")}
              </Typography>
              <Button size="small" color="error" onClick={() => removeBatch(null)} disabled={busy}>
                {t("para.removeAll")}
              </Button>
            </Stack>
            {batches.map((b) => (
              <Stack key={b.source} direction="row" alignItems="center" spacing={1}>
                <Typography variant="body2" noWrap sx={{ flex: 1 }}>
                  {b.source || t("para.unnamed")}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  {t("para.remaining", { n: b.remaining })}
                </Typography>
                <Tooltip title={t("para.remove")}>
                  <IconButton size="small" onClick={() => removeBatch(b.source)} disabled={busy}>
                    <DeleteIcon fontSize="small" />
                  </IconButton>
                </Tooltip>
              </Stack>
            ))}
          </Stack>
        )}
        <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
          {t("para.totals", { n: items.reduce((a, p) => a + p.sentences, 0), done: items.reduce((a, p) => a + p.recorded, 0) })}
        </Typography>
        <List dense disablePadding>
          {[...items].sort((a, b) => Number(a.recorded >= a.sentences) - Number(b.recorded >= b.sentences)).map((p) => (
            <ListItem
              key={p.id}
              disableGutters
              secondaryAction={
                <Button size="small" variant={p.recorded >= p.sentences ? "text" : "outlined"} onClick={() => run(() => api.queueParagraph(p.id))} disabled={busy || p.recorded >= p.sentences}>
                  {p.recorded >= p.sentences ? t("para.done") : t("para.read")}
                </Button>
              }
            >
              <ListItemText primary={p.title} secondary={`${t("para.count", { n: p.sentences, done: p.recorded })} · ${p.preview}`} secondaryTypographyProps={{ noWrap: true }} sx={{ pr: 12 }} />
            </ListItem>
          ))}
        </List>

        {books.length > 0 && (
          <Stack spacing={1} sx={{ mt: 2 }}>
            <Typography variant="subtitle2">{t("para.library")}</Typography>
            <Typography variant="caption" color="text.secondary">
              {t("para.libraryHint")}
            </Typography>
            {books.map((book) => (
              <Accordion key={book.id} disableGutters variant="outlined" onChange={(_, expanded) => expanded && loadChapters(book)}>
                <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                  <Typography variant="body2">
                    <b>{book.title}</b> · {book.author}
                  </Typography>
                </AccordionSummary>
                <AccordionDetails sx={{ pt: 0 }}>
                  {chapters[book.id] === "loading" || !chapters[book.id] ? (
                    <CircularProgress size={20} />
                  ) : (
                    <List dense disablePadding>
                      {(chapters[book.id] as Chapter[]).map((ch) => (
                        <ListItem
                          key={ch.page}
                          disableGutters
                          secondaryAction={
                            <Button size="small" variant="outlined" onClick={() => run(() => api.queueText({ book: book.id, page: ch.page }))} disabled={busy}>
                              {t("para.read")}
                            </Button>
                          }
                        >
                          <ListItemText primary={ch.title} primaryTypographyProps={{ noWrap: true }} sx={{ pr: 10 }} />
                        </ListItem>
                      ))}
                    </List>
                  )}
                </AccordionDetails>
              </Accordion>
            ))}
          </Stack>
        )}

        <Stack spacing={1} sx={{ mt: 2 }}>
          <Typography variant="subtitle2">{t("para.own")}</Typography>
          <TextField value={source} onChange={(e) => setSource(e.target.value)} multiline minRows={2} maxRows={8} fullWidth size="small" placeholder={t("para.ownPlaceholder")} />
          <Button variant="contained" onClick={submitSource} disabled={busy || !source.trim()} sx={{ alignSelf: "flex-start" }}>
            {t("para.ownRead")}
          </Button>
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{t("para.close")}</Button>
      </DialogActions>
    </Dialog>
  );
}
