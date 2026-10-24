import clsx from "clsx";
import {
  AlertTriangle, Check, ChevronDown, ChevronUp, Copy, Download, FileAudio, Loader2, MoreHorizontal, RefreshCw,
  Search, Tag, Trash2, Undo2, X,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { get, patch, post, put } from "../lib/api";
import { clock, date, duration, eta, LANG_LABEL, STAGE_LABEL } from "../lib/format";
import { confirmDialog, pickSavePath, shell } from "../lib/native";
import type { SessionDetail } from "../lib/types";
import { useStore } from "../store";
import { Player } from "./Player";
import { Transcript } from "./Transcript";
import { Badge, Button, IconButton, Menu, ProgressBar } from "./ui";

export const EXPORT_FORMATS = [
  { id: "txt", label: "Plain text (.txt)" },
  { id: "docx", label: "Word document (.docx)" },
  { id: "pdf", label: "PDF meeting report (.pdf)" },
  { id: "srt", label: "Subtitles (.srt)" },
  { id: "vtt", label: "Web subtitles (.vtt)" },
  { id: "md", label: "Markdown (.md)" },
  { id: "json", label: "JSON with word timings (.json)" },
  { id: "csv", label: "Spreadsheet (.csv)" },
];

export function safeName(title: string) {
  return title.replace(/[\\/:*?"<>|]+/g, "_").trim().slice(0, 80) || "transcript";
}

export function SessionView({ sessionId, onReprocess, onTags, onDelete }: {
  sessionId: number; onReprocess: () => void; onTags: () => void; onDelete: () => void;
}) {
  const { toast, settings, jobs, transcriptVersion, set } = useStore();
  const [detail, setDetail] = useState<SessionDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState(false);
  const [title, setTitle] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [matchCount, setMatchCount] = useState(0);
  const [matchIndex, setMatchIndex] = useState(0);
  const [version, setVersion] = useState(0);
  const searchRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    try {
      const d = await get<SessionDetail>(`/api/sessions/${sessionId}`);
      setDetail(d);
      setTitle(d.session.title);
      setError(null);
    } catch (e) {
      setError(String(e));
    }
  }, [sessionId]);

  useEffect(() => {
    setDetail(null);
    setQuery("");
    setSearchOpen(false);
    load();
  }, [load]);
  useEffect(() => {
    if (transcriptVersion) load().then(() => setVersion((v) => v + 1));
  }, [transcriptVersion, load]);

  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.key.toLowerCase() === "f") {
        e.preventDefault();
        setSearchOpen(true);
        setTimeout(() => searchRef.current?.focus(), 0);
      }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, []);

  if (error) return <div className="p-10 text-danger">{error}</div>;
  if (!detail) return <div className="flex h-full items-center justify-center"><Loader2 className="animate-spin text-fg-3" /></div>;

  const s = detail.session;
  const job = jobs.find((j) => j.session_id === s.id && (j.status === "running" || j.status === "queued"));
  const busy = s.status === "processing" || s.status === "queued";
  const lastJob = jobs.find((j) => j.session_id === s.id);

  const saveTitle = async () => {
    setEditingTitle(false);
    if (title.trim() && title.trim() !== s.title) {
      await patch(`/api/sessions/${s.id}`, { title: title.trim() });
      useStore.getState().refreshSessions();
      load();
    } else setTitle(s.title);
  };

  const doExport = async (fmt: string) => {
    const path = await pickSavePath(`${safeName(s.title)}.${fmt}`, fmt, fmt.toUpperCase());
    if (!path) return;
    try {
      await post("/api/export", { session_ids: [s.id], formats: [fmt], path,
        timestamps: settings?.export_timestamps ?? true, speakers: settings?.export_speakers ?? true,
        merge: settings?.export_merge ?? true });
      toast({ kind: "success", title: `Exported ${fmt.toUpperCase()}`, body: path,
        action: { label: "Show in folder", run: () => shell.reveal(path) } });
    } catch (e) {
      toast({ kind: "error", title: "Export failed", body: String(e) });
    }
  };

  const exportAudio = async () => {
    const ext = detail.session.audio_path?.endsWith(".ogg") ? "ogg" : "wav";
    const path = await pickSavePath(`${safeName(s.title)}.${ext}`, ext, "Audio");
    if (!path) return;
    try {
      await post(`/api/sessions/${s.id}/export-audio`, { path });
      toast({ kind: "success", title: "Audio exported", body: path, action: { label: "Show in folder", run: () => shell.reveal(path) } });
    } catch (e) {
      toast({ kind: "error", title: "Audio export failed", body: String(e) });
    }
  };

  const setExportOpt = (k: "export_timestamps" | "export_speakers" | "export_merge") => {
    const v = !(settings?.[k] ?? true);
    useStore.getState().set({ settings: settings ? { ...settings, [k]: v } : settings });
    put("/api/settings", { [k]: v }).catch(() => {});
  };

  const copyAll = () => {
    const names = new Map(detail.speakers.map((x) => [x.id, x.display_name]));
    const txt = detail.segments.map((g) => `[${clock(g.start_sec, true)}] ${names.get(g.speaker_id ?? -1) ?? ""}: ${g.display_text}`).join("\n");
    navigator.clipboard.writeText(txt);
    toast({ kind: "info", title: "Transcript copied" });
  };

  const revertAll = async () => {
    if (!(await confirmDialog("Undo every edit, rename, merge and split in this meeting and restore the original transcript?"))) return;
    try {
      await post(`/api/sessions/${s.id}/revert`);
      toast({ kind: "success", title: "Original transcript restored" });
      load();
    } catch (e) {
      toast({ kind: "error", title: "Could not revert", body: String(e) });
    }
  };

  const steps = stepState(s.status, s.stage);
  const tt = detail.talk_time.filter((t) => t.seconds > 0);

  return (
    <div className="flex h-full min-w-0 flex-col bg-layer">
      {/* header */}
      <header className="border-b border-stroke px-6 pb-3 pt-4">
        <div className="flex items-start gap-3">
          <div className="min-w-0 flex-1">
            {editingTitle ? (
              <input autoFocus value={title} onChange={(e) => setTitle(e.target.value)} onBlur={saveTitle}
                onKeyDown={(e) => { if (e.key === "Enter") saveTitle(); if (e.key === "Escape") { setTitle(s.title); setEditingTitle(false); } }}
                aria-label="Meeting title"
                className="w-full rounded-md border border-accent bg-layer-2 px-2 py-0.5 text-[1.3rem] font-semibold focus:outline-none" />
            ) : (
              <h1 className="cursor-text truncate rounded-md px-2 py-0.5 -mx-2 text-[1.3rem] font-semibold hover:bg-card-hover"
                title="Click to rename" onClick={() => setEditingTitle(true)}>{s.title}</h1>
            )}
            <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[0.78rem] text-fg-3">
              <span>{date(s.created_at)}</span><span>·</span><span>{duration(s.duration_sec)}</span>
              <Badge tone={s.source_type === "recorded" ? "accent" : "neutral"}>{s.source_type === "recorded" ? "Recorded" : "Imported"}</Badge>
              {s.detected_languages.map((l) => <Badge key={l}>{LANG_LABEL[l] ?? l.toUpperCase()}</Badge>)}
              {s.tags.map((t) => <button key={t} onClick={onTags} className="text-accent hover:underline">#{t}</button>)}
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-1.5">
            {searchOpen ? (
              <div className="flex items-center gap-1 rounded-lg border border-stroke bg-card pl-2">
                <Search size={14} className="text-fg-3" />
                <input ref={searchRef} value={query} onChange={(e) => { setQuery(e.target.value); setMatchIndex(0); }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") setMatchIndex((i) => i + (e.shiftKey ? -1 : 1));
                    if (e.key === "Escape") { setQuery(""); setSearchOpen(false); }
                  }}
                  placeholder="Find in transcript" aria-label="Find in transcript"
                  className="h-8 w-44 bg-transparent text-[0.84rem] focus:outline-none" />
                <span className="w-12 text-center text-[0.72rem] tabular-nums text-fg-3">
                  {query ? (matchCount ? `${(((matchIndex % matchCount) + matchCount) % matchCount) + 1}/${matchCount}` : "0") : ""}
                </span>
                <IconButton label="Previous match" className="h-7 w-7" onClick={() => setMatchIndex((i) => i - 1)}><ChevronUp size={15} /></IconButton>
                <IconButton label="Next match" className="h-7 w-7" onClick={() => setMatchIndex((i) => i + 1)}><ChevronDown size={15} /></IconButton>
                <IconButton label="Close search" className="h-7 w-7" onClick={() => { setQuery(""); setSearchOpen(false); }}><X size={14} /></IconButton>
              </div>
            ) : (
              <IconButton label="Find in transcript (Ctrl+F)" onClick={() => { setSearchOpen(true); setTimeout(() => searchRef.current?.focus(), 0); }}>
                <Search size={17} />
              </IconButton>
            )}
            <Menu align="right" width={280} trigger={(open) => (
              <Button variant="primary" icon={<Download size={16} />} onClick={open} disabled={s.status !== "done"}>
                Export <ChevronDown size={14} />
              </Button>
            )} items={[
              ...EXPORT_FORMATS.map((f) => ({ label: f.label, onClick: () => doExport(f.id) })),
              { separator: true, label: "" },
              { label: "Export audio…", icon: <FileAudio size={14} />, onClick: exportAudio, disabled: !detail.has_audio },
              { separator: true, label: "" },
              { label: "Include timestamps", checked: settings?.export_timestamps ?? true, onClick: () => setExportOpt("export_timestamps") },
              { label: "Include speaker names", checked: settings?.export_speakers ?? true, onClick: () => setExportOpt("export_speakers") },
              { label: "Merge consecutive lines", checked: settings?.export_merge ?? true, onClick: () => setExportOpt("export_merge") },
            ]} />
            <Menu align="right" width={240} trigger={(open) => (
              <IconButton label="More actions" onClick={open}><MoreHorizontal size={18} /></IconButton>
            )} items={[
              { label: "Re-process…", icon: <RefreshCw size={14} />, onClick: onReprocess, disabled: busy },
              { label: "Tags…", icon: <Tag size={14} />, onClick: onTags },
              { label: "Copy transcript", icon: <Copy size={14} />, onClick: copyAll, disabled: !detail.segments.length },
              { label: "Revert all edits", icon: <Undo2 size={14} />, onClick: revertAll, disabled: s.status !== "done" },
              { separator: true, label: "" },
              { label: "Delete…", icon: <Trash2 size={14} />, danger: true, onClick: onDelete },
            ]} />
          </div>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <Stepper steps={steps} />
          {tt.length > 0 && (
            <div className="flex min-w-0 items-center gap-2 rounded-full border border-stroke bg-card px-3 py-1 text-[0.78rem]"
              title={tt.map((t) => `${t.name}: ${t.percent}% (${clock(t.seconds)})`).join("\n")}>
              <div className="flex h-1.5 w-20 overflow-hidden rounded-full">
                {tt.map((t) => <span key={t.speaker_id} style={{ width: `${t.percent}%`, background: t.color }} />)}
              </div>
              <span className="truncate text-fg-2">
                {tt.slice(0, 3).map((t) => `${t.name}: ${Math.round(t.percent)}%`).join(" | ")}{tt.length > 3 ? " | …" : ""}
              </span>
            </div>
          )}
          {s.status === "done" && (
            <span className="ml-auto truncate text-[0.72rem] text-fg-3" title={s.diarization_engine ?? ""}>
              {[s.asr_model, s.profile_used].filter(Boolean).join(" · ")}
            </span>
          )}
        </div>
      </header>

      {s.warnings.length > 0 && s.status === "done" && (
        <div className="flex items-start gap-2 border-b border-stroke bg-warning/10 px-6 py-2 text-[0.8rem] text-fg-2">
          <AlertTriangle size={15} className="mt-0.5 shrink-0 text-warning" />
          <div className="selectable">{s.warnings.map((w, i) => <div key={i}>{w}</div>)}</div>
        </div>
      )}

      <div className="min-h-0 flex-1">
        {busy ? (
          <div className="flex h-full items-center justify-center p-8">
            <div className="w-full max-w-md rounded-2xl border border-stroke bg-card p-6 text-center fade-in">
              <Loader2 className="mx-auto mb-3 animate-spin text-accent" size={28} />
              <div className="text-[1rem] font-medium">
                {s.status === "queued" ? "Waiting in the processing queue" : STAGE_LABEL[job?.stage ?? s.stage ?? ""] ?? "Processing"}
              </div>
              <div className="mt-1 text-[0.82rem] text-fg-3">
                {s.status === "queued" ? "It starts as soon as the current job finishes." : `${Math.round((job?.progress ?? s.progress) * 100)}% · ${eta(job?.eta_sec)}`}
              </div>
              <ProgressBar className="mt-4" value={job?.progress ?? s.progress} indeterminate={s.status === "queued"} />
              <div className="mt-4 text-[0.76rem] text-fg-3">You can keep using Sabhalekh; you will be notified when it is done.</div>
              {job && <Button className="mt-4" size="sm" variant="ghost" onClick={() => post(`/api/jobs/${job.id}/cancel`)}>Cancel</Button>}
            </div>
          </div>
        ) : s.status === "error" || s.status === "cancelled" || s.status === "new" ? (
          <div className="flex h-full items-center justify-center p-8">
            <div className="w-full max-w-lg rounded-2xl border border-stroke bg-card p-6 fade-in">
              <div className="flex items-center gap-2 text-[1rem] font-medium">
                <AlertTriangle size={18} className={s.status === "error" ? "text-danger" : "text-warning"} />
                {s.status === "error" ? "Processing failed" : s.status === "cancelled" ? "Processing was cancelled" : "Not processed yet"}
              </div>
              {s.error_message && <pre className="selectable mt-3 max-h-48 overflow-auto whitespace-pre-wrap rounded-lg bg-layer-2 p-3 text-[0.78rem] text-fg-2">{s.error_message}</pre>}
              <div className="mt-4 flex gap-2">
                <Button variant="primary" icon={<RefreshCw size={15} />} onClick={async () => {
                  try {
                    if (lastJob && lastJob.status !== "done") await post(`/api/jobs/${lastJob.id}/retry`);
                    else await post(`/api/sessions/${s.id}/process`, {});
                    useStore.getState().refreshJobs();
                  } catch (e) { toast({ kind: "error", title: "Could not start", body: String(e) }); }
                }}>{s.status === "new" ? "Process now" : "Retry"}</Button>
                <Button onClick={onReprocess}>Change settings…</Button>
              </div>
            </div>
          </div>
        ) : (
          <Transcript detail={detail} query={query} matchIndex={matchIndex} onMatches={setMatchCount}
            onChanged={() => { load(); set({ transcriptVersion: 0 }); useStore.getState().refreshSessions(); }} />
        )}
      </div>

      <Player sessionId={s.id} duration={s.duration_sec} segments={detail.segments} speakers={detail.speakers}
        hasAudio={detail.has_audio} version={version} />
    </div>
  );
}

