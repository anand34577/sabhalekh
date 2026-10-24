import clsx from "clsx";
import {
  Check, Copy, CornerDownLeft, Layers, Merge, Pencil, Scissors, Undo2, UserPlus, UserRoundPen, Users,
} from "lucide-react";
import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { patch, post } from "../lib/api";
import { clock, LANG_LABEL, searchNorm } from "../lib/format";
import { activeSegmentIndex, activeWordIndex, wordIndexAtChar } from "../lib/karaoke";
import type { Segment, SessionDetail, Speaker } from "../lib/types";
import { playerBus, timeBus, useStore } from "../store";
import { Button, IconButton, Menu, Modal } from "./ui";

interface Props {
  detail: SessionDetail;
  query: string;
  matchIndex: number;
  onMatches: (n: number) => void;
  onChanged: () => void;
}

export function Transcript({ detail, query, matchIndex, onMatches, onChanged }: Props) {
  const { segments, speakers } = detail;
  const toast = useStore((s) => s.toast);
  const [active, setActive] = useState(-1);
  const [word, setWord] = useState(-1);
  const [follow, setFollow] = useState(true);
  const [editing, setEditing] = useState<number | null>(null);
  const [renaming, setRenaming] = useState<Speaker | null>(null);
  const [newSpeakerFor, setNewSpeakerFor] = useState<Segment | null>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const userScrollUntil = useRef(0);
  const spk = useMemo(() => new Map(speakers.map((s) => [s.id, s])), [speakers]);

  // karaoke: follow the player
  useEffect(() => timeBus.subscribe((t) => {
    const i = activeSegmentIndex(segments, t);
    setActive((prev) => (prev === i ? prev : i));
    const w = i >= 0 ? activeWordIndex(segments[i], t) : -1;
    setWord((prev) => (prev === w ? prev : w));
  }), [segments]);

  useEffect(() => {
    if (!follow || active < 0 || editing !== null || Date.now() < userScrollUntil.current) return;
    const el = scroller.current?.querySelector<HTMLElement>(`[data-seg="${segments[active]?.id}"]`);
    const box = scroller.current?.getBoundingClientRect();
    if (el && box) {
      const r = el.getBoundingClientRect();
      if (r.top < box.top + 40 || r.bottom > box.bottom - 40) el.scrollIntoView({ block: "center", behavior: "smooth" });
    }
  }, [active, follow, editing, segments]);

  // in-transcript search
  const nq = searchNorm(query.trim());
  const matches = useMemo(() => (nq ? segments.filter((s) => searchNorm(s.display_text).includes(nq)).map((s) => s.id)
    : []), [nq, segments]);
  useEffect(() => onMatches(matches.length), [matches.length, onMatches]);
  const currentMatch = matches.length ? matches[((matchIndex % matches.length) + matches.length) % matches.length] : null;
  useEffect(() => {
    if (currentMatch == null) return;
    scroller.current?.querySelector(`[data-seg="${currentMatch}"]`)?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [currentMatch]);

  const run = useCallback(async (fn: () => Promise<unknown>, ok?: string) => {
    try {
      await fn();
      if (ok) toast({ kind: "success", title: ok });
      onChanged();
    } catch (e) {
      toast({ kind: "error", title: "Could not save the change", body: String(e) });
    }
  }, [onChanged, toast]);

  const actions = useMemo(() => ({
    save: (s: Segment, text: string) => run(() => patch(`/api/segments/${s.id}`, { text })),
    reassign: (s: Segment, speakerId: number) => run(() => patch(`/api/segments/${s.id}`, { speaker_id: speakerId })),
    revert: (s: Segment) => run(() => post(`/api/segments/${s.id}/revert`), "Segment reverted"),
    mergeNext: (s: Segment) => {
      const i = segments.findIndex((x) => x.id === s.id);
      const next = segments[i + 1];
      if (next) run(() => post("/api/segments/merge", { ids: [s.id, next.id] }));
    },
    split: (s: Segment, caret: number) => {
      const w = wordIndexAtChar(s, caret);
      run(() => post(`/api/segments/${s.id}/split`, w != null ? { at_word: w } : { at_char: caret }));
    },
    rename: (sp: Speaker) => setRenaming(sp),
    newSpeaker: (s: Segment) => setNewSpeakerFor(s),
    copy: (s: Segment) => {
      const name = spk.get(s.speaker_id ?? -1)?.display_name ?? "";
      navigator.clipboard.writeText(`[${clock(s.start_sec, true)}] ${name}: ${s.display_text}`);
      toast({ kind: "info", title: "Copied" });
    },
    edit: (id: number | null) => setEditing(id),
  }), [run, segments, spk, toast]);

  if (!segments.length) {
    return <div className="flex h-full items-center justify-center text-[0.9rem] text-fg-3">No speech was found in this recording.</div>;
  }

  return (
    <div className="relative h-full">
      <div
        ref={scroller}
        className="h-full overflow-y-auto px-8 py-5"
        onWheel={() => { userScrollUntil.current = Date.now() + 4000; }}
        onKeyDown={(e) => { if (e.key === "PageDown" || e.key === "PageUp") userScrollUntil.current = Date.now() + 4000; }}
      >
        <div className="mx-auto max-w-[920px]">
          {segments.map((s, i) => {
            const prev = segments[i - 1];
            const showHeader = !prev || prev.speaker_id !== s.speaker_id || s.start_sec - prev.end_sec > 30;
            return (
              <Row
                key={s.id}
                seg={s}
                speaker={spk.get(s.speaker_id ?? -1)}
                speakers={speakers}
                showHeader={showHeader}
                isActive={i === active}
                activeWord={i === active ? word : -1}
                editing={editing === s.id}
                query={nq ? query.trim() : ""}
                isMatch={currentMatch === s.id}
                hasNext={i < segments.length - 1}
                actions={actions}
              />
            );
          })}
          <div className="h-24" />
        </div>
      </div>
      <div className="absolute bottom-3 right-6">
        <Button size="sm" variant={follow ? "subtle" : "secondary"} onClick={() => {
          setFollow(!follow);
          userScrollUntil.current = 0;
        }} aria-pressed={follow}>
          {follow ? "Following playback" : "Follow playback"}
        </Button>
      </div>
      {renaming && <RenameSpeaker sp={renaming} onClose={() => setRenaming(null)}
        onSave={(name) => run(() => patch(`/api/speakers/${renaming.id}`, { display_name: name }),
          `Renamed to ${name} everywhere in this meeting`).then(() => setRenaming(null))} />}
      {newSpeakerFor && <RenameSpeaker title="New speaker" onClose={() => setNewSpeakerFor(null)}
        onSave={(name) => run(async () => {
          const r = await post<{ id: number }>(`/api/sessions/${detail.session.id}/speakers`, { name });
          await patch(`/api/segments/${newSpeakerFor.id}`, { speaker_id: r.id });
        }).then(() => setNewSpeakerFor(null))} />}
    </div>
  );
}

type Actions = {
  save: (s: Segment, text: string) => Promise<void>;
  reassign: (s: Segment, id: number) => void;
  revert: (s: Segment) => void;
  mergeNext: (s: Segment) => void;
  split: (s: Segment, caret: number) => void;
  rename: (sp: Speaker) => void;
  newSpeaker: (s: Segment) => void;
  copy: (s: Segment) => void;
  edit: (id: number | null) => void;
};

const Row = memo(function Row({ seg, speaker, speakers, showHeader, isActive, activeWord, editing, query, isMatch,
  hasNext, actions }: {
  seg: Segment; speaker?: Speaker; speakers: Speaker[]; showHeader: boolean; isActive: boolean; activeWord: number;
  editing: boolean; query: string; isMatch: boolean; hasNext: boolean; actions: Actions;
}) {
  const color = speaker?.color ?? "#8c9bab";
  const edited = seg.edited_text !== null;
  const reassigned = seg.original_speaker_id !== null && seg.speaker_id !== seg.original_speaker_id;
  const speakerMenu = (open: () => void) => (
    <button onClick={open} className="inline-flex items-center gap-1.5 rounded-md px-1 py-0.5 text-[0.86rem] font-semibold hover:bg-card-hover"
      style={{ color }} aria-label={`Speaker ${speaker?.display_name ?? "unknown"}: change`}>
      <span className="h-2 w-2 rounded-full" style={{ background: color }} />
      {speaker?.display_name ?? "Unknown"}
    </button>
  );
  const menuItems = [
    ...speakers.map((sp) => ({ label: sp.display_name, checked: sp.id === seg.speaker_id,
      icon: <span className="block h-2.5 w-2.5 rounded-full" style={{ background: sp.color }} />,
      onClick: () => sp.id !== seg.speaker_id && actions.reassign(seg, sp.id) })),
    { separator: true, label: "" },
    ...(speaker ? [{ label: `Rename “${speaker.display_name}”…`, icon: <UserRoundPen size={14} />,
      onClick: () => actions.rename(speaker) }] : []),
    { label: "Assign to a new speaker…", icon: <UserPlus size={14} />, onClick: () => actions.newSpeaker(seg) },
  ];

  return (
    <div data-seg={seg.id}
      className={clsx("group relative -mx-3 rounded-xl px-3 transition-colors", showHeader ? "mt-4 pt-2 pb-1.5" : "py-1",
        isActive && "bg-accent-soft/60", isMatch && "ring-1 ring-warning/60")}>
      <span className="absolute left-0 top-2 bottom-2 w-[3px] rounded-full" style={{ background: color, opacity: isActive ? 1 : 0.35 }} />
      {showHeader && (
        <div className="mb-0.5 flex items-center gap-2">
          <Menu trigger={speakerMenu} items={menuItems} width={250} />
          <button className="text-[0.76rem] tabular-nums text-fg-3 hover:text-accent hover:underline"
            onClick={() => playerBus.seek(seg.start_sec)} aria-label={`Play from ${clock(seg.start_sec, true)}`}>
            {clock(seg.start_sec, true)}
          </button>
        </div>
      )}
      <div className="flex items-start gap-2">
        {!showHeader && (
          <button className="mt-[0.3rem] w-[3.6rem] shrink-0 text-left text-[0.7rem] tabular-nums text-fg-3 opacity-0 group-hover:opacity-100 hover:text-accent focus:opacity-100"
            onClick={() => playerBus.seek(seg.start_sec)}>{clock(seg.start_sec, true)}</button>
        )}
        <div className={clsx("min-w-0 flex-1", !showHeader && "-ml-[3.6rem] group-hover:ml-0 transition-[margin]")}>
          {editing ? <Editor seg={seg} actions={actions} /> : (
            <p className="transcript-text selectable cursor-text whitespace-pre-wrap break-words text-fg"
              lang={seg.language === "hi" ? "hi" : "en"}
              onDoubleClick={() => actions.edit(seg.id)}>
              {query ? <Highlighted text={seg.display_text} q={query} />
                : !edited && seg.words.length ? seg.words.map((w, i) => (
                  <span key={i}>
                    {i > 0 ? " " : ""}
                    <span
                      onClick={() => playerBus.seek(w.start)}
                      title={w.confidence != null && w.confidence < 0.5 ? `Low confidence (${Math.round(w.confidence * 100)}%)` : undefined}
                      className={clsx("cursor-pointer rounded-[4px] transition-colors hover:text-accent",
                        i === activeWord && "word-active",
                        w.confidence != null && w.confidence < 0.5 && "underline decoration-dotted decoration-fg-3 underline-offset-4")}
                    >{w.text}</span>
                  </span>
                )) : <span onClick={() => playerBus.seek(seg.start_sec)}>{seg.display_text}</span>}
            </p>
          )}
          <div className="mt-0.5 flex items-center gap-1.5 text-[0.68rem] text-fg-3">
            {seg.language && <span>{LANG_LABEL[seg.language] ?? seg.language}</span>}
            {seg.overlap_flag ? <span className="inline-flex items-center gap-0.5 text-warning" title="Several people speak at once here"><Layers size={11} /> overlap</span> : null}
            {edited && <span className="text-accent">edited</span>}
            {reassigned && <span className="text-accent">speaker changed</span>}
          </div>
        </div>
        {!editing && (
          <div className="flex shrink-0 items-center opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
            {!showHeader && <Menu align="right" trigger={(open) => (
              <IconButton label="Change speaker" onClick={open} className="h-7 w-7"><Users size={14} /></IconButton>
            )} items={menuItems} width={250} />}
            <IconButton label="Edit text" className="h-7 w-7" onClick={() => actions.edit(seg.id)}><Pencil size={14} /></IconButton>
            {hasNext && <IconButton label="Merge with next segment" className="h-7 w-7" onClick={() => actions.mergeNext(seg)}><Merge size={14} /></IconButton>}
            {(edited || reassigned) && <IconButton label="Revert to original" className="h-7 w-7" onClick={() => actions.revert(seg)}><Undo2 size={14} /></IconButton>}
            <IconButton label="Copy" className="h-7 w-7" onClick={() => actions.copy(seg)}><Copy size={14} /></IconButton>
          </div>
        )}
      </div>
    </div>
  );
});

function Editor({ seg, actions }: { seg: Segment; actions: Actions }) {
  const [text, setText] = useState(seg.display_text);
  const ref = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    const t = ref.current;
    if (t) {
      t.focus();
      t.selectionStart = t.selectionEnd = t.value.length;
    }
  }, []);
  useEffect(() => {
    const t = ref.current;
    if (t) {
      t.style.height = "auto";
      t.style.height = `${t.scrollHeight + 2}px`;
    }
  }, [text]);
  const save = async () => {
    if (text.trim() && text !== seg.display_text) await actions.save(seg, text);
    actions.edit(null);
  };
  return (
    <div>
      <textarea
        ref={ref}
        value={text}
        lang={seg.language === "hi" ? "hi" : "en"}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            save();
          } else if (e.key === "Escape") actions.edit(null);
        }}
        aria-label="Edit segment text"
        className="transcript-text w-full resize-none rounded-lg border border-accent bg-layer-2 px-2.5 py-1.5 text-fg focus:outline-none"
      />
      <div className="mt-1 flex items-center gap-1.5">
        <Button size="sm" variant="primary" icon={<Check size={14} />} onClick={save}>Save</Button>
        <Button size="sm" variant="ghost" onClick={() => actions.edit(null)}>Cancel</Button>
        <Button size="sm" variant="ghost" icon={<Scissors size={14} />}
          disabled={text !== seg.display_text}
          title={text !== seg.display_text ? "Save your text changes first" : "Split this segment at the cursor"}
          onClick={() => {
            const caret = ref.current?.selectionStart ?? 0;
            if (caret > 0 && caret < text.length) {
              actions.split(seg, caret);
              actions.edit(null);
            }
          }}>Split at cursor</Button>
        <span className="ml-auto inline-flex items-center gap-1 text-[0.7rem] text-fg-3"><CornerDownLeft size={11} /> save · Esc cancel</span>
      </div>
    </div>
  );
}

