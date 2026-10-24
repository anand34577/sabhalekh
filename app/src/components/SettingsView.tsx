import clsx from "clsx";
import { CheckCircle2, Cpu, FolderOpen, Gpu, HardDrive, Loader2, Lock, PackagePlus, RefreshCw, ShieldCheck, XCircle } from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";
import { get, post, put } from "../lib/api";
import { bytes } from "../lib/format";
import { LINKS, openLink, pickFolder, setAutostart, shell } from "../lib/native";
import type { Device, HardwareStatus, ModelInfo, Settings } from "../lib/types";
import { useStore } from "../store";
import { Button, Card, Field, Select, Toggle } from "./ui";

const ACCENTS = ["#4F8EF7", "#8B5CF6", "#14B8A6", "#F25F8C", "#F5A524", "#2BB673", "#EF6A3A"];

export function SettingsView() {
  const { settings, hardware, set, toast } = useStore();
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [verify, setVerify] = useState<string>("");
  const [devices, setDevices] = useState<{ microphones: Device[]; loopbacks: Device[] } | null>(null);
  const [storage, setStorage] = useState<Record<string, number | string> | null>(null);
  const [health, setHealth] = useState<{ version: string; network_blocked_attempts: number; logs_dir: string; data_dir: string } | null>(null);
  const [testing, setTesting] = useState(false);
  const [test, setTest] = useState<Record<string, { ok: boolean; peak: number }> | null>(null);
  const [packBusy, setPackBusy] = useState(false);

  const loadModels = () => get<{ models: ModelInfo[]; verify_state: string }>("/api/models").then((r) => {
    setModels(r.models);
    setVerify(r.verify_state);
  });
  useEffect(() => {
    loadModels();
    get<{ microphones: Device[]; loopbacks: Device[] }>("/api/recording/devices").then(setDevices).catch(() => setDevices(null));
    get<Record<string, number | string>>("/api/storage").then(setStorage);
    get<typeof health>("/api/health").then(setHealth);
  }, []);
  useEffect(() => {
    const onPack = (e: Event) => {
      const d = (e as CustomEvent).detail;
      if (d.type === "pack_imported" || d.type === "pack_failed") {
        setPackBusy(false);
        loadModels();
      }
    };
    window.addEventListener("sabhalekh-event", onPack);
    return () => window.removeEventListener("sabhalekh-event", onPack);
  }, []);

  if (!settings) return null;
  const update = async (p: Partial<Settings>) => {
    set({ settings: { ...settings, ...p } });
    try {
      const st = await put<Settings>("/api/settings", p);
      set({ settings: st });
      if ("profile_override" in p) set({ hardware: await get<HardwareStatus>("/api/hardware") });
    } catch (e) {
      toast({ kind: "error", title: "Setting not saved", body: String(e) });
    }
  };

  const asr = models.filter((m) => m.kind === "asr");
  const diar = models.find((m) => m.kind === "diarization");
  const igpu = hardware?.info.accel_devices?.find((d) => d.type === "igpu");
  const dgpu = !!hardware?.info.cuda_available || !!hardware?.info.accel_devices?.some((d) => d.type === "gpu");

  return (
    <div className="h-full overflow-y-auto bg-layer px-8 py-6">
      <div className="mx-auto max-w-3xl pb-16">
        <h1 className="text-[1.3rem] font-semibold">Settings</h1>

        <Section title="Transcription">
          <Field label="Language" hint="Auto handles meetings that switch between English and Hindi (Hinglish).">
            <Select value={settings.language_mode} onChange={(v) => update({ language_mode: v })} options={[
              { value: "auto", label: "Auto: English + Hindi (code-switching)" },
              { value: "en", label: "English only" },
              { value: "hi", label: "Hindi only" },
              { value: "translate", label: "Translate Hindi to English" },
            ]} />
          </Field>
          {settings.language_mode === "translate" && !asr.some((m) => m.translate && m.available) && (
            <p className="-mt-1 mb-2 text-[0.78rem] text-warning">
              Translation needs Whisper large-v3 (or medium/small): Nemotron ASR cannot translate. Import the Accuracy model pack below.
            </p>
          )}
          <Field label="Hindi / Hinglish script" hint="How Hindi words are written in the transcript.">
            <Select value={settings.script_mode} onChange={(v) => update({ script_mode: v })} options={[
              { value: "as_spoken", label: "As spoken: Hindi in Devanagari, English in Latin" },
              { value: "devanagari", label: "Devanagari: मीटिंग कल है" },
              { value: "roman", label: "Roman (transliterated): meeting kal hai" },
            ]} />
          </Field>
          <Field label="Speech recognition model" hint="Automatic uses NVIDIA Nemotron 3.5 ASR: the lowest Hindi word error rate, several times faster than Whisper, with less than half the memory. Whisper is used only to translate.">
            <Select value={settings.asr_model} onChange={(v) => update({ asr_model: v })} options={[
              { value: "auto", label: "Automatic (best for this PC and task)" },
              ...asr.map((m) => ({ value: m.id, label: `${m.label}${m.available ? "" : " (not installed)"}`, disabled: !m.available })),
            ]} />
          </Field>
          <Field label="Custom vocabulary" hint="Names, product words and jargon, e.g. “Rahul Sharma, Kubernetes, GST, Jio”. Helps spelling with Whisper models; Nemotron does not take a vocabulary.">
            <textarea value={settings.initial_prompt} onChange={(e) => set({ settings: { ...settings, initial_prompt: e.target.value } })}
              onBlur={(e) => update({ initial_prompt: e.target.value })} rows={2}
              className="w-full resize-none rounded-lg border border-stroke bg-card px-3 py-2 text-[0.88rem] focus:outline-none focus:ring-2 focus:ring-accent" />
          </Field>
          <div className="grid grid-cols-2 gap-4">
            <Field label="Minimum speakers" hint="Leave on Auto unless quiet speakers are missed.">
              <Select value={settings.min_speakers ?? 0} onChange={(v) => update({ min_speakers: v || null })}
                options={[{ value: 0, label: "Auto" }, ...[1, 2, 3, 4, 5, 6, 7, 8].map((n) => ({ value: n, label: String(n) }))]} />
            </Field>
            <Field label="Maximum speakers" hint="Nemotron tracks up to 8 speakers.">
              <Select value={settings.max_speakers ?? 0} onChange={(v) => update({ max_speakers: v || null })}
                options={[{ value: 0, label: "Auto (up to 8)" }, ...[1, 2, 3, 4, 5, 6, 7].map((n) => ({ value: n, label: String(n) }))]} />
            </Field>
          </div>
          <Toggle label="Process automatically" description="Transcribe recordings and imports as soon as they are saved."
            checked={settings.auto_process} onChange={(v) => update({ auto_process: v })} />
        </Section>

        <Section title="Hardware">
          {hardware && (
            <Card className="p-4">
              <div className="flex items-center gap-2.5">
                {hardware.profile.accel !== "cpu" ? <Gpu size={20} className="text-success" /> : <Cpu size={20} className="text-fg-2" />}
                <div className="font-medium">{hardware.badge}</div>
                <Button size="sm" variant="ghost" className="ml-auto" icon={<RefreshCw size={14} />}
                  onClick={async () => set({ hardware: await post<HardwareStatus>("/api/hardware/refresh") })}>Re-detect</Button>
              </div>
              <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-1.5 text-[0.82rem]">
                <Info k="GPU" v={hardware.info.gpu_name ? `${hardware.info.gpu_name} · ${Math.round((hardware.info.vram_mb ?? 0) / 1024)} GB VRAM` : "No discrete GPU"} />
                <Info k="Integrated GPU" v={igpu ? `${igpu.description} · shared memory` : "None"} />
                <Info k="Vulkan (Nemotron)" v={hardware.info.accel_error ? "Not available" : hardware.info.accel_devices.length ? hardware.info.accel_devices.map((d) => d.description.replace(/\(TM\)|NVIDIA |GeForce /g, "")).join(", ") : "No GPU"} />
                <Info k="NVIDIA CUDA (Whisper packs)" v={hardware.info.cuda_available ? "Available" : hardware.info.cuda_error ?? "Not available"} />
                <Info k="CPU" v={`${hardware.info.cpu_name ?? "CPU"} · ${hardware.info.cpu_cores} cores / ${hardware.info.cpu_threads} threads`} />
                <Info k="Memory" v={`${Math.round(hardware.info.ram_mb / 1024)} GB RAM · ${bytes(hardware.info.free_disk_mb * 1048576)} free disk`} />
                <Info k="Speech recognition on" v={hardware.profile.accel === "gpu" ? `${hardware.info.gpu_name ?? "GPU"} (dedicated VRAM)` : hardware.profile.accel === "igpu" ? `${igpu?.description ?? "integrated GPU"} (shared memory)` : `CPU (${hardware.profile.threads} threads)`} />
                <Info k="Diarization" v={diar?.available ? "Nemotron-3 · CPU (ONNX int8, ~40× real time)" : diar?.problem ?? "…"} />
              </dl>
              {hardware.warnings.map((w) => <p key={w} className="mt-2 text-[0.78rem] text-warning">{w}</p>)}
            </Card>
          )}
          <Field label="Processing profile" hint="Auto uses the discrete GPU (its own VRAM keeps system RAM free), then the integrated GPU, then the CPU. If a GPU runs out of memory, Sabhalekh moves to the next one by itself.">
            <Select value={settings.profile_override} onChange={(v) => update({ profile_override: v })} options={[
              { value: "auto", label: "Auto" },
              { value: "gpu_high", label: "High-performance GPU (6 GB+ VRAM)", disabled: !dgpu },
              { value: "gpu_low", label: "Discrete GPU, low VRAM (frees VRAM after each meeting)", disabled: !dgpu },
              { value: "igpu", label: "Integrated GPU (keeps the discrete GPU free)", disabled: !igpu },
              { value: "cpu", label: "CPU (int8)" },
              { value: "cpu_fast", label: "Fast CPU (lighter model, greedy decoding)" },
            ]} />
          </Field>
        </Section>

        <Section title="Models">
          <div className="space-y-1.5">
            {models.map((m) => (
              <div key={m.id} className="flex items-start gap-2.5 rounded-lg px-1 py-1.5">
                {m.available ? <CheckCircle2 size={16} className="mt-0.5 text-success" /> : <XCircle size={16} className="mt-0.5 text-fg-3" />}
                <div className="min-w-0">
                  <div className="text-[0.88rem]">{m.label} <span className="text-[0.72rem] text-fg-3">{m.source !== "bundled" ? m.source : ""}</span></div>
                  <div className="text-[0.76rem] text-fg-3">{m.available ? m.notes : m.problem}</div>
                </div>
              </div>
            ))}
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <Button icon={packBusy ? <Loader2 size={15} className="animate-spin" /> : <PackagePlus size={15} />} disabled={packBusy}
              onClick={async () => {
                const dir = await pickFolder("Choose the Offline Model Pack folder (e.g. on a USB drive)");
                if (!dir) return;
                setPackBusy(true);
                post("/api/models/import", { path: dir }).catch((e) => {
                  setPackBusy(false);
                  toast({ kind: "error", title: "Import failed", body: String(e) });
                });
              }}>{packBusy ? "Importing…" : "Import Offline Model Pack…"}</Button>
            <Button variant="ghost" icon={<ShieldCheck size={15} />} onClick={async () => {
              await post("/api/models/verify");
              setVerify("running");
              setTimeout(loadModels, 4000);
            }}>Verify model files</Button>
            <span className="text-[0.76rem] text-fg-3">
              Checksums: {verify === "ok" ? "all files verified" : verify === "running" || verify === "pending" ? "checking…" : verify}
            </span>
          </div>
        </Section>

        <Section title="Audio devices">
          <Field label="Microphone (your voice)">
            <Select value={settings.mic_device ?? -1} onChange={(v) => update({ mic_device: v === -1 ? null : v })} options={[
              { value: -1, label: "Windows default (follows device changes)" },
              ...(devices?.microphones ?? []).map((d) => ({ value: d.index, label: d.name })),
            ]} />
          </Field>
          <Field label="System audio (other participants)" hint="Captures what your speakers or headset play: Teams, Zoom, Meet in the browser…">
            <Select value={settings.loopback_device ?? -1} onChange={(v) => update({ loopback_device: v === -1 ? null : v })} options={[
              { value: -1, label: "Windows default output (follows device changes)" },
              ...(devices?.loopbacks ?? []).map((d) => ({ value: d.index, label: d.name.replace(" [Loopback]", "") })),
            ]} />
          </Field>
          <Field label="Playback audio quality" hint="Compressed Opus copy used by the player and audio export. Transcription always uses the full-quality 16 kHz audio.">
            <Select value={settings.playback_kbps ?? 64} onChange={(v) => update({ playback_kbps: v })} options={[
              { value: 48, label: "Compact (48 kbps per channel, ~22 MB per hour)" },
              { value: 64, label: "Standard (64 kbps per channel, ~29 MB per hour)" },
              { value: 96, label: "High (96 kbps per channel, ~43 MB per hour)" }]} />
          </Field>
          <div className="flex items-center gap-3">
            <Button disabled={testing} icon={testing ? <Loader2 size={15} className="animate-spin" /> : undefined} onClick={async () => {
              setTesting(true);
              setTest(null);
              try {
                const r = await post<{ tracks: Record<string, { ok: boolean; peak: number }> }>("/api/recording/test", { seconds: 4 });
                setTest(r.tracks);
              } catch (e) {
                toast({ kind: "error", title: "Audio test failed", body: String(e) });
              } finally {
                setTesting(false);
              }
            }}>{testing ? "Listening for 4 s… speak and play a sound" : "Test devices"}</Button>
            {test && Object.entries(test).map(([k, v]) => (
              <span key={k} className={clsx("text-[0.8rem]", v.ok ? "text-success" : "text-warning")}>
                {k === "mic" ? "Microphone" : "System audio"}: {v.ok ? "heard ✓" : "silent"}
              </span>
            ))}
          </div>
        </Section>

        <Section title="Appearance">
          <Field label="Theme">
            <Select value={settings.theme} onChange={(v) => update({ theme: v })} options={[
              { value: "system", label: "Follow Windows" }, { value: "dark", label: "Dark" }, { value: "light", label: "Light" }]} />
          </Field>
          <Field label="Accent color">
            <div className="flex gap-2">
              {ACCENTS.map((c) => (
                <button key={c} aria-label={`Accent ${c}`} onClick={() => update({ accent: c })}
                  className={clsx("h-7 w-7 rounded-full border-2", settings.accent.toUpperCase() === c ? "border-fg" : "border-transparent")}
                  style={{ background: c }} />
              ))}
            </div>
          </Field>
          <Field label={`Text size: ${Math.round(settings.text_scale * 100)}%`}>
            <input type="range" min={0.85} max={1.4} step={0.05} value={settings.text_scale} aria-label="Text size"
              onChange={(e) => set({ settings: { ...settings, text_scale: Number(e.target.value) } })}
              onMouseUp={(e) => update({ text_scale: Number((e.target as HTMLInputElement).value) })}
              onKeyUp={(e) => update({ text_scale: Number((e.target as HTMLInputElement).value) })}
              className="w-64 accent-[var(--accent)]" />
          </Field>
        </Section>

        <Section title="Shortcuts & startup">
          <Field label="Start / stop recording hotkey" hint="Works system-wide, even when Sabhalekh is minimized. Click the box and press the keys.">
            <HotkeyInput value={settings.hotkey} onChange={(v) => update({ hotkey: v })} />
          </Field>
          <Toggle label="Start with Windows" description="Opens minimized in the tray." checked={settings.start_with_windows}
            onChange={(v) => { update({ start_with_windows: v }); setAutostart(v); }} />
          <Toggle label="Keep running in the tray when the window is closed" checked={settings.minimize_to_tray}
            onChange={(v) => { update({ minimize_to_tray: v }); shell.setCloseToTray(v); }} />
        </Section>

        <Section title="Storage">
          {storage && (
            <div className="grid grid-cols-2 gap-x-6 gap-y-1.5 text-[0.82rem]">
              <Info k="Recordings & audio" v={bytes(Number(storage.sessions_bytes))} />
              <Info k="Database" v={bytes(Number(storage.db_bytes))} />
              <Info k="Imported models" v={bytes(Number(storage.models_bytes))} />
              <Info k="Free disk space" v={bytes(Number(storage.free_bytes))} />
            </div>
          )}
          <Field label="Delete audio automatically" hint="Transcripts are always kept; only the audio of finished meetings is removed.">
            <Select value={settings.auto_delete_audio_days} onChange={(v) => update({ auto_delete_audio_days: v })} options={[
              { value: 0, label: "Never" }, { value: 7, label: "After 7 days" }, { value: 30, label: "After 30 days" },
              { value: 90, label: "After 90 days" }, { value: 365, label: "After 1 year" }]} />
          </Field>
          <div className="flex flex-wrap gap-2">
            <Button size="sm" icon={<FolderOpen size={14} />} onClick={() => storage && shell.openFolder(String(storage.data_dir))}>Open data folder</Button>
            <Button size="sm" icon={<FolderOpen size={14} />} onClick={() => health && shell.openFolder(health.logs_dir)}>Open logs folder</Button>
            <Button size="sm" variant="ghost" icon={<HardDrive size={14} />} onClick={async () => {
              const r = await post<{ deleted: number }>("/api/storage/cleanup");
              toast({ kind: "info", title: r.deleted ? `Removed audio of ${r.deleted} meeting(s)` : "Nothing to clean up" });
              get<Record<string, number | string>>("/api/storage").then(setStorage);
            }}>Apply auto-delete now</Button>
          </div>
        </Section>

        <Section title="Privacy">
          <div className="flex items-start gap-3 rounded-xl border border-success/30 bg-success/10 p-4 text-[0.86rem]">
            <Lock size={18} className="mt-0.5 shrink-0 text-success" />
            <div>
              <div className="font-medium">Nothing ever leaves this PC.</div>
              <div className="mt-1 text-fg-2">
                Recording, transcription, speaker identification and search all run locally. Sabhalekh has no accounts, no cloud,
                no telemetry and no update checks; network access is blocked in code
                {health ? ` (${health.network_blocked_attempts} blocked attempts this session)` : ""}.
                Always tell participants when you record a meeting.
              </div>
            </div>
          </div>
        </Section>

        <Section title="About">
          <p className="text-[0.84rem] text-fg-2">Sabhalekh {health?.version ?? ""} · NVIDIA Nemotron 3.5 ASR (transcribe.cpp) · Whisper (CTranslate2, translation) · NVIDIA Nemotron-3-Diarization (OpenMDW-1.1) · Silero VAD.</p>
          <p className="mt-1 text-[0.8rem] text-fg-3">Free and open source under the MIT License. Third-party licenses are listed in THIRD_PARTY_LICENSES.md in the installation folder.
            Sabhalekh is an independent project, not affiliated with or endorsed by NVIDIA, OpenAI or Microsoft.</p>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button size="sm" onClick={() => openLink(LINKS.guide)}>User guide</Button>
            <Button size="sm" onClick={() => openLink(LINKS.issues)}>Report a problem</Button>
            <Button size="sm" variant="ghost" onClick={() => openLink(LINKS.source)}>Source code</Button>
          </div>
          <p className="mt-2 text-[0.76rem] text-fg-3">These links open in your web browser.</p>
        </Section>
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="mt-8">
      <h2 className="mb-2 text-[0.8rem] font-semibold uppercase tracking-wider text-fg-3">{title}</h2>
      <Card className="px-5 py-3">{children}</Card>
    </section>
  );
}

