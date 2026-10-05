import { useCallback, useEffect, useState } from "react";
import { Accordion, AccordionDetails, AccordionSummary, Alert, AppBar, Badge, Box, Container, IconButton, MenuItem, Select, Snackbar, Stack, Tab, Tabs, Toolbar, Tooltip, Typography } from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import HelpOutlineIcon from "@mui/icons-material/HelpOutline";
import MicNoneIcon from "@mui/icons-material/MicNone";
import GraphicEqIcon from "@mui/icons-material/GraphicEq";
import { AppThemeProvider } from "./theme";
import { api, type DatasetReport, type Job, type SystemInfo, type VoicesPayload } from "./api";
import { VoiceCard } from "./components/VoiceCard";
import { StudioCard } from "./components/StudioCard";
import { DatasetCard } from "./components/DatasetCard";
import { TranscribeCard } from "./components/TranscribeCard";
import { TrainingCard } from "./components/TrainingCard";
import { ProcessingCard } from "./components/ProcessingCard";
import { JobsCard } from "./components/JobsCard";
import { TestCard } from "./components/TestCard";
import { DeployCard } from "./components/DeployCard";
import { ProgressSteps, type TabId } from "./components/ProgressSteps";
import { TrainingChip } from "./components/TrainingChip";
import { HelpDialog } from "./components/HelpDialog";
import { EmptyState } from "./components/EmptyState";
import { StorageCard } from "./components/StorageCard";
import { SystemChip } from "./components/SystemChip";
import { useTrainingStream } from "./lib/useTrainingStream";
import { errorText, I18nProvider, useI18n, type Lang } from "./i18n";

const TABS: TabId[] = ["voice", "record", "data", "train", "test"];

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
  const [report, setReport] = useState<DatasetReport | null>(null);
  const [helpOpen, setHelpOpen] = useState(false);
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

  // the dataset report feeds the step bar, the dataset overview and the training requirements
  const voiceId = payload?.voice?.id ?? null;
  useEffect(() => {
    if (!voiceId) {
      setReport(null);
      return;
    }
    api.dataset().then(setReport).catch(() => setReport(null));
  }, [voiceId, datasetVersion, state.status]);

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

  // an import adds recordings behind the studio's back, so the studio is re-mounted to reload its list
  const [importCount, setImportCount] = useState(0);
  const onImported = useCallback(() => {
    setImportCount((v) => v + 1);
    setDatasetVersion((v) => v + 1);
    api
      .voices()
      .then(setPayload)
      .catch(() => undefined);
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
          <TrainingChip state={state} onClick={() => selectTab("train")} />
          <SystemChip info={system} />
          <Tooltip title={t("help.title")}>
            <IconButton onClick={() => setHelpOpen(true)} size="small" sx={{ mr: 1 }}>
              <HelpOutlineIcon />
            </IconButton>
          </Tooltip>
          <Select size="small" value={lang} onChange={(e) => setLang(e.target.value as Lang)} aria-label={t("app.language")} sx={{ minWidth: 90 }}>
            <MenuItem value="cs">Čeština</MenuItem>
            <MenuItem value="en">English</MenuItem>
          </Select>
        </Toolbar>
        <Tabs value={tab} onChange={(_, v) => selectTab(v as TabId)} variant="scrollable" allowScrollButtonsMobile sx={{ px: 1 }}>
          <Tab value="voice" label={t("tabs.voice")} />
          <Tab value="record" label={t("tabs.record")} disabled={!voice} />
          <Tab value="data" label={t("tabs.data")} disabled={!voice} />
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

      <Container maxWidth="md" sx={{ py: 2 }}>
        <Stack spacing={3}>
          {payload && <ProgressSteps voice={voice} report={report} jobs={jobs} state={state} tab={tab} onGo={selectTab} />}
          {tab === "voice" && payload && <VoiceCard payload={payload} disabled={running} onChange={onVoices} onError={showError} />}
          {tab !== "voice" && !voice && <Alert severity="info">{t("app.noVoice")}</Alert>}
          {tab === "record" && voice && payload && (
            <StudioCard key={`${voice.id}-${importCount}`} voice={voice} minutes={payload.minutes} disabled={running} onChanged={() => setDatasetVersion((v) => v + 1)} onError={showError} />
          )}
          {tab === "data" && voice && payload && (
            <>
              {report && report.count === 0 && (
                <EmptyState icon={<MicNoneIcon color="disabled" sx={{ fontSize: 48 }} />} title={t("empty.dataTitle")} text={t("empty.dataText")} action={{ label: t("empty.dataAction"), onClick: () => selectTab("record") }} />
              )}
              <DatasetCard report={report} disabled={running} onImported={onImported} onError={showError} />
              <TranscribeCard voiceId={voice.id} disabled={running} onImported={onImported} onError={showError} />
              <StorageCard version={datasetVersion + jobs.length} disabled={running} onError={showError} onChanged={() => setDatasetVersion((v) => v + 1)} />
            </>
          )}
          {tab === "train" && voice && payload && (
            <>
              <TrainingCard state={state} log={log} voice={voice} report={report} jobs={jobs} defaults={payload.defaults} system={system} onVoices={onVoices} onError={showError} onFinished={loadJobs} onGo={selectTab} />
              {(report?.count ?? 0) > 0 && <ProcessingCard voice={voice} payload={payload} disabled={running} onVoices={onVoices} onError={showError} />}
              {jobs.length > 0 && (
                <Accordion disableGutters variant="outlined" defaultExpanded={jobs.length > 1 && !running}>
                  <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                    <Typography variant="subtitle2">{t("jobs.accordion", { n: jobs.length })}</Typography>
                  </AccordionSummary>
                  <AccordionDetails sx={{ p: 0 }}>
                    <JobsCard jobs={jobs} liveEpoch={state.epoch} disabled={running} onChanged={loadJobs} onError={showError} />
                  </AccordionDetails>
                </Accordion>
              )}
            </>
          )}
          {tab === "test" && voice && payload && (
            <>
              <TestCard jobs={jobs} voice={voice} baseVoiceName={payload.languages.find((l) => l.id === voice.language)?.base.name ?? null} onVoices={onVoices} onError={showError} onGo={selectTab} />
              <DeployCard jobs={jobs} onError={showError} />
            </>
          )}
          <Typography variant="caption" color="text.secondary" textAlign="center">
            {t("app.footer")}
          </Typography>
        </Stack>
      </Container>

      <HelpDialog open={helpOpen} onClose={() => setHelpOpen(false)} />
      <Snackbar open={!!error} autoHideDuration={8000} onClose={() => setError(null)} anchorOrigin={{ vertical: "bottom", horizontal: "center" }}>
        <Alert severity="error" onClose={() => setError(null)} variant="filled">
          {error}
        </Alert>
      </Snackbar>
    </Box>
  );
}
