import clsx from "clsx";
import { Copy, Lock, Minus, Square, X } from "lucide-react";
import { useEffect, useState } from "react";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { isTauri } from "../lib/api";
import { isMac } from "../lib/platform";
import { levels, useStore } from "../store";
import { clock } from "../lib/format";

/** Whole seconds of the running recording, re-rendering once a second instead of at the meter rate. */
function useElapsed(active: boolean) {
  const [sec, setSec] = useState(0);
  useEffect(() => {
    if (!active) return setSec(0);
    return levels.subscribe((l) => setSec((prev) => (Math.floor(l.elapsed) === prev ? prev : Math.floor(l.elapsed))));
  }, [active]);
  return sec;
}

function WindowButton({ label, onClick, danger, children }:
  { label: string; onClick: () => void; danger?: boolean; children: React.ReactNode }) {
  return (
    <button type="button" aria-label={label} title={label} onClick={onClick} tabIndex={-1}
      className={clsx("flex h-full w-[46px] items-center justify-center text-fg-2 transition-colors",
        danger ? "hover:bg-rec hover:text-white" : "hover:bg-card-hover hover:text-fg")}>
      {children}
    </button>
  );
}

/**
 * The app's own title bar. The system one is removed in the Rust shell on Windows and Linux; on macOS the native
 * traffic lights stay (overlay style), so only a spacer is reserved for them there.
 */
export function TitleBar() {
  const recording = useStore((s) => s.recording);
  const title = useStore((s) => (s.view === "session" ? s.sessions.find((x) => x.id === s.selectedId)?.title : ""));
  const elapsed = useElapsed(recording.active);
  const [maximized, setMaximized] = useState(false);

  useEffect(() => {
    if (!isTauri() || isMac) return;
    const win = getCurrentWindow();
    const sync = () => win.isMaximized().then(setMaximized).catch(() => {});
    sync();
    const un = win.onResized(sync);
    return () => {
      un.then((f) => f());
    };
  }, []);

  if (!isTauri()) return null;
  const win = getCurrentWindow();

  return (
    <header data-tauri-drag-region
      className="relative z-[60] flex h-9 shrink-0 select-none items-center text-[0.8rem]">
      {isMac && <div data-tauri-drag-region className="h-full w-[78px] shrink-0" />}
      <div data-tauri-drag-region className="pointer-events-none flex items-center gap-2 pl-3 pr-4">
        <img src="/icon.png" alt="" className="h-4 w-4 rounded-[4px]" draggable={false} />
        <span className="font-medium text-fg-2">Sabhalekh</span>
        <span className="ml-1 flex items-center gap-1 text-[0.7rem] text-fg-3" title="Nothing ever leaves this PC">
          <Lock size={11} /> Offline
        </span>
      </div>
      <div data-tauri-drag-region className="pointer-events-none flex min-w-0 flex-1 items-center justify-center px-2">
        {recording.active ? (
          <span className="flex items-center gap-2 rounded-full bg-rec/15 px-3 py-0.5 font-medium text-fg">
            <span className={clsx("h-2 w-2 rounded-full bg-rec", !recording.paused && "rec-dot")} />
            {recording.paused ? "Paused" : "Recording"} <span className="tabular-nums text-fg-2">{clock(elapsed, true)}</span>
          </span>
        ) : title ? <span className="truncate text-fg-3">{title}</span> : null}
      </div>
      {!isMac && (
        <div className="flex h-full shrink-0">
          <WindowButton label="Minimize" onClick={() => win.minimize()}><Minus size={15} /></WindowButton>
          <WindowButton label={maximized ? "Restore" : "Maximize"} onClick={() => win.toggleMaximize()}>
            {maximized ? <Copy size={12} className="-scale-x-100" /> : <Square size={12} />}
          </WindowButton>
          <WindowButton label="Close" danger onClick={() => win.close()}><X size={16} /></WindowButton>
        </div>
      )}
    </header>
  );
}
