import { useEffect, useState } from "react";
import { Button, Dialog, DialogActions, DialogContent, DialogTitle, List, ListItem, ListItemText, Typography } from "@mui/material";
import { api, type Paragraph } from "../api";
import { errorText, useI18n } from "../i18n";

type Props = { open: boolean; onClose: () => void; onQueued: (added: number) => void; onError: (message: string) => void };

/** Connected texts (a story, a forecast, a recipe) read sentence by sentence, in order. */
export function ParagraphsDialog({ open, onClose, onQueued, onError }: Props) {
  const { t } = useI18n();
  const [items, setItems] = useState<Paragraph[]>([]);

  useEffect(() => {
    if (open) api.paragraphs().then((r) => setItems(r.items)).catch(() => setItems([]));
  }, [open]);

  const queue = async (p: Paragraph) => {
    try {
      const res = await api.queueParagraph(p.id);
      onQueued(res.added);
      onClose();
    } catch (e) {
      onError(errorText(t, e));
    }
  };

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>{t("para.title")}</DialogTitle>
      <DialogContent>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
          {t("para.help")}
        </Typography>
        <List dense disablePadding>
          {items.map((p) => (
            <ListItem
              key={p.id}
              disableGutters
              secondaryAction={
                <Button size="small" variant={p.recorded >= p.sentences ? "text" : "outlined"} onClick={() => queue(p)} disabled={p.recorded >= p.sentences}>
                  {p.recorded >= p.sentences ? t("para.done") : t("para.read")}
                </Button>
              }
            >
              <ListItemText primary={p.title} secondary={`${t("para.count", { n: p.sentences, done: p.recorded })} · ${p.preview}`} secondaryTypographyProps={{ noWrap: true }} sx={{ pr: 12 }} />
            </ListItem>
          ))}
        </List>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{t("para.close")}</Button>
      </DialogActions>
    </Dialog>
  );
}
