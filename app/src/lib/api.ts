/** Connection to the local backend sidecar: 127.0.0.1 only, per-launch bearer token from the Rust shell. */
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import type { BackendEvent } from "./types";

export interface BackendInfo {
  status: "starting" | "ready" | "exited";
  port: number;
  token: string;
  error: string | null;
}

let base = "";
let token = "";

export function configure(info: BackendInfo) {
  base = `http://127.0.0.1:${info.port}`;
  token = info.token;
}

export function mediaUrl(path: string): string {
  return `${base}${path}${path.includes("?") ? "&" : "?"}token=${encodeURIComponent(token)}`;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export async function api<T = unknown>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const headers: Record<string, string> = { Authorization: `Bearer ${token}` };
  let body = init.body;
  if (init.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(init.json);
  }
  const res = await fetch(base + path, { ...init, body, headers: { ...headers, ...(init.headers as object) } });
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const j = await res.json();
      msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, msg);
  }
  const ct = res.headers.get("content-type") || "";
  return (ct.includes("application/json") ? res.json() : res.text()) as Promise<T>;
}

export const get = <T>(p: string) => api<T>(p);
export const post = <T>(p: string, json?: unknown) => api<T>(p, { method: "POST", json: json ?? {} });
export const put = <T>(p: string, json: unknown) => api<T>(p, { method: "PUT", json });
export const patch = <T>(p: string, json: unknown) => api<T>(p, { method: "PATCH", json });
export const del = <T>(p: string) => api<T>(p, { method: "DELETE" });

export const isTauri = () => typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

/** Wait for the sidecar, then keep a WebSocket open to its event stream (auto-reconnect). */
export async function connectBackend(
  onReady: (info: BackendInfo) => void,
  onExit: (info: BackendInfo) => void,
): Promise<() => void> {
  if (!isTauri()) {
    // development/UI tests in a plain browser: http://localhost:1420/?port=PORT&token=TOKEN
    const q = new URLSearchParams(location.search);
    const info: BackendInfo = { status: "ready", port: Number(q.get("port")), token: q.get("token") ?? "", error: null };
    if (info.port && info.token) {
      configure(info);
      onReady(info);
    } else onExit({ ...info, status: "exited", error: "Open this page from the Sabhalekh app (or pass ?port=&token= in development)." });
    return () => {};
  }
  const unReady = await listen<BackendInfo>("backend://ready", (e) => {
    configure(e.payload);
    onReady(e.payload);
  });
  const unExit = await listen<BackendInfo>("backend://exited", (e) => onExit(e.payload));
  const info = await invoke<BackendInfo>("backend_info");
  if (info.status === "ready") {
    configure(info);
    onReady(info);
  } else if (info.status === "exited") onExit(info);
  return () => {
    unReady();
    unExit();
  };
}

export function openEvents(onEvent: (e: BackendEvent) => void, onState: (connected: boolean) => void): () => void {
  let ws: WebSocket | null = null;
  let closed = false;
  let retry = 500;
  const open = () => {
    ws = new WebSocket(`${base.replace("http", "ws")}/api/events?token=${encodeURIComponent(token)}`);
    ws.onopen = () => {
      retry = 500;
      onState(true);
    };
    ws.onmessage = (m) => {
      try {
        onEvent(JSON.parse(m.data));
      } catch {
        /* ignore malformed */
      }
    };
    ws.onclose = () => {
      onState(false);
      if (!closed) setTimeout(open, (retry = Math.min(retry * 2, 5000)));
    };
  };
  open();
  return () => {
    closed = true;
    ws?.close();
  };
}
