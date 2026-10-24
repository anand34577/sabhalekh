import { Pause, Play, RotateCcw, RotateCw, Volume2, VolumeX } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { get, mediaUrl } from "../lib/api";
import { clock } from "../lib/format";
import type { Peaks, Segment, Speaker } from "../lib/types";
import { playerBus, timeBus } from "../store";
import { IconButton, Menu } from "./ui";

const SPEEDS = [0.5, 0.75, 1, 1.25, 1.5, 1.75, 2];

function cssVar(name: string) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

export function Player({ sessionId, duration, segments, speakers, hasAudio, version }: {
  sessionId: number; duration: number; segments: Segment[]; speakers: Speaker[]; hasAudio: boolean; version: number;
}) {
  const audio = useRef<HTMLAudioElement>(null);
  const wave = useRef<HTMLCanvasElement>(null);
  const timeline = useRef<HTMLCanvasElement>(null);
  const [peaks, setPeaks] = useState<Peaks | null>(null);
  const [playing, setPlaying] = useState(false);
  const [t, setT] = useState(0);
  const [dur, setDur] = useState(duration);
  const [rate, setRate] = useState(1);
  const [vol, setVol] = useState(1);
  const [muted, setMuted] = useState(false);
  const [hover, setHover] = useState<{ x: number; t: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const dragging = useRef(false);

  useEffect(() => {
    setPeaks(null);
    setT(0);
    setPlaying(false);
    setError(null);
    timeBus.emit(0, false);
    get<Peaks>(`/api/sessions/${sessionId}/peaks`).then(setPeaks).catch(() => setPeaks(null));
  }, [sessionId, version]);

  useEffect(() => setDur(duration || peaks?.duration || 0), [duration, peaks]);

  // publish the playback position every frame while playing (karaoke highlighting)
  useEffect(() => {
    let raf = 0;
    const tick = () => {
      const a = audio.current;
      if (a) {
        timeBus.emit(a.currentTime, !a.paused);
        if (!dragging.current) setT(a.currentTime);
      }
      raf = requestAnimationFrame(tick);
    };
    if (playing) raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing]);

  const seek = useCallback((time: number, play = false) => {
    const a = audio.current;
    if (!a) return;
    const v = Math.max(0, Math.min(time, dur || a.duration || 0));
    a.currentTime = v;
    setT(v);
    timeBus.emit(v, !a.paused);
    if (play && a.paused) a.play().catch((e) => setError(String(e)));
  }, [dur]);

  useEffect(() => playerBus.onSeek((time, play) => seek(time, play)), [seek]);

  const toggle = useCallback(() => {
    const a = audio.current;
    if (!a) return;
    if (a.paused) a.play().catch((e) => setError(String(e)));
    else a.pause();
  }, []);

  // keyboard: Space play/pause, arrows ±10 s (ignored while typing)
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement;
      if (el.closest("input, textarea, select, [contenteditable='true'], [role='dialog']")) return;
      if (e.code === "Space") {
        e.preventDefault();
        toggle();
      } else if (e.key === "ArrowLeft" && !e.ctrlKey) {
        e.preventDefault();
        seek((audio.current?.currentTime ?? 0) - 10);
      } else if (e.key === "ArrowRight" && !e.ctrlKey) {
        e.preventDefault();
        seek((audio.current?.currentTime ?? 0) + 10);
      }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [toggle, seek]);

  // ------------------------------------------------------------------ drawing
  const draw = useCallback(() => {
    const c = wave.current;
    const tl = timeline.current;
    if (!c || !tl) return;
    const dpr = window.devicePixelRatio || 1;
    for (const cv of [c, tl]) {
      const r = cv.getBoundingClientRect();
      if (cv.width !== Math.round(r.width * dpr) || cv.height !== Math.round(r.height * dpr)) {
        cv.width = Math.round(r.width * dpr);
        cv.height = Math.round(r.height * dpr);
      }
    }
    const W = c.width;
    const H = c.height;
    const ctx = c.getContext("2d")!;
    ctx.clearRect(0, 0, W, H);
    const accent = cssVar("--accent") || "#4f8ef7";
    const dim = cssVar("--fg-3") || "#888";
    const total = dur || 1;
    const playedX = (t / total) * W;
    const bar = Math.max(2, Math.round(2 * dpr));
    const gap = Math.max(1, Math.round(1 * dpr));
    const n = Math.floor(W / (bar + gap));
    const p = peaks?.peaks ?? [];
    for (let i = 0; i < n; i++) {
      let v = 0.04;
      if (p.length) {
        const a = Math.floor((i / n) * p.length);
        const b = Math.max(a + 1, Math.floor(((i + 1) / n) * p.length));
        let m = 0;
        for (let k = a; k < b && k < p.length; k++) m = Math.max(m, p[k]);
        v = Math.max(0.04, m / 255);
      }
      const h = v * (H - 4);
      const x = i * (bar + gap);
      ctx.fillStyle = x < playedX ? accent : dim;
      ctx.globalAlpha = x < playedX ? 1 : 0.55;
      ctx.beginPath();
      ctx.roundRect(x, (H - h) / 2, bar, h, bar / 2);
      ctx.fill();
    }
    ctx.globalAlpha = 1;
    // speaker timeline (matches the transcript: drawn from its segments)
    const tctx = tl.getContext("2d")!;
    const TW = tl.width;
    const TH = tl.height;
    tctx.clearRect(0, 0, TW, TH);
    tctx.fillStyle = cssVar("--stroke") || "#333";
    tctx.fillRect(0, TH / 2 - 1, TW, 2);
    const colors = new Map(speakers.map((s) => [s.id, s.color]));
    for (const s of segments) {
      const x0 = (s.start_sec / total) * TW;
      const x1 = Math.max(x0 + 2, (s.end_sec / total) * TW);
      tctx.fillStyle = colors.get(s.speaker_id ?? -1) ?? "#888";
      tctx.beginPath();
      tctx.roundRect(x0, 1, x1 - x0, TH - 2, 3 * dpr);
      tctx.fill();
      if (s.overlap_flag) {
        tctx.fillStyle = "rgba(255,255,255,0.55)";
        tctx.fillRect(x0, 0, x1 - x0, 2 * dpr);
      }
    }
    tctx.fillStyle = cssVar("--fg") || "#fff";
    tctx.fillRect(Math.round((t / total) * TW) - dpr, 0, 2 * dpr, TH);
  }, [peaks, t, dur, segments, speakers]);

  useEffect(() => {
    draw();
  }, [draw]);
  useEffect(() => {
    const ro = new ResizeObserver(() => draw());
    if (wave.current) ro.observe(wave.current);
    return () => ro.disconnect();
  }, [draw]);

  const timeAt = (e: React.PointerEvent | React.MouseEvent, el: HTMLElement) => {
    const r = el.getBoundingClientRect();
    return { x: e.clientX - r.left, t: Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)) * (dur || 0) };
  };

  const speakerAt = (time: number) => {
    const s = segments.find((g) => g.start_sec <= time && time <= g.end_sec);
    return s ? speakers.find((sp) => sp.id === s.speaker_id)?.display_name : undefined;
  };

  return (
    <div className="border-t border-stroke bg-layer px-5 pb-3 pt-2.5">
      {hasAudio ? (
        <audio
          ref={audio}
          src={mediaUrl(`/api/sessions/${sessionId}/audio`) + `&v=${version}`}
          preload="metadata"
          onPlay={() => setPlaying(true)}
          onPause={() => { setPlaying(false); timeBus.emit(audio.current?.currentTime ?? 0, false); }}
          onEnded={() => setPlaying(false)}
          onLoadedMetadata={(e) => { if (isFinite(e.currentTarget.duration)) setDur(e.currentTarget.duration); }}
          onError={() => setError("The audio file could not be played.")}
        />
      ) : null}
      <div className="relative">
        <canvas
          ref={wave}
          className="h-14 w-full cursor-pointer"
          aria-label="Waveform: click to seek"
          onPointerDown={(e) => {
            if (!hasAudio) return;
            dragging.current = true;
            (e.target as HTMLElement).setPointerCapture(e.pointerId);
            setT(timeAt(e, e.currentTarget).t);
          }}
          onPointerMove={(e) => {
            const h = timeAt(e, e.currentTarget);
            setHover(h);
            if (dragging.current) setT(h.t);
          }}
          onPointerUp={(e) => {
            if (!dragging.current) return;
            dragging.current = false;
            seek(timeAt(e, e.currentTarget).t);
          }}
          onPointerLeave={() => setHover(null)}
        />
        <canvas
          ref={timeline}
          className="mt-1.5 h-2.5 w-full cursor-pointer rounded"
          aria-label="Speaker timeline: click to seek"
          onClick={(e) => hasAudio && seek(timeAt(e, e.currentTarget).t, true)}
          onPointerMove={(e) => setHover(timeAt(e, e.currentTarget))}
          onPointerLeave={() => setHover(null)}
        />
        {hover && (
          <div className="pointer-events-none absolute -top-7 rounded-md border border-stroke bg-layer-2 px-1.5 py-0.5 text-[0.7rem] tabular-nums shadow"
            style={{ left: Math.max(0, hover.x - 30) }}>
            {clock(hover.t)}{speakerAt(hover.t) ? ` · ${speakerAt(hover.t)}` : ""}
          </div>
        )}
      </div>
      <div className="mt-2 flex items-center gap-1.5">
        <IconButton label="Back 10 seconds" onClick={() => seek(t - 10)} disabled={!hasAudio}><RotateCcw size={17} /></IconButton>
        <button
          onClick={toggle}
          disabled={!hasAudio}
          aria-label={playing ? "Pause" : "Play"}
          className="flex h-10 w-10 items-center justify-center rounded-full bg-accent text-white shadow hover:brightness-110 disabled:opacity-40"
        >
          {playing ? <Pause size={19} fill="currentColor" /> : <Play size={19} fill="currentColor" className="ml-0.5" />}
        </button>
        <IconButton label="Forward 10 seconds" onClick={() => seek(t + 10)} disabled={!hasAudio}><RotateCw size={17} /></IconButton>
        <span className="ml-2 text-[0.82rem] tabular-nums text-fg-2">{clock(t, dur >= 3600)} / {clock(dur, dur >= 3600)}</span>
        {error && <span className="ml-3 text-[0.78rem] text-danger">{error}</span>}
        {!hasAudio && <span className="ml-3 text-[0.78rem] text-fg-3">Audio was deleted; the transcript is kept.</span>}
        <div className="ml-auto flex items-center gap-1">
          <Menu align="right" width={120} trigger={(open) => (
            <button onClick={open} className="h-8 rounded-md px-2 text-[0.8rem] font-medium tabular-nums text-fg-2 hover:bg-card-hover"
              aria-label="Playback speed">{rate}×</button>
          )} items={SPEEDS.map((s) => ({ label: `${s}×`, checked: s === rate, onClick: () => {
            setRate(s);
            if (audio.current) audio.current.playbackRate = s;
          } }))} />
          <IconButton label={muted ? "Unmute" : "Mute"} onClick={() => {
            setMuted(!muted);
            if (audio.current) audio.current.muted = !muted;
          }}>{muted || vol === 0 ? <VolumeX size={17} /> : <Volume2 size={17} />}</IconButton>
          <input type="range" min={0} max={1} step={0.05} value={muted ? 0 : vol} aria-label="Volume"
            className="w-24 accent-[var(--accent)]"
            onChange={(e) => {
              const v = Number(e.target.value);
              setVol(v);
              setMuted(false);
              if (audio.current) { audio.current.volume = v; audio.current.muted = false; }
            }} />
        </div>
      </div>
    </div>
  );
}