type StepState = "done" | "active" | "todo" | "error";

/** Pipeline order is extract → vad → diarize → transcribe → align → save; the stepper shows the three milestones. */
function stepState(status: string, stage: string | null): { label: string; state: StepState }[] {
  const order = ["extract", "vad", "diarize", "transcribe", "align", "save"];
  const idx = stage ? order.indexOf(stage) : -1;
  if (status === "done") {
    return [{ label: "Audio Extracted", state: "done" }, { label: "Transcribed", state: "done" },
      { label: "Diarized", state: "done" }];
  }
  if (status === "processing") {
    return [
      { label: "Audio Extracted", state: idx >= 1 ? "done" : "active" },
      { label: "Transcribed", state: idx >= 4 ? "done" : stage === "vad" || stage === "transcribe" ? "active" : "todo" },
      { label: "Diarized", state: idx >= 3 ? "done" : stage === "diarize" ? "active" : "todo" },
    ];
  }
  const failed: StepState = status === "error" ? "error" : "todo";
  return [{ label: "Audio Extracted", state: idx >= 1 ? "done" : failed },
    { label: "Transcribed", state: idx >= 4 ? "done" : failed }, { label: "Diarized", state: idx >= 3 ? "done" : failed }];
}

function Stepper({ steps }: { steps: { label: string; state: StepState }[] }) {
  return (
    <ol className="flex items-center gap-1.5 text-[0.76rem]" aria-label="Processing steps">
      {steps.map((st, i) => (
        <li key={st.label} className="flex items-center gap-1.5">
          <span className={clsx("flex h-4.5 w-4.5 items-center justify-center rounded-full border",
            st.state === "done" && "border-success bg-success text-white",
            st.state === "active" && "border-accent text-accent",
            st.state === "todo" && "border-stroke-strong text-fg-3",
            st.state === "error" && "border-danger text-danger")}>
            {st.state === "done" ? <Check size={11} strokeWidth={3} /> : st.state === "active"
              ? <Loader2 size={11} className="animate-spin" /> : st.state === "error" ? <X size={11} /> : null}
          </span>
          <span className={clsx(st.state === "done" ? "text-fg-2" : st.state === "active" ? "text-fg" : "text-fg-3")}>{st.label}</span>
          {i < steps.length - 1 && <span className="mx-1 h-px w-5 bg-stroke-strong" />}
        </li>
      ))}
    </ol>
  );
}
