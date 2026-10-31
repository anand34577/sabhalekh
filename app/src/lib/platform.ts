/** Which desktop the UI is running on, for window chrome and keyboard shortcuts. */
export type Platform = "windows" | "mac" | "linux";

export const platform: Platform = (() => {
  const ua = (typeof navigator === "undefined" ? "" : navigator.userAgent).toLowerCase();
  if (ua.includes("mac")) return "mac";
  if (ua.includes("windows")) return "windows";
  return "linux";
})();

export const isMac = platform === "mac";

/** The shortcut modifier: Cmd on macOS, Ctrl elsewhere. */
export const modKey = (e: { ctrlKey: boolean; metaKey: boolean }) => (isMac ? e.metaKey : e.ctrlKey);

export const MOD_LABEL = isMac ? "⌘" : "Ctrl";

/** "CommandOrControl+Shift+R" as the user should read it on this platform. */
export const hotkeyLabel = (accelerator: string) =>
  accelerator.replace("CommandOrControl", MOD_LABEL).replace(/\+/g, isMac ? "" : "+");
