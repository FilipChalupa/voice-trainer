import { Button, Card, CardContent, Stack, Typography } from "@mui/material";
import ArrowForwardIcon from "@mui/icons-material/ArrowForward";

type Props = { icon: React.ReactNode; title: string; text: string; action?: { label: string; onClick: () => void } };

/** A tab with nothing to show yet says what to do next instead of just being empty. */
export function EmptyState({ icon, title, text, action }: Props) {
  return (
    <Card>
      <CardContent>
        <Stack spacing={1.5} alignItems="center" textAlign="center" sx={{ py: 3 }}>
          {icon}
          <Typography variant="h6">{title}</Typography>
          <Typography variant="body2" color="text.secondary" sx={{ maxWidth: 480 }}>
            {text}
          </Typography>
          {action && (
            <Button variant="contained" endIcon={<ArrowForwardIcon />} onClick={action.onClick}>
              {action.label}
            </Button>
          )}
        </Stack>
      </CardContent>
    </Card>
  );
}
