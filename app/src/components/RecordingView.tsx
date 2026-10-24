import { Headphones, Mic, Monitor, Pause, Play, Square } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { clock } from "../lib/format";
import type { Levels } from "../lib/types";
import { levels, useStore } from "../store";
import { Button } from "./ui";

export function RecordingView({ onPause, onResume, onStop }: {
  onPause: () => void; onResume: () => void; onStop: () => void;
}) {
  const recording = useStore((s) => s.recording);
  const [elapsed, setElapsed] = useState(recording.elapsed ?? 0);
  const canvas = useRef<HTMLCanvasElement>(null);
  const mic = useRef<Levels | undefined>(undefined);
  const sys = useRef<Levels | undefined>(undefined);
  const micBar = useRef<HTMLDivElement>(null);
  const sysBar = useRef<HTMLDivElement>(null);

  useEffect(() => levels.subscribe((l) => {
    mic.current = l.mic;
    sys.current = l.system;
    setElapsed(l.elapsed);
  }), []);

  // smooth visualizer: two mirrored spectra (mic above, system below), decaying between updates
  useEffect(() => {
    let raf = 0;
    const shownMic = new Array(24).fill(0);
    const shownSys = new Array(24).fill(0);
    const draw = () => {
      const c = canvas.current;
      if (c) {
        const dpr = window.devicePixelRatio || 1;
        const r = c.getBoundingClientRect();
        if (c.width !== Math.round(r.width * dpr)) {
          c.width = Math.round(r.width * dpr);
          c.height = Math.round(r.height * dpr);
        }
        const ctx = c.getContext("2d")!;
        const W = c.width;
        const H = c.height;
        ctx.clearRect(0, 0, W, H);
        const paused = useStore.getState().recording.paused;
        const n = 24;
        const gap = 6 * dpr;
        const bw = (W - gap * (n - 1)) / n;
        const mid = H / 2;
        for (let i = 0; i < n; i++) {
          const tm = paused ? 0 : (mic.current?.bands[i] ?? 0);
          const ts = paused ? 0 : (sys.current?.bands[i] ?? 0);
          shownMic[i] = Math.max(tm, shownMic[i] * 0.88);
          shownSys[i] = Math.max(ts, shownSys[i] * 0.88);
          const x = i * (bw + gap);
          const hm = Math.max(3 * dpr, shownMic[i] * (mid - 8 * dpr));
          const hs = Math.max(3 * dpr, shownSys[i] * (mid - 8 * dpr));
          ctx.fillStyle = "#60a5fa";
          ctx.globalAlpha = 0.9;
          ctx.beginPath();
          ctx.roundRect(x, mid - 2 * dpr - hm, bw, hm, bw / 3);
          ctx.fill();
          ctx.fillStyle = "#a78bfa";
          ctx.beginPath();
          ctx.roundRect(x, mid + 2 * dpr, bw, hs, bw / 3);
          ctx.fill();
        }
        ctx.globalAlpha = 1;
        if (micBar.current) micBar.current.style.width = `${Math.min(100, (paused ? 0 : mic.current?.rms ?? 0) * 100)}%`;
        if (sysBar.current) sysBar.current.style.width = `${Math.min(100, (paused ? 0 : sys.current?.rms ?? 0) * 100)}%`;
      }
      raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, []);

  const devices = recording.devices ?? {};
  return (
    <div className="flex h-full flex-col items-center justify-center bg-layer px-8">
      <div className="w-full max-w-3xl fade-in">
        <div className="flex items-center justify-center gap-2.5 text-[0.95rem] font-medium">
          <span className={recording.paused ? "h-3 w-3 rounded-full bg-warning" : "rec-dot h-3 w-3 rounded-full bg-rec"} />
          {recording.paused ? "Paused" : "Recording"}
          <span className="text-fg-3">·</span>
          <span className="max-w-[24rem] truncate text-fg-2">{recording.title}</span>
        </div>
        <div className="mt-3 text-center font-light tabular-nums tracking-tight text-fg" style={{ fontSize: "4.2rem" }}
          aria-live="off" aria-label="Elapsed time">
          {clock(elapsed, true)}
        </div>
        <canvas ref={canvas} className="mt-6 h-48 w-full" aria-hidden="true" />
        <div className="mt-6 grid grid-cols-2 gap-4">
          <Meter icon={<Mic size={15} />} label="You (microphone)" device={devices.mic} barRef={micBar} color="#60a5fa" />
          <Meter icon={<Monitor size={15} />} label="Others (system audio)" device={devices.system} barRef={sysBar} color="#a78bfa" />
        </div>
        <div className="mt-8 flex items-center justify-center gap-3">
          {recording.paused ? (
            <Button size="lg" icon={<Play size={18} />} onClick={onResume}>Resume</Button>
          ) : (
            <Button size="lg" icon={<Pause size={18} />} onClick={onPause}>Pause</Button>
          )}
          <Button size="lg" variant="danger" icon={<Square size={16} fill="currentColor" />} onClick={onStop}>Stop & save</Button>
        </div>
        <p className="mx-auto mt-6 max-w-xl text-center text-[0.78rem] leading-relaxed text-fg-3">
          <Headphones size={13} className="mr-1.5 inline-block align-[-2px]" />
          Audio is saved to disk as it records, so nothing is lost if the PC crashes. Headphones give the cleanest
          separation between your voice and everyone else.
        </p>
      </div>
    </div>
  );
}

function Meter({ icon, label, device, barRef, color }: {
  icon: React.ReactNode; label: string; device?: string | null; barRef: React.RefObject<HTMLDivElement | null>; color: string;
}) {
  return (
    <div className="rounded-xl border border-stroke bg-card p-3.5">
      <div className="flex items-center gap-2 text-[0.84rem] font-medium" style={{ color }}>{icon}<span className="text-fg">{label}</span></div>
      <div className="mt-0.5 truncate text-[0.74rem] text-fg-3" title={device ?? ""}>{device ?? "Not available"}</div>
      <div className="mt-2.5 h-2 overflow-hidden rounded-full bg-stroke">
        <div ref={barRef} className="h-full rounded-full transition-[width] duration-75" style={{ background: color, width: "0%" }} />
      </div>
    </div>
  );
}
