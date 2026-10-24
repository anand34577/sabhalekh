import clsx from "clsx";
import {
  ArrowDownUp, Cpu, Filter, Gpu, ListChecks, Lock, Mic, MoreHorizontal, RefreshCw, Search, Settings, Trash2,
  Upload, X,
} from "lucide-react";
import { type ReactNode, useEffect, useMemo, useState } from "react";
import { get } from "../lib/api";
import { date, duration, gpuName, LANG_LABEL, STAGE_LABEL } from "../lib/format";
import type { SearchHit, Session } from "../lib/types";
import { playerBus, useStore } from "../store";
import { Badge, Button, IconButton, Menu, ProgressBar } from "./ui";

export function Snippet({ text }: { text: string }) {
  const parts: ReactNode[] = [];
  const re = /\x02(.*?)\x03/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = re.exec(text))) {
    parts.push(text.slice(last, m.index));
    parts.push(<mark key={i++} className="hit">{m[1]}</mark>);
    last = m.index + m[0].length;
  }
  parts.push(text.slice(last));
  return <>{parts}</>;
}

export function Sidebar(props: {
  onRecord: () => void;
  onUpload: () => void;
  onRename: (s: Session) => void;
  onReprocess: (s: Session) => void;
  onExport: (ids: number[]) => void;
  onDelete: (s: Session) => void;
}) {
  const { sessions, selectedId, select, query, set, filters, hardware, jobs, recording, view, refreshSessions } =
    useStore();
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [tags, setTags] = useState<string[]>([]);

  useEffect(() => {
    const q = query.trim();
    if (!q) {
      setHits(null);
      return;
    }
    const t = setTimeout(() => {
      get<SearchHit[]>(`/api/search?q=${encodeURIComponent(q)}`).then(setHits).catch(() => setHits([]));
    }, 180);
    return () => clearTimeout(t);
  }, [query, sessions]);

  useEffect(() => {
    get<string[]>("/api/tags").then(setTags).catch(() => {});
  }, [sessions]);

  useEffect(() => {
    refreshSessions().catch(() => {});
  }, [filters, refreshSessions]);

  const grouped = useMemo(() => {
    if (!hits) return null;
    const by = new Map<number, SearchHit[]>();
    hits.forEach((h) => by.set(h.session_id, [...(by.get(h.session_id) || []), h]));
    return Array.from(by.entries());
  }, [hits]);

  const activeJobs = jobs.filter((j) => j.status === "queued" || j.status === "running").length;
  const nFilters = [filters.status, filters.language, filters.source, filters.tag, filters.days].filter(Boolean).length;
  const setF = (p: Partial<typeof filters>) => set({ filters: { ...filters, ...p } });

  return (
    <aside className="flex h-full w-[300px] shrink-0 flex-col border-r border-stroke bg-transparent">
      <div className="flex items-center gap-2.5 px-4 pt-4 pb-3">
        <img src="/icon.png" alt="" className="h-7 w-7 rounded-lg" />
        <span className="text-[1.02rem] font-semibold tracking-tight">Sabhalekh</span>
        <span className="ml-auto flex items-center gap-1 text-[0.7rem] text-fg-3" title="Nothing ever leaves this PC">
          <Lock size={12} /> Offline
        </span>
      </div>

      <div className="grid grid-cols-2 gap-2 px-3">
        {recording.active ? (
          <Button variant="danger" onClick={() => useStore.getState().set({ view: "recording" })}
            className="col-span-2" icon={<span className="rec-dot h-2 w-2 rounded-full bg-white" />}>
            {recording.paused ? "Recording paused" : "Recording…"}
          </Button>
        ) : (
          <>
            <Button variant="primary" icon={<Mic size={16} />} onClick={props.onRecord}>New Recording</Button>
            <Button icon={<Upload size={16} />} onClick={props.onUpload}>Upload Media</Button>
          </>
        )}
      </div>

      <div className="px-3 pt-3">
        <div className="relative">
          <Search size={15} className="absolute left-2.5 top-2.5 text-fg-3" />
          <input
            value={query}
            onChange={(e) => set({ query: e.target.value })}
            placeholder="Search all meetings…  हिंदी भी"
            aria-label="Search all meetings"
            className="h-9 w-full rounded-lg border border-stroke bg-card pl-8 pr-8 text-[0.86rem] placeholder:text-fg-3
              focus:outline-none focus:ring-2 focus:ring-accent"
          />
          {query && (
            <IconButton label="Clear search" className="absolute right-0.5 top-0.5" onClick={() => set({ query: "" })}>
              <X size={14} />
            </IconButton>
          )}
        </div>
        {!hits && (
          <div className="mt-2 flex items-center gap-1">
            <Menu width={240} trigger={(open) => (
              <Button size="sm" variant="ghost" icon={<Filter size={14} />} onClick={open}>
                Filter{nFilters ? ` (${nFilters})` : ""}
              </Button>
            )} items={[
              { label: "Any status", checked: !filters.status, onClick: () => setF({ status: "" }) },
              { label: "Done", checked: filters.status === "done", onClick: () => setF({ status: "done" }) },
              { label: "Processing / queued", checked: filters.status === "processing",
                onClick: () => setF({ status: "processing" }) },
              { label: "Failed", checked: filters.status === "error", onClick: () => setF({ status: "error" }) },
              { separator: true, label: "" },
              { label: "Any language", checked: !filters.language, onClick: () => setF({ language: "" }) },
              { label: "English", checked: filters.language === "en", onClick: () => setF({ language: "en" }) },
              { label: "Hindi", checked: filters.language === "hi", onClick: () => setF({ language: "hi" }) },
              { separator: true, label: "" },
              { label: "Recorded & imported", checked: !filters.source, onClick: () => setF({ source: "" }) },
              { label: "Recorded only", checked: filters.source === "recorded",
                onClick: () => setF({ source: "recorded" }) },
              { label: "Imported only", checked: filters.source === "imported",
                onClick: () => setF({ source: "imported" }) },
              { separator: true, label: "" },
              { label: "Any time", checked: !filters.days, onClick: () => setF({ days: 0 }) },
              { label: "Last 7 days", checked: filters.days === 7, onClick: () => setF({ days: 7 }) },
              { label: "Last 30 days", checked: filters.days === 30, onClick: () => setF({ days: 30 }) },
              ...(tags.length ? [{ separator: true, label: "" },
                { label: "Any tag", checked: !filters.tag, onClick: () => setF({ tag: "" }) },
                ...tags.map((t) => ({ label: `#${t}`, checked: filters.tag === t, onClick: () => setF({ tag: t }) }))]
                : []),
            ]} />
            <Menu trigger={(open) => (
              <Button size="sm" variant="ghost" icon={<ArrowDownUp size={14} />} onClick={open}>
                {filters.sort === "date" ? "Date" : filters.sort === "duration" ? "Duration" : "Title"}
              </Button>
            )} items={[
              { label: "Newest first", checked: filters.sort === "date" && filters.order === "desc",
                onClick: () => setF({ sort: "date", order: "desc" }) },
              { label: "Oldest first", checked: filters.sort === "date" && filters.order === "asc",
                onClick: () => setF({ sort: "date", order: "asc" }) },
              { label: "Longest first", checked: filters.sort === "duration",
                onClick: () => setF({ sort: "duration", order: "desc" }) },
              { label: "Title A–Z", checked: filters.sort === "title",
                onClick: () => setF({ sort: "title", order: "asc" }) },
            ]} />
            {nFilters > 0 && (
              <button className="ml-auto text-[0.75rem] text-accent hover:underline"
                onClick={() => setF({ status: "", language: "", source: "", tag: "", days: 0 })}>Clear</button>
            )}
          </div>
        )}
      </div>

      <div className="mt-2 flex-1 overflow-y-auto px-2 pb-2" role="list" aria-label="Meeting history">
        {grouped ? (
          grouped.length === 0 ? (
            <div className="px-3 py-8 text-center text-[0.84rem] text-fg-3">No matches for “{query}”.</div>
          ) : grouped.map(([sid, hs]) => (
            <div key={sid} className="mb-1.5 rounded-lg px-2 py-2 hover:bg-card-hover">
              <button className="w-full text-left" onClick={() => select(sid)}>
                <div className="truncate text-[0.86rem] font-medium">{hs[0].title}</div>
                <div className="text-[0.72rem] text-fg-3">{date(hs[0].created_at)}</div>
              </button>
              {hs.filter((h) => h.segment_id).slice(0, 4).map((h) => (
                <button key={`${h.segment_id}-${h.field}`} onClick={() => {
                  select(sid);
                  setTimeout(() => playerBus.seek(h.start_sec ?? 0, false), 350);
                }}
                className="mt-1 block w-full rounded-md px-2 py-1 text-left text-[0.8rem] text-fg-2 hover:bg-card">
                  <span className="mr-1.5 tabular-nums text-fg-3">
                    {new Date((h.start_sec ?? 0) * 1000).toISOString().slice(11, 19)}
                  </span>
                  <Snippet text={h.snippet} />
                </button>
              ))}
              {hs.some((h) => h.field === "speaker") && (
                <div className="mt-1 px-2 text-[0.74rem] text-fg-3">Speaker name matches</div>
              )}
            </div>
          ))
        ) : sessions.length === 0 ? (
          <div className="px-4 py-10 text-center text-[0.84rem] leading-relaxed text-fg-3">
            {nFilters ? "No meetings match these filters." : "No meetings yet. Record one or drop audio/video files anywhere in this window."}
          </div>
        ) : sessions.map((s) => (
          <HistoryItem key={s.id} s={s} selected={selectedId === s.id && view === "session"}
            onOpen={() => select(s.id)} {...props} />
        ))}
      </div>

      <div className="flex items-center gap-1 border-t border-stroke px-2 py-2">
        <button
          onClick={() => set({ view: "settings" })}
          title={hardware ? `${hardware.info.cpu_name ?? ""}\n${gpuName(hardware.info)}` : ""}
          className="flex min-w-0 flex-1 items-center gap-2 rounded-md px-2 py-1.5 text-left hover:bg-card-hover"
        >
          {hardware && hardware.profile.accel !== "cpu"
            ? <Gpu size={16} className="shrink-0 text-success" /> : <Cpu size={16} className="shrink-0 text-fg-2" />}
          <span className="truncate text-[0.76rem] text-fg-2">{hardware?.badge ?? "Detecting hardware…"}</span>
        </button>
        <IconButton label={`Processing queue${activeJobs ? ` (${activeJobs} active)` : ""}`} active={view === "queue"}
          onClick={() => set({ view: "queue" })} className="relative">
          <ListChecks size={17} />
          {activeJobs > 0 && (
            <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-accent px-1 text-[0.6rem] font-bold text-white">
              {activeJobs}
            </span>
          )}
        </IconButton>
        <IconButton label="Settings" active={view === "settings"} onClick={() => set({ view: "settings" })}>
          <Settings size={17} />
        </IconButton>
      </div>
    </aside>
  );
}

