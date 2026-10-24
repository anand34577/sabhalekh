export function clock(sec: number, withHours = false): string {
  const s = Math.max(0, Math.floor(sec || 0));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const ss = s % 60;
  const mm = String(m).padStart(2, "0");
  const sss = String(ss).padStart(2, "0");
  return h > 0 || withHours ? `${String(h).padStart(2, "0")}:${mm}:${sss}` : `${mm}:${sss}`;
}

export function duration(sec: number): string {
  const s = Math.round(sec || 0);
  if (s < 60) return `${s}s`;
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return h ? `${h}h ${m}m` : `${m}m ${s % 60 ? `${s % 60}s` : ""}`.trim();
}

export function eta(sec: number | null | undefined): string {
  if (sec == null || !isFinite(sec)) return "estimating…";
  if (sec < 60) return `${Math.max(1, Math.round(sec))}s left`;
  return `${Math.round(sec / 60)} min left`;
}

export function date(ts: number): string {
  const d = new Date(ts * 1000);
  const now = new Date();
  const sameDay = d.toDateString() === now.toDateString();
  const yest = new Date(now.getTime() - 86400000).toDateString() === d.toDateString();
  const time = d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  if (sameDay) return `Today, ${time}`;
  if (yest) return `Yesterday, ${time}`;
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) + `, ${time}`;
}

export function bytes(n: number): string {
  if (n < 1024) return `${n} B`;
  const u = ["KB", "MB", "GB", "TB"];
  let i = -1;
  do {
    n /= 1024;
    i++;
  } while (n >= 1024 && i < u.length - 1);
  return `${n.toFixed(n >= 100 ? 0 : 1)} ${u[i]}`;
}

export const LANG_LABEL: Record<string, string> = { en: "EN", hi: "HI", mixed: "EN+HI" };
export const STAGE_LABEL: Record<string, string> = {
  extract: "Extracting audio",
  vad: "Finding speech",
  diarize: "Identifying speakers",
  transcribe: "Transcribing",
  align: "Aligning speakers",
  save: "Saving",
};

export function nfc(s: string): string {
  return s.normalize("NFC");
}

/** Search-normalized text: NFC, no zero-width joiners, no nukta, lower-case (mirrors the backend). */
export function searchNorm(s: string): string {
  return s.normalize("NFC").replace(/[​-‍⁠﻿]/g, "").replace(/़/g, "").toLowerCase();
}

/** Name of the dedicated graphics card: NVML knows NVIDIA cards, Vulkan knows every vendor. */
export function gpuName(info: { gpu_name: string | null; accel_devices?: { type: string; description: string }[] }): string {
  return info.gpu_name ?? info.accel_devices?.find((d) => d.type === "gpu")?.description ?? "No dedicated graphics card";
}
