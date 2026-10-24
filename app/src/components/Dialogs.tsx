import clsx from "clsx";
import { AlertTriangle, LifeBuoy, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { del, get, patch, post } from "../lib/api";
import { date, duration } from "../lib/format";
import { pickSavePath, shell } from "../lib/native";
import type { ModelInfo, Recoverable, Session } from "../lib/types";
import { useStore } from "../store";
import { EXPORT_FORMATS } from "./SessionView";
import { Button, Field, Modal, Select, Toggle } from "./ui";

export function ConsentDialog({ onAccept, onClose }: { onAccept: () => void; onClose: () => void }) {
  return (
    <Modal title="Before you record" onClose={onClose} width={500} footer={<>
      <Button variant="ghost" onClick={onClose}>Cancel</Button>
      <Button variant="primary" onClick={onAccept}>I understand, start recording</Button>
    </>}>
      <div className="flex gap-3">
        <ShieldCheck size={22} className="mt-0.5 shrink-0 text-accent" />
        <div className="space-y-2 text-[0.88rem] text-fg-2">
          <p>Sabhalekh records <b className="text-fg">your microphone</b> and <b className="text-fg">everything your PC plays</b> (the other people in Teams, Zoom or Meet).</p>
          <p>In many places the law requires that <b className="text-fg">everyone in the meeting knows and agrees</b> that it is recorded. Tell participants before you start.</p>
          <p>While recording, a red indicator is always visible in the window title and the system tray. Audio and transcripts stay on this PC.</p>
        </div>
      </div>
    </Modal>
  );
}

export function RecoverDialog({ items, onDone }: { items: Recoverable[]; onDone: () => void }) {
  const { toast, select, refreshSessions } = useStore();
  const [busy, setBusy] = useState<string | null>(null);
  const [left, setLeft] = useState(items);
  useEffect(() => { if (!left.length) onDone(); }, [left, onDone]);
  return (
    <Modal title="Recover unfinished recording" onClose={onDone} width={540}>
      <div className="flex gap-3">
        <LifeBuoy size={22} className="mt-0.5 shrink-0 text-warning" />
        <p className="text-[0.86rem] text-fg-2">Sabhalekh was closed while recording. The audio was saved continuously, so these recordings can be restored.</p>
      </div>
      <div className="mt-4 space-y-2">
        {left.map((r) => (
          <div key={r.id} className="flex items-center gap-3 rounded-xl border border-stroke bg-card p-3">
            <div className="min-w-0 flex-1">
              <div className="truncate text-[0.9rem] font-medium">{r.title}</div>
              <div className="text-[0.76rem] text-fg-3">{date(r.started_at)} · {duration(r.duration)}</div>
            </div>
            <Button size="sm" variant="ghost" disabled={!!busy} onClick={async () => {
              await del(`/api/recording/recoverable/${r.id}`);
              setLeft((l) => l.filter((x) => x.id !== r.id));
            }}>Discard</Button>
            <Button size="sm" variant="primary" disabled={!!busy} onClick={async () => {
              setBusy(r.id);
              try {
                const s = await post<Session>(`/api/recording/recover/${r.id}`);
                toast({ kind: "success", title: "Recording recovered", body: s.title });
                await refreshSessions();
                select(s.id);
                setLeft((l) => l.filter((x) => x.id !== r.id));
              } catch (e) {
                toast({ kind: "error", title: "Recovery failed", body: String(e) });
              } finally {
                setBusy(null);
              }
            }}>{busy === r.id ? "Recovering…" : "Recover"}</Button>
          </div>
        ))}
      </div>
    </Modal>
  );
}

export function ReprocessDialog({ session, onClose }: { session: Session; onClose: () => void }) {
  const { settings, toast, refreshJobs, refreshSessions } = useStore();
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [p, setP] = useState({
    language_mode: session.language_mode || settings?.language_mode || "auto",
    script_mode: session.script_mode || settings?.script_mode || "as_spoken",
    asr_model: "auto",
    min_speakers: settings?.min_speakers ?? 0,
    max_speakers: settings?.max_speakers ?? 0,
    initial_prompt: settings?.initial_prompt ?? "",
  });
  useEffect(() => { get<{ models: ModelInfo[] }>("/api/models").then((r) => setModels(r.models.filter((m) => m.kind === "asr"))); }, []);
  const translateBlocked = p.language_mode === "translate" && !models.some((m) => m.translate && m.available);
  return (
    <Modal title="Re-process meeting" onClose={onClose} footer={<>
      <Button variant="ghost" onClick={onClose}>Cancel</Button>
      <Button variant="primary" disabled={translateBlocked} onClick={async () => {
        try {
          await post(`/api/sessions/${session.id}/process`, { ...p, min_speakers: p.min_speakers || null,
            max_speakers: p.max_speakers || null });
          toast({ kind: "info", title: "Queued for processing", body: "Speaker names you set are kept." });
          refreshJobs();
          refreshSessions();
          onClose();
        } catch (e) {
          toast({ kind: "error", title: "Could not queue", body: String(e) });
        }
      }}>Re-process</Button>
    </>}>
      <p className="mb-2 text-[0.84rem] text-fg-2">The transcript is regenerated from the audio. Manual edits are replaced; speaker names are kept.</p>
      <Field label="Language">
        <Select value={p.language_mode} onChange={(v) => setP({ ...p, language_mode: v })} options={[
          { value: "auto", label: "Auto: English + Hindi" }, { value: "en", label: "English only" },
          { value: "hi", label: "Hindi only" }, { value: "translate", label: "Translate Hindi to English" }]} />
      </Field>
      {translateBlocked && <p className="text-[0.78rem] text-warning">Translation needs Whisper large-v3 (Accuracy model pack): Nemotron ASR cannot translate.</p>}
      <Field label="Script">
        <Select value={p.script_mode} onChange={(v) => setP({ ...p, script_mode: v })} options={[
          { value: "as_spoken", label: "As spoken" }, { value: "devanagari", label: "Devanagari" }, { value: "roman", label: "Roman (Hinglish)" }]} />
      </Field>
      <Field label="Model">
        <Select value={p.asr_model} onChange={(v) => setP({ ...p, asr_model: v })} options={[
          { value: "auto", label: "Automatic" },
          ...models.map((m) => ({ value: m.id, label: m.label + (m.available ? "" : " (not installed)"), disabled: !m.available }))]} />
      </Field>
      <div className="grid grid-cols-2 gap-4">
        <Field label="Min speakers">
          <Select value={p.min_speakers} onChange={(v) => setP({ ...p, min_speakers: v })}
            options={[{ value: 0, label: "Auto" }, ...[1, 2, 3, 4, 5, 6, 7, 8].map((n) => ({ value: n, label: String(n) }))]} />
        </Field>
        <Field label="Max speakers">
          <Select value={p.max_speakers} onChange={(v) => setP({ ...p, max_speakers: v })}
            options={[{ value: 0, label: "Auto (up to 8)" }, ...[1, 2, 3, 4, 5, 6, 7].map((n) => ({ value: n, label: String(n) }))]} />
        </Field>
      </div>
      <Field label="Custom vocabulary">
        <input value={p.initial_prompt} onChange={(e) => setP({ ...p, initial_prompt: e.target.value })}
          className="h-9 w-full rounded-lg border border-stroke bg-card px-3 text-[0.86rem] focus:outline-none focus:ring-2 focus:ring-accent" />
      </Field>
    </Modal>
  );
}

export function MetaDialog({ session, onClose }: { session: Session; onClose: () => void }) {
  const { toast, refreshSessions, set, transcriptVersion } = useStore();
  const [title, setTitle] = useState(session.title);
  const [tags, setTags] = useState(session.tags.join(", "));
  return (
    <Modal title="Rename & tags" onClose={onClose} width={460} footer={<>
      <Button variant="ghost" onClick={onClose}>Cancel</Button>
      <Button variant="primary" disabled={!title.trim()} onClick={async () => {
        try {
          await patch(`/api/sessions/${session.id}`, { title: title.trim(), tags: tags.split(/[,#]/).map((t) => t.trim()).filter(Boolean) });
          await refreshSessions();
          set({ transcriptVersion: transcriptVersion + 1 });
          onClose();
        } catch (e) {
          toast({ kind: "error", title: "Not saved", body: String(e) });
        }
      }}>Save</Button>
    </>}>
      <Field label="Title">
        <input autoFocus value={title} onChange={(e) => setTitle(e.target.value)}
          className="h-9 w-full rounded-lg border border-stroke bg-card px-3 text-[0.9rem] focus:outline-none focus:ring-2 focus:ring-accent" />
      </Field>
      <Field label="Tags" hint="Comma separated, e.g. finance, weekly, client-x">
        <input value={tags} onChange={(e) => setTags(e.target.value)}
          className="h-9 w-full rounded-lg border border-stroke bg-card px-3 text-[0.9rem] focus:outline-none focus:ring-2 focus:ring-accent" />
      </Field>
    </Modal>
  );
}

export function DeleteDialog({ session, onClose }: { session: Session; onClose: () => void }) {
  const { toast, refreshSessions, select, selectedId } = useStore();
  const [mode, setMode] = useState<"audio" | "all">("all");
  return (
    <Modal title={`Delete “${session.title}”?`} onClose={onClose} width={480} footer={<>
      <Button variant="ghost" onClick={onClose}>Cancel</Button>
      <Button variant="danger" onClick={async () => {
        try {
          await del(`/api/sessions/${session.id}?mode=${mode}`);
          if (mode === "all" && selectedId === session.id) select(null);
          await refreshSessions();
          toast({ kind: "info", title: mode === "all" ? "Meeting deleted" : "Audio deleted, transcript kept" });
          onClose();
        } catch (e) {
          toast({ kind: "error", title: "Delete failed", body: String(e) });
        }
      }}>{mode === "all" ? "Delete everything" : "Delete audio"}</Button>
    </>}>
      <div className="space-y-2">
        {([["audio", "Delete audio only", "Frees disk space. The transcript, speaker names and search stay."],
          ["all", "Delete everything", "Audio, transcript and history entry. This cannot be undone."]] as const).map(([v, t, d]) => (
          <label key={v} className={clsx("flex cursor-pointer gap-3 rounded-xl border p-3", mode === v ? "border-accent bg-accent-soft" : "border-stroke bg-card")}>
            <input type="radio" name="delmode" checked={mode === v} onChange={() => setMode(v)} className="mt-1 accent-[var(--accent)]" />
            <span><span className="block text-[0.9rem] font-medium">{t}</span><span className="text-[0.8rem] text-fg-3">{d}</span></span>
          </label>
        ))}
      </div>
      {mode === "all" && <p className="mt-3 flex items-center gap-1.5 text-[0.8rem] text-danger"><AlertTriangle size={14} /> Permanent.</p>}
    </Modal>
  );
}

export function BatchExportDialog({ initial, onClose }: { initial: number[]; onClose: () => void }) {
  const { sessions, toast, settings } = useStore();
  const done = sessions.filter((s) => s.status === "done");
  const [ids, setIds] = useState<number[]>(initial.length ? initial : done.map((s) => s.id));
  const [formats, setFormats] = useState<string[]>(["txt", "pdf"]);
  const [opts, setOpts] = useState({ timestamps: settings?.export_timestamps ?? true, speakers: settings?.export_speakers ?? true,
    merge: settings?.export_merge ?? true });
  const [busy, setBusy] = useState(false);
  const toggle = <T,>(arr: T[], v: T) => (arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v]);
  return (
    <Modal title="Export transcripts" onClose={onClose} width={640} footer={<>
      <Button variant="ghost" onClick={onClose}>Cancel</Button>
      <Button variant="primary" disabled={!ids.length || !formats.length || busy} onClick={async () => {
        const single = ids.length === 1 && formats.length === 1;
        const s = sessions.find((x) => x.id === ids[0]);
        const name = single ? `${(s?.title ?? "transcript").replace(/[\\/:*?"<>|]+/g, "_")}.${formats[0]}` : "Sabhalekh export.zip";
        const path = await pickSavePath(name, single ? formats[0] : "zip", single ? formats[0].toUpperCase() : "ZIP archive");
        if (!path) return;
        setBusy(true);
        try {
          await post("/api/export", { session_ids: ids, formats, path, ...opts });
          toast({ kind: "success", title: "Export complete", body: path, action: { label: "Show in folder", run: () => shell.reveal(path) } });
          onClose();
        } catch (e) {
          toast({ kind: "error", title: "Export failed", body: String(e) });
        } finally {
          setBusy(false);
        }
      }}>{busy ? "Exporting…" : ids.length > 1 || formats.length > 1 ? "Export as ZIP…" : "Export…"}</Button>
    </>}>
      <div className="grid grid-cols-2 gap-5">
        <div>
          <div className="mb-1.5 flex items-center justify-between text-[0.86rem]">
            <span>Meetings ({ids.length})</span>
            <button className="text-[0.76rem] text-accent hover:underline" onClick={() => setIds(ids.length === done.length ? [] : done.map((s) => s.id))}>
              {ids.length === done.length ? "None" : "All"}
            </button>
          </div>
          <div className="max-h-72 space-y-0.5 overflow-auto rounded-lg border border-stroke p-1">
            {done.map((s) => (
              <label key={s.id} className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1 text-[0.82rem] hover:bg-card-hover">
                <input type="checkbox" checked={ids.includes(s.id)} onChange={() => setIds(toggle(ids, s.id))} className="accent-[var(--accent)]" />
                <span className="truncate">{s.title}</span>
              </label>
            ))}
          </div>
        </div>
        <div>
          <div className="mb-1.5 text-[0.86rem]">Formats</div>
          <div className="space-y-0.5">
            {EXPORT_FORMATS.map((f) => (
              <label key={f.id} className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1 text-[0.82rem] hover:bg-card-hover">
                <input type="checkbox" checked={formats.includes(f.id)} onChange={() => setFormats(toggle(formats, f.id))} className="accent-[var(--accent)]" />
                {f.label}
              </label>
            ))}
          </div>
          <div className="mt-2 border-t border-stroke pt-1">
            <Toggle label="Timestamps" checked={opts.timestamps} onChange={(v) => setOpts({ ...opts, timestamps: v })} />
            <Toggle label="Speaker names" checked={opts.speakers} onChange={(v) => setOpts({ ...opts, speakers: v })} />
            <Toggle label="Merge consecutive lines" checked={opts.merge} onChange={(v) => setOpts({ ...opts, merge: v })} />
          </div>
        </div>
      </div>
    </Modal>
  );
}