function Info({ k, v }: { k: string; v: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-[0.72rem] text-fg-3">{k}</dt>
      <dd className="truncate" title={v}>{v}</dd>
    </div>
  );
}

function HotkeyInput({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const [rec, setRec] = useState(false);
  return (
    <input readOnly value={rec ? "Press keys…" : value.replace("CommandOrControl", "Ctrl")} aria-label="Recording hotkey"
      onFocus={() => setRec(true)} onBlur={() => setRec(false)}
      onKeyDown={(e) => {
        e.preventDefault();
        if (["Control", "Shift", "Alt", "Meta"].includes(e.key)) return;
        if (e.key === "Escape") { (e.target as HTMLInputElement).blur(); return; }
        const parts = [];
        if (e.ctrlKey) parts.push("CommandOrControl");
        if (e.altKey) parts.push("Alt");
        if (e.shiftKey) parts.push("Shift");
        if (!parts.length) return; // require a modifier for a global hotkey
        const key = e.code.startsWith("Key") ? e.code.slice(3) : e.code.startsWith("Digit") ? e.code.slice(5) : e.key.length === 1 ? e.key.toUpperCase() : e.code;
        parts.push(key);
        onChange(parts.join("+"));
        setRec(false);
        (e.target as HTMLInputElement).blur();
      }}
      className="h-9 w-64 cursor-pointer rounded-lg border border-stroke bg-card px-3 text-[0.88rem] focus:outline-none focus:ring-2 focus:ring-accent" />
  );
}
