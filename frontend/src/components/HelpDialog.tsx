import { Dialog, DialogActions, DialogContent, DialogTitle, Button, List, ListItem, ListItemText } from "@mui/material";
import { useI18n, type TKey } from "../i18n";

const TERMS = ["consent", "corpus", "epoch", "validation", "mel", "mos", "checkpoint", "variants", "patience", "onnx", "wyoming", "lexicon"] as const;

/** Short explanations of the terms used across the app, in one place. */
export function HelpDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useI18n();
  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm" scroll="paper">
      <DialogTitle>{t("help.title")}</DialogTitle>
      <DialogContent dividers>
        <List dense disablePadding>
          {TERMS.map((term) => (
            <ListItem key={term} disableGutters alignItems="flex-start">
              <ListItemText primary={t(`help.${term}.term` as TKey)} secondary={t(`help.${term}.text` as TKey)} primaryTypographyProps={{ fontWeight: 600 }} />
            </ListItem>
          ))}
        </List>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{t("help.close")}</Button>
      </DialogActions>
    </Dialog>
  );
}
