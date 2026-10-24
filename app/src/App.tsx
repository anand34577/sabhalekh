import { AlertOctagon, FileUp, Loader2, Lock, Mic, RotateCw, Upload } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { ConsentDialog, DeleteDialog, MetaDialog, RecoverDialog, ReprocessDialog, BatchExportDialog } from "./components/Dialogs";
import { Onboarding } from "./components/Onboarding";
import { QueueView } from "./components/QueueView";
import { RecordingView } from "./components/RecordingView";
import { SessionView } from "./components/SessionView";
import { SettingsView } from "./components/SettingsView";
import { Sidebar } from "./components/Sidebar";
import { Button, Toasts } from "./components/ui";
import { connectBackend, get, isTauri, openEvents, post, put } from "./lib/api";
import { clock } from "./lib/format";
import { confirmDialog, notify, onFileDrop, onTray, pickMediaFiles, setHotkey, shell } from "./lib/native";
import type { BackendEvent, HardwareStatus, Job, RecordingStatus, Recoverable, Session, Settings } from "./lib/types";
import { levels, useStore } from "./store";

export default function App() {
  const s = useStore();
  const { backend, backendError, settings, view, selectedId, recording, set, toast } = s;
  const [recoverable, setRecoverable] = useState<Recoverable[]>([]);
  const [onboarding, setOnboarding] = useState(false);
  const [consent, setConsent] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [dialog, setDialog] = useState<null | { kind: "reprocess" | "meta" | "delete"; session: Session } | { kind: "export"; ids: number[] }>(null);
  const refreshTimer = useRef<number | undefined>(undefined);

  const refreshSoon = useCallback(() => {
    clearTimeout(refreshTimer.current);
    refreshTimer.current = window.setTimeout(() => {
      useStore.getState().refreshSessions().catch(() => {});
    }, 250);
  }, []);

  // ------------------------------------------------------------------ backend lifecycle
  useEffect(() => {
    let closeEvents: (() => void) | null = null;
    let unlisten: (() => void) | null = null;
    connectBackend(async () => {
      set({ backend: "ready", backendError: null });
      closeEvents?.();
      closeEvents = openEvents(handleEvent, (c) => set({ connected: c }));
      try {
        const [st, hw, jobs, health, rec] = await Promise.all([
          get<Settings>("/api/settings"), get<HardwareStatus>("/api/hardware"), get<Job[]>("/api/jobs"),
          get<{ windows_build?: number }>("/api/health"), get<RecordingStatus>("/api/recording/status"),
        ]);
        set({ settings: st, hardware: hw, jobs, recording: rec, windowsBuild: health.windows_build ?? 0 });
        hw.warnings.forEach((w) => toast({ kind: "warning", title: "Hardware", body: w }));
        if (rec.active) set({ view: "recording" });
        await useStore.getState().refreshSessions();
        const devSession = !isTauri() && new URLSearchParams(location.search).get("session");
        if (devSession) useStore.getState().select(Number(devSession));
        if (!st.onboarding_done) setOnboarding(true);
        setRecoverable(await get<Recoverable[]>("/api/recording/recoverable"));
      } catch (e) {
        toast({ kind: "error", title: "Could not load data", body: String(e) });
      }
    }, (info) => set({ backend: "exited", backendError: info.error })).then((u) => { unlisten = u; });
    return () => {
      closeEvents?.();
      unlisten?.();
    };
  }, []);

  function handleEvent(e: BackendEvent) {
    const st = useStore.getState();
    switch (e.type) {
      case "rec_levels":
        levels.emit(e as never);
        return;
      case "rec_state": {
        const r = e as unknown as RecordingStatus;
        set({ recording: r.active ? r : { active: false } });
        return;
      }
      case "rec_warning":
        toast({ kind: "warning", title: "Recording", body: String(e.message) });
        return;
      case "job_progress": {
        set({
          jobs: st.jobs.map((j) => j.id === e.job_id ? { ...j, status: "running", stage: e.stage as string, progress: e.progress as number, eta_sec: e.eta_sec as number } : j),
          sessions: st.sessions.map((x) => x.id === e.session_id ? { ...x, status: "processing", stage: e.stage as string, progress: e.progress as number } : x),
        });
        return;
      }
      case "job_queued":
      case "job_started":
        st.refreshJobs();
        refreshSoon();
        if (st.selectedId === e.session_id) set({ transcriptVersion: st.transcriptVersion + 1 });
        return;
      case "job_finished": {
        st.refreshJobs();
        refreshSoon();
        if (st.selectedId === e.session_id) set({ transcriptVersion: st.transcriptVersion + 1 });
        const title = String(e.title || "Meeting");
        if (e.status === "done") {
          notify("Transcript ready", title);
          toast({ kind: "success", title: "Transcript ready", body: title, action: { label: "Open", run: () => useStore.getState().select(e.session_id as number) } });
        } else if (e.status === "error") {
          notify("Processing failed", `${title}: ${e.error}`);
          toast({ kind: "error", title: `Processing failed: ${title}`, body: String(e.error) });
        }
        return;
      }
      case "job_warning":
        toast({ kind: "warning", title: "Note", body: String(e.message) });
        return;
      case "session_created":
      case "session_deleted":
        refreshSoon();
        return;
      case "session_updated":
        refreshSoon();
        return;
      case "transcript_updated":
        if (st.selectedId === e.session_id) set({ transcriptVersion: st.transcriptVersion + 1 });
        return;
      case "settings_updated":
        get<Settings>("/api/settings").then((x) => set({ settings: x }));
        return;
      case "pack_imported":
        toast({ kind: "success", title: "Model pack imported", body: (e.models as string[]).join(", ") });
        window.dispatchEvent(new CustomEvent("sabhalekh-event", { detail: e }));
        return;
      case "pack_failed":
        toast({ kind: "error", title: "Model pack import failed", body: String(e.error) });
        window.dispatchEvent(new CustomEvent("sabhalekh-event", { detail: e }));
        return;
      default:
    }
  }

  // ------------------------------------------------------------------ appearance
  useEffect(() => {
    if (!settings) return;
    const root = document.documentElement;
    const mq = window.matchMedia("(prefers-color-scheme: light)");
    const apply = () => {
      const light = settings.theme === "light" || (settings.theme === "system" && mq.matches);
      root.classList.toggle("light", light);
    };
    apply();
    root.style.setProperty("--accent", settings.accent);
    root.style.setProperty("--scale", String(settings.text_scale || 1));
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, [settings?.theme, settings?.accent, settings?.text_scale, settings]);

  useEffect(() => {
    document.documentElement.classList.toggle("mica", s.windowsBuild >= 22000);
  }, [s.windowsBuild]);

  // ------------------------------------------------------------------ recording control
  const startRecording = useCallback(async () => {
    const st = useStore.getState();
    if (st.recording.active) return;
    if (!st.settings?.consent_acknowledged) {
      setConsent(true);
      return;
    }
    try {
      const r = await post<RecordingStatus>("/api/recording/start", {});
      set({ recording: r, view: "recording" });
    } catch (e) {
      toast({ kind: "error", title: "Could not start recording", body: String(e) });
    }
  }, [set, toast]);

  const stopRecording = useCallback(async () => {
    try {
      const sess = await post<Session>("/api/recording/stop");
      set({ recording: { active: false } });
      await useStore.getState().refreshSessions();
      useStore.getState().select(sess.id);
      toast({ kind: "success", title: "Recording saved", body: useStore.getState().settings?.auto_process ? "Processing has started." : sess.title });
    } catch (e) {
      toast({ kind: "error", title: "Could not stop recording", body: String(e) });
    }
  }, [set, toast]);

  const toggleRecording = useCallback(() => {
    if (useStore.getState().recording.active) stopRecording();
    else startRecording();
  }, [startRecording, stopRecording]);

  // tray indicator + window title, always visible while recording
  useEffect(() => {
    if (!recording.active) {
      shell.setRecordingIndicator(false);
      return;
    }
    const tick = () => {
      const r = useStore.getState().recording;
      shell.setRecordingIndicator(true, r.paused ? "(paused)" : clock(lastElapsed.current, true));
    };
    tick();
    const t = setInterval(tick, 5000);
    return () => clearInterval(t);
  }, [recording.active, recording.paused]);
  const lastElapsed = useRef(0);
  useEffect(() => levels.subscribe((l) => { lastElapsed.current = l.elapsed; }), []);

  useEffect(() => {
    if (backend !== "ready" || !settings) return;
    setHotkey(settings.hotkey, toggleRecording).then((err) => {
      if (err) toast({ kind: "warning", title: "Hotkey unavailable", body: `${settings.hotkey}: ${err}` });
    });
    shell.setCloseToTray(settings.minimize_to_tray);
  }, [backend, settings?.hotkey, settings?.minimize_to_tray, toggleRecording, settings, toast]);

  useEffect(() => onTray(toggleRecording, async () => {
    if (useStore.getState().recording.active) {
      if (!(await confirmDialog("A recording is running. Stop and save it, then quit?"))) return;
      await stopRecording();
    }
    shell.quit();
  }), [toggleRecording, stopRecording]);

  // ------------------------------------------------------------------ import
  const importFiles = useCallback(async (paths: string[]) => {
    if (!paths.length) return;
    try {
      const r = await post<{ created: number[]; errors: { path: string; error: string }[] }>("/api/sessions/import", { paths });
      if (r.created.length) {
        toast({ kind: "success", title: `Imported ${r.created.length} file${r.created.length > 1 ? "s" : ""}`,
          body: useStore.getState().settings?.auto_process ? "Added to the processing queue." : undefined });
        await useStore.getState().refreshSessions();
        useStore.getState().select(r.created[0]);
      }
      r.errors.forEach((er) => toast({ kind: "error", title: `Cannot import ${er.path.split(/[\\/]/).pop()}`, body: er.error }));
    } catch (e) {
      toast({ kind: "error", title: "Import failed", body: String(e) });
    }
  }, [toast]);

  useEffect(() => onFileDrop((p) => { if (useStore.getState().backend === "ready") importFiles(p); }, setDragOver), [importFiles]);

  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.shiftKey && e.key.toLowerCase() === "e") {
        e.preventDefault();
        setDialog({ kind: "export", ids: [] });
      }
      if (e.ctrlKey && e.key.toLowerCase() === "o") {
        e.preventDefault();
        pickMediaFiles().then(importFiles);
      }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [importFiles]);

  // ------------------------------------------------------------------ render
  if (backend !== "ready") {
    return (
      <div className="flex h-full items-center justify-center bg-layer">
        {backend === "starting" ? (
          <div className="text-center fade-in">
            <img src="/icon.png" alt="" className="mx-auto h-16 w-16 rounded-2xl shadow-lg" />
            <div className="mt-5 flex items-center justify-center gap-2 text-[0.95rem] text-fg-2">
              <Loader2 size={17} className="animate-spin" /> Starting the offline engine…
            </div>
            <div className="mt-2 flex items-center justify-center gap-1 text-[0.76rem] text-fg-3"><Lock size={12} /> Nothing ever leaves this PC</div>
          </div>
        ) : (
          <div className="max-w-xl rounded-2xl border border-stroke bg-card p-6 fade-in">
            <div className="flex items-center gap-2 text-[1.05rem] font-semibold"><AlertOctagon className="text-danger" /> The processing engine stopped</div>
            <pre className="selectable mt-3 max-h-64 overflow-auto whitespace-pre-wrap rounded-lg bg-layer-2 p-3 text-[0.76rem] text-fg-2">{backendError}</pre>
            <p className="mt-3 text-[0.82rem] text-fg-3">Your recordings and transcripts are safe. Restart the engine; if it keeps failing, the log files in %APPDATA%\Sabhalekh\logs explain why.</p>
            <Button className="mt-4" variant="primary" icon={<RotateCw size={15} />} onClick={() => { set({ backend: "starting" }); shell.restartBackend(); }}>Restart engine</Button>
          </div>
        )}
      </div>
    );
  }

  const selected = s.sessions.find((x) => x.id === selectedId);
  const openReprocess = (x: Session) => setDialog({ kind: "reprocess", session: x });
  return (
    <div className="flex h-full">
      <Sidebar
        onRecord={startRecording}
        onUpload={() => pickMediaFiles().then(importFiles)}
        onRename={(x) => setDialog({ kind: "meta", session: x })}
        onReprocess={openReprocess}
        onExport={(ids) => setDialog({ kind: "export", ids })}
        onDelete={(x) => setDialog({ kind: "delete", session: x })}
      />
      <main className="min-w-0 flex-1 rounded-tl-xl border-l border-t border-stroke bg-layer shadow-[var(--shadow)] overflow-hidden">
        {view === "recording" && recording.active ? (
          <RecordingView onPause={() => post("/api/recording/pause")} onResume={() => post("/api/recording/resume")} onStop={stopRecording} />
        ) : view === "queue" ? <QueueView />
          : view === "settings" ? <SettingsView />
            : view === "session" && selectedId ? (
              <SessionView key={selectedId} sessionId={selectedId}
                onReprocess={() => selected && openReprocess(selected)}
                onTags={() => selected && setDialog({ kind: "meta", session: selected })}
                onDelete={() => selected && setDialog({ kind: "delete", session: selected })} />
            ) : <Empty onRecord={startRecording} onUpload={() => pickMediaFiles().then(importFiles)} />}
      </main>

      {dragOver && (
        <div className="pointer-events-none fixed inset-3 z-50 flex items-center justify-center rounded-2xl border-2 border-dashed border-accent bg-accent-soft backdrop-blur-sm fade-in">
          <div className="text-center"><FileUp size={42} className="mx-auto text-accent" /><div className="mt-2 text-[1.05rem] font-medium">Drop audio or video files to import</div>
            <div className="text-[0.8rem] text-fg-2">mp3, wav, m4a, aac, flac, ogg, wma, mp4, mkv, mov, avi, webm</div></div>
        </div>
      )}
      {consent && <ConsentDialog onClose={() => setConsent(false)} onAccept={async () => {
        setConsent(false);
        const st = await put<Settings>("/api/settings", { consent_acknowledged: true });
        set({ settings: st });
        startRecording();
      }} />}
      {recoverable.length > 0 && !onboarding && <RecoverDialog items={recoverable} onDone={() => setRecoverable([])} />}
      {onboarding && <Onboarding onClose={() => setOnboarding(false)} />}
      {dialog?.kind === "reprocess" && <ReprocessDialog session={dialog.session} onClose={() => setDialog(null)} />}
      {dialog?.kind === "meta" && <MetaDialog session={dialog.session} onClose={() => setDialog(null)} />}
      {dialog?.kind === "delete" && <DeleteDialog session={dialog.session} onClose={() => setDialog(null)} />}
      {dialog?.kind === "export" && <BatchExportDialog initial={dialog.ids} onClose={() => setDialog(null)} />}
      <Toasts />
    </div>
  );
}

function Empty({ onRecord, onUpload }: { onRecord: () => void; onUpload: () => void }) {
  const hotkey = useStore((s) => s.settings?.hotkey ?? "").replace("CommandOrControl", "Ctrl");
  return (
    <div className="flex h-full items-center justify-center bg-layer p-10">
      <div className="max-w-xl text-center fade-in">
        <img src="/icon.png" alt="" className="mx-auto h-16 w-16 rounded-2xl shadow-lg" />
        <h1 className="mt-5 text-[1.5rem] font-semibold tracking-tight">Record or import a meeting</h1>
        <p className="mt-2 text-[0.9rem] text-fg-2">Get a transcript with speaker names and timestamps, in English, हिंदी or Hinglish, without anything leaving your PC.</p>
        <div className="mt-6 flex justify-center gap-3">
          <Button size="lg" variant="primary" icon={<Mic size={18} />} onClick={onRecord}>New Recording</Button>
          <Button size="lg" icon={<Upload size={18} />} onClick={onUpload}>Upload Media</Button>
        </div>
        <p className="mt-5 text-[0.8rem] text-fg-3">Drop audio or video files anywhere · {hotkey} starts/stops recording from any app · Ctrl+F searches a transcript</p>
      </div>
    </div>
  );
}