function Highlighted({ text, q }: { text: string; q: string }) {
  const nt = searchNorm(text);
  const nq = searchNorm(q);
  if (!nq || nt.length !== text.normalize("NFC").length) {
    // normalization changed the length (nukta/zero-width): highlight the whole segment instead of offsets
    return nq && nt.includes(nq) ? <mark className="hit">{text}</mark> : <>{text}</>;
  }
  const src = text.normalize("NFC");
  const out: React.ReactNode[] = [];
  let pos = 0;
  let i = nt.indexOf(nq);
  let k = 0;
  while (i >= 0) {
    out.push(src.slice(pos, i), <mark key={k++} className="hit current">{src.slice(i, i + nq.length)}</mark>);
    pos = i + nq.length;
    i = nt.indexOf(nq, pos);
  }
  out.push(src.slice(pos));
  return <>{out}</>;
}

function RenameSpeaker({ sp, title, onClose, onSave }: {
  sp?: Speaker; title?: string; onClose: () => void; onSave: (name: string) => void;
}) {
  const [name, setName] = useState(sp?.display_name ?? "");
  return (
    <Modal title={title ?? "Rename speaker"} onClose={onClose} width={420} footer={<>
      <Button variant="ghost" onClick={onClose}>Cancel</Button>
      <Button variant="primary" disabled={!name.trim()} onClick={() => onSave(name.trim())}>Save</Button>
    </>}>
      {sp && <p className="mb-3 text-[0.84rem] text-fg-2">The new name is used for every segment of {sp.display_name} in this meeting and in exports.</p>}
      <input autoFocus value={name} onChange={(e) => setName(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && name.trim() && onSave(name.trim())}
        placeholder="e.g. Rahul Sharma / राहुल शर्मा" aria-label="Speaker name"
        className="h-10 w-full rounded-lg border border-stroke bg-card px-3 text-[0.92rem] focus:outline-none focus:ring-2 focus:ring-accent" />
    </Modal>
  );
}