function HistoryItem({ s, selected, onOpen, onRename, onReprocess, onExport, onDelete }: {
  s: Session; selected: boolean; onOpen: () => void; onRename: (s: Session) => void; onReprocess: (s: Session) => void;
  onExport: (ids: number[]) => void; onDelete: (s: Session) => void;
}) {
  const busy = s.status === "processing" || s.status === "queued";
  const langs = s.detected_languages?.length ? s.detected_languages : [];
  return (
    <div role="listitem"
      className={clsx("group relative mb-0.5 rounded-lg px-2.5 py-2 transition-colors",
        selected ? "bg-card-hover" : "hover:bg-card")}
      onContextMenu={(e) => { e.preventDefault(); onOpen(); }}>
      {selected && <span className="absolute left-0 top-3 bottom-3 w-[3px] rounded-full bg-accent" />}
      <button className="block w-full text-left" onClick={onOpen} aria-current={selected}>
        <div className="truncate pr-6 text-[0.87rem] font-medium">{s.title}</div>
        <div className="mt-0.5 flex items-center gap-1.5 text-[0.72rem] text-fg-3">
          <span>{date(s.created_at)}</span>
          {s.duration_sec > 0 && <><span>·</span><span>{duration(s.duration_sec)}</span></>}
        </div>
        <div className="mt-1.5 flex flex-wrap items-center gap-1">
          <Badge tone={s.source_type === "recorded" ? "accent" : "neutral"}>
            {s.source_type === "recorded" ? "Recorded" : "Imported"}
          </Badge>
          {langs.map((l) => <Badge key={l}>{LANG_LABEL[l] ?? l.toUpperCase()}</Badge>)}
          {s.status === "error" && <Badge tone="danger">Failed</Badge>}
          {s.status === "cancelled" && <Badge tone="warning">Cancelled</Badge>}
          {s.status === "new" && <Badge tone="warning">Not processed</Badge>}
          {s.tags?.map((t) => <span key={t} className="text-[0.7rem] text-fg-3">#{t}</span>)}
        </div>
        {busy && (
          <div className="mt-2">
            <div className="mb-1 text-[0.7rem] text-fg-3">
              {s.status === "queued" ? "Waiting in queue" : `${STAGE_LABEL[s.stage ?? ""] ?? "Processing"} · ${Math.round((s.progress ?? 0) * 100)}%`}
            </div>
            <ProgressBar value={s.progress} indeterminate={s.status === "queued"} />
          </div>
        )}
      </button>
      <div className="absolute right-1.5 top-1.5 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
        <Menu align="right" trigger={(open) => (
          <IconButton label={`Actions for ${s.title}`} onClick={open} className="h-7 w-7"><MoreHorizontal size={16} /></IconButton>
        )} items={[
          { label: "Open", onClick: onOpen },
          { label: "Rename / tags", onClick: () => onRename(s) },
          { label: "Re-process…", icon: <RefreshCw size={14} />, onClick: () => onReprocess(s), disabled: busy },
          { label: "Export…", onClick: () => onExport([s.id]), disabled: s.status !== "done" },
          { separator: true, label: "" },
          { label: "Delete…", icon: <Trash2 size={14} />, danger: true, onClick: () => onDelete(s) },
        ]} />
      </div>
    </div>
  );
}
