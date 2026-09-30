import { useCallback, useEffect, useState } from "react";
import { Alert, AppBar, Badge, Box, Container, MenuItem, Select, Snackbar, Stack, Tab, Tabs, Toolbar, Typography } from "@mui/material";
import GraphicEqIcon from "@mui/icons-material/GraphicEq";
import { AppThemeProvider } from "./theme";
import { api, type Job, type SystemInfo, type VoicesPayload } from "./api";
import { VoiceCard } from "./components/VoiceCard";
import { StudioCard } from "./components/StudioCard";
import { DatasetCard } from "./components/DatasetCard";
import { TrainingCard } from "./components/TrainingCard";
import { JobsCard } from "./components/JobsCard";
import { TestCard } from "./components/TestCard";
import { SystemChip } from "./components/SystemChip";
import { useTrainingStream } from "./lib/useTrainingStream";
import { errorText, I18nProvider, useI18n, type Lang } from "./i18n";

const TABS = ["voice", "record", "train", "test"] as const;
type TabId = (typeof TABS)[number];

export default function App() {
  return (
    <I18nProvider>
      <AppThemeProvider>
        <Main />
      </AppThemeProvider>
    </I18nProvider>
  );
}

function Main() {
  const { t, lang, setLang } = useI18n();
  const [payload, setPayload] = useState<VoicesPayload | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [system, setSystem] = useState<SystemInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [datasetVersion, setDatasetVersion] = useState(0);
  const { state, log } = useTrainingStream();
  const [tab, setTab] = useState<TabId>(() => {
    const hash = location.hash.replace("#", "") as TabId;
    return TABS.includes(hash) ? hash : "voice";
  });

  const showError = useCallback((message: string) => setError(message), []);
  const selectTab = (next: TabId) => {
    setTab(next);
    history.replaceState(null, "", `#${next}`);
  };

  const loadJobs = useCallback(() => {
    api
      .jobs()
      .then((r) => setJobs(r.items))
      .catch((e) => showError(errorText(t, e)));
  }, [showError, t]);

  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);

  useEffect(() => {
    api
      .voices()
      .then(setPayload)
      .catch((e) => showError(errorText(t, e)));
    loadJobs();
    const loadSystem = () => api.system().then(setSystem).catch(() => undefined);
    loadSystem();
    const timer = setInterval(loadSystem, 30000);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onVoices = useCallback(
    (p: VoicesPayload) => {
      setPayload(p);
      setDatasetVersion((v) => v + 1);
      loadJobs();
    },
    [loadJobs],
  );

  const running = ["downloading", "preparing", "training", "exporting"].includes(state.status);
  const voice = payload?.voice ?? null;

  return (
    <Box sx={{ minHeight: "100vh", bgcolor: "background.default" }}>
      <AppBar position="sticky" color="default" elevation={0} sx={{ borderBottom: 1, borderColor: "divider", bgcolor: "background.paper" }}>
        <Toolbar>
          <GraphicEqIcon color="primary" sx={{ mr: 1.5 }} />
          <Box sx={{ flex: 1, minWidth: 0 }}>
            <Typography variant="h6" component="h1" lineHeight={1.2}>
              {t("app.title")}
            </Typography>
            <Typography variant="caption" color="text.secondary" noWrap display="block">
              {t("app.subtitle")}
            </Typography>
          </Box>
          {voice && (
            <Typography variant="subtitle1" fontWeight={600} color="primary" sx={{ mr: 2, display: { xs: "none", md: "block" } }}>
              {voice.name}
            </Typography>
          )}
          <SystemChip info={system} />
          <Select size="small" value={lang} onChange={(e) => setLang(e.target.value as Lang)} aria-label={t("app.language")} sx={{ minWidth: 90 }}>
            <MenuItem value="cs">Čeština</MenuItem>
            <MenuItem value="en">English</MenuItem>
          </Select>
        </Toolbar>
        <Tabs value={tab} onChange={(_, v) => selectTab(v as TabId)} variant="scrollable" allowScrollButtonsMobile sx={{ px: 1 }}>
          <Tab value="voice" label={t("tabs.voice")} />
          <Tab value="record" label={t("tabs.record")} disabled={!voice} />
          <Tab
            value="train"
            disabled={!voice}
            label={
              <Badge color="info" variant="dot" invisible={!running}>
                {t("tabs.train")}
              </Badge>
            }
          />
          <Tab value="test" label={t("tabs.test")} disabled={!voice} />
        </Tabs>
      </AppBar>

      <Container maxWidth="md" sx={{ py: 3 }}>
        <Stack spacing={3}>
          {tab === "voice" && payload && <VoiceCard payload={payload} disabled={running} onChange={onVoices} onError={showError} />}
          {tab !== "voice" && !voice && <Alert severity="info">{t("app.noVoice")}</Alert>}
          {tab === "record" && voice && payload && (
            <>
              <StudioCard key={voice.id} voice={voice} minutes={payload.minutes} disabled={running} onChanged={() => setDatasetVersion((v) => v + 1)} onError={showError} />
              <DatasetCard version={datasetVersion} />
            </>
          )}
          {tab === "train" && voice && payload && (
            <>
              <TrainingCard state={state} log={log} voice={voice} defaults={payload.defaults} system={system} datasetVersion={datasetVersion} onVoices={onVoices} onError={showError} onFinished={loadJobs} />
              <JobsCard jobs={jobs} disabled={running} onChanged={loadJobs} onError={showError} />
            </>
          )}
          {tab === "test" && voice && <TestCard jobs={jobs} onError={showError} />}
          <Typography variant="caption" color="text.secondary" textAlign="center">
            {t("app.footer")}
          </Typography>
        </Stack>
      </Container>

      <Snackbar open={!!error} autoHideDuration={8000} onClose={() => setError(null)} anchorOrigin={{ vertical: "bottom", horizontal: "center" }}>
        <Alert severity="error" onClose={() => setError(null)} variant="filled">
          {error}
        </Alert>
      </Snackbar>
    </Box>
  );
}
