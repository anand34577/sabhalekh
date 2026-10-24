import { create } from "zustand";
import { get as apiGet } from "./lib/api";
import type { HardwareStatus, Job, Levels, RecordingStatus, Session, Settings } from "./lib/types";

export type View = "session" | "recording" | "queue" | "settings" | "empty";

export interface Toast {
  id: number;
  kind: "info" | "success" | "error" | "warning";
  title: string;
  body?: string;
  action?: { label: string; run: () => void };
}

export interface HistoryFilters {
  status: string;
  language: string;
  source: string;
  tag: string;
  sort: "date" | "duration" | "title";
  order: "asc" | "desc";
  days: number; // 0 = any time
}

interface State {
  backend: "starting" | "ready" | "exited";
  backendError: string | null;
  connected: boolean;
  view: View;
  selectedId: number | null;
  sessions: Session[];
  query: string;
  filters: HistoryFilters;
  jobs: Job[];
  hardware: HardwareStatus | null;
  settings: Settings | null;
  recording: RecordingStatus;
  toasts: Toast[];
  transcriptVersion: number; // bump to reload the open transcript
  windowsBuild: number;
  set: (p: Partial<State>) => void;
  select: (id: number | null) => void;
  toast: (t: Omit<Toast, "id">) => void;
  dismiss: (id: number) => void;
  refreshSessions: () => Promise<void>;
  refreshJobs: () => Promise<void>;
}

let toastId = 1;

export const useStore = create<State>((set, get) => ({
  backend: "starting",
  backendError: null,
  connected: false,
  view: "empty",
  selectedId: null,
  sessions: [],
  query: "",
  filters: { status: "", language: "", source: "", tag: "", sort: "date", order: "desc", days: 0 },
  jobs: [],
  hardware: null,
  settings: null,
  recording: { active: false },
  toasts: [],
  transcriptVersion: 0,
  windowsBuild: 0,
  set: (p) => set(p),
  select: (id) => set({ selectedId: id, view: id ? "session" : "empty" }),
  toast: (t) => {
    const id = toastId++;
    set({ toasts: [...get().toasts, { ...t, id }] });
    setTimeout(() => get().dismiss(id), t.kind === "error" ? 9000 : 5000);
  },
  dismiss: (id) => set({ toasts: get().toasts.filter((t) => t.id !== id) }),
  refreshSessions: async () => {
    const { filters: f } = get();
    const q = new URLSearchParams({ sort: f.sort, order: f.order });
    if (f.status) q.set("status", f.status);
    if (f.language) q.set("language", f.language);
    if (f.source) q.set("source", f.source);
    if (f.tag) q.set("tag", f.tag);
    if (f.days) q.set("date_from", String(Date.now() / 1000 - f.days * 86400));
    set({ sessions: await apiGet<Session[]>(`/api/sessions?${q}`) });
  },
  refreshJobs: async () => set({ jobs: await apiGet<Job[]>("/api/jobs") }),
}));

/** High-rate recorder levels live outside React state; components subscribe to it directly. */
type LevelListener = (l: { mic?: Levels; system?: Levels; elapsed: number }) => void;
const levelListeners = new Set<LevelListener>();
export const levels = {
  emit: (l: { mic?: Levels; system?: Levels; elapsed: number }) => levelListeners.forEach((f) => f(l)),
  subscribe: (f: LevelListener) => {
    levelListeners.add(f);
    return () => {
      levelListeners.delete(f);
    };
  },
};

/** Current playback time, published by the player every animation frame while playing. */
type TimeListener = (t: number, playing: boolean) => void;
const timeListeners = new Set<TimeListener>();
export const timeBus = {
  last: 0,
  emit: (t: number, playing: boolean) => {
    timeBus.last = t;
    timeListeners.forEach((f) => f(t, playing));
  },
  subscribe: (f: TimeListener) => {
    timeListeners.add(f);
    return () => {
      timeListeners.delete(f);
    };
  },
};

/** Player position, shared by the transcript (karaoke) and the docked player without re-rendering the app. */
type SeekListener = (t: number, play: boolean) => void;
const seekListeners = new Set<SeekListener>();
export const playerBus = {
  seek: (t: number, play = true) => seekListeners.forEach((f) => f(t, play)),
  onSeek: (f: SeekListener) => {
    seekListeners.add(f);
    return () => {
      seekListeners.delete(f);
    };
  },
};
