/** Thin wrappers around the Tauri shell and plugins (dialogs, notifications, hotkey, autostart, tray). */
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { getCurrentWebview } from "@tauri-apps/api/webview";
import { disable as autostartDisable, enable as autostartEnable, isEnabled } from "@tauri-apps/plugin-autostart";
import { ask, open, save } from "@tauri-apps/plugin-dialog";
import { register, unregisterAll } from "@tauri-apps/plugin-global-shortcut";
import { isPermissionGranted, requestPermission, sendNotification } from "@tauri-apps/plugin-notification";
import { openPath, openUrl, revealItemInDir } from "@tauri-apps/plugin-opener";
import { isTauri } from "./api";

export const MEDIA_EXTENSIONS = ["mp3", "wav", "m4a", "aac", "flac", "ogg", "opus", "wma", "mp4", "mkv", "mov", "avi",
  "webm"];

export async function pickMediaFiles(): Promise<string[]> {
  const r = await open({ multiple: true, title: "Upload media",
    filters: [{ name: "Audio & video", extensions: MEDIA_EXTENSIONS }] });
  if (!r) return [];
  return Array.isArray(r) ? r : [r];
}

export async function pickFolder(title: string): Promise<string | null> {
  const r = await open({ directory: true, title });
  return typeof r === "string" ? r : null;
}

export async function pickSavePath(defaultName: string, ext: string, label: string): Promise<string | null> {
  return save({ defaultPath: defaultName, title: "Export", filters: [{ name: label, extensions: [ext] }] });
}

/** Project pages, opened in the user's own browser on request. The app itself never connects anywhere. */
export const LINKS = {
  guide: "https://github.com/anand34577/sabhalekh/wiki",
  issues: "https://github.com/anand34577/sabhalekh/issues/new/choose",
  source: "https://github.com/anand34577/sabhalekh",
};

export async function openLink(url: string) {
  if (isTauri()) await openUrl(url);
  else window.open(url, "_blank", "noopener");
}

export async function confirmDialog(message: string, title = "Sabhalekh"): Promise<boolean> {
  return ask(message, { title, kind: "warning" });
}

let notifyOk: boolean | null = null;
export async function notify(title: string, body: string) {
  if (!isTauri()) return;
  try {
    if (notifyOk === null) {
      notifyOk = await isPermissionGranted();
      if (!notifyOk) notifyOk = (await requestPermission()) === "granted";
    }
    if (notifyOk) sendNotification({ title, body });
  } catch {
    /* notifications are best-effort */
  }
}

export async function setHotkey(accelerator: string, onPress: () => void): Promise<string | null> {
  if (!isTauri()) return null;
  try {
    await unregisterAll();
    if (!accelerator) return null;
    await register(accelerator, (e) => {
      if (e.state === "Pressed") onPress();
    });
    return null;
  } catch (e) {
    return String(e);
  }
}

export async function setAutostart(on: boolean) {
  try {
    if (on && !(await isEnabled())) await autostartEnable();
    if (!on && (await isEnabled())) await autostartDisable();
  } catch {
    /* ignore in dev */
  }
}

export const shell = {
  setCloseToTray: (enabled: boolean) => invoke("set_close_to_tray", { enabled }).catch(() => {}),
  setRecordingIndicator: (active: boolean, label?: string) =>
    invoke("set_recording_indicator", { active, label: label ?? null }).catch(() => {}),
  restartBackend: () => invoke("restart_backend"),
  quit: () => invoke("quit_app"),
  openFolder: (path: string) => openPath(path).catch(() => {}),
  reveal: (path: string) => revealItemInDir(path).catch(() => {}),
};

export function onTray(onToggleRecording: () => void, onQuit: () => void) {
  if (!isTauri()) return () => {};
  const a = listen("tray://toggle-recording", onToggleRecording);
  const b = listen("tray://quit-requested", onQuit);
  return () => {
    a.then((f) => f());
    b.then((f) => f());
  };
}

export function onFileDrop(onDrop: (paths: string[]) => void, onHover: (over: boolean) => void) {
  if (!isTauri()) return () => {};
  const p = getCurrentWebview().onDragDropEvent((e) => {
    if (e.payload.type === "over" || e.payload.type === "enter") onHover(true);
    else if (e.payload.type === "leave") onHover(false);
    else if (e.payload.type === "drop") {
      onHover(false);
      onDrop(e.payload.paths);
    }
  });
  return () => {
    p.then((f) => f());
  };
}
