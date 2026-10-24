import clsx from "clsx";
import { CheckCircle2, Cpu, Gpu, Loader2, Lock, Mic, Monitor, XCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { get, post, put } from "../lib/api";
import { gpuName } from "../lib/format";
import type { ModelInfo, Session, Settings } from "../lib/types";
import { useStore } from "../store";
import { Button, Modal } from "./ui";

const STEPS = ["Welcome", "Hardware", "Audio test", "Test recording"];

export function Onboarding({ onClose }: { onClose: () => void }) {
  const { hardware, toast, set, select, refreshSessions } = useStore();
  const [step, setStep] = useState(0);
  const [models, setModels] = useState<ModelInfo[] | null>(null);
  const [test, setTest] = useState<Record<string, { ok: boolean }> | null>(null);
  const [testing, setTesting] = useState(false);
  const [recState, setRecState] = useState<"idle" | "recording" | "done">("idle");
  const [count, setCount] = useState(10);

  useEffect(() => { get<{ models: ModelInfo[] }>("/api/models").then((r) => setModels(r.models)); }, []);

  const finish = async () => {
    const st = await put<Settings>("/api/settings", { onboarding_done: true });
    set({ settings: st });
    onClose();
  };

  const runTest = async () => {
    setTesting(true);
    setTest(null);
    try {
      const r = await post<{ tracks: Record<string, { ok: boolean }> }>("/api/recording/test", { seconds: 4 });
      setTest(r.tracks);
    } catch (e) {
      toast({ kind: "error", title: "Audio test failed", body: String(e) });
    } finally {
      setTesting(false);
    }
  };

  const testRecording = async () => {
    try {
      await put("/api/settings", { consent_acknowledged: true });
      await post("/api/recording/start", { title: "Test recording" });
      setRecState("recording");
      for (let i = 10; i > 0; i--) {
        setCount(i);
        await new Promise((r) => setTimeout(r, 1000));
      }
      const s = await post<Session>("/api/recording/stop");
      setRecState("done");
      await refreshSessions();
      select(s.id);
    } catch (e) {
      setRecState("idle");
      toast({ kind: "error", title: "Test recording failed", body: String(e) });
    }
  };

  const ok = (b: boolean | undefined) => b ? <CheckCircle2 size={17} className="text-success" /> : <XCircle size={17} className="text-warning" />;
  const asrReady = models?.some((m) => m.kind === "asr" && m.available);
  const diarReady = models?.some((m) => m.kind === "diarization" && m.available);

  return (
    <Modal title="Welcome to Sabhalekh" width={600} footer={<>
      <Button variant="ghost" onClick={finish}>Skip setup</Button>
      {step > 0 && <Button onClick={() => setStep(step - 1)}>Back</Button>}
      {step < STEPS.length - 1 ? <Button variant="primary" onClick={() => setStep(step + 1)}>Next</Button>
        : <Button variant="primary" onClick={finish}>Finish</Button>}
    </>}>
      <ol className="mb-5 flex gap-2">
        {STEPS.map((s, i) => (
          <li key={s} className="flex-1">
            <div className={clsx("h-1 rounded-full", i <= step ? "bg-accent" : "bg-stroke")} />
            <div className={clsx("mt-1.5 text-[0.72rem]", i === step ? "text-fg" : "text-fg-3")}>{s}</div>
          </li>
        ))}
      </ol>

      {step === 0 && (
        <div className="space-y-3 text-[0.9rem] text-fg-2">
          <p>Sabhalekh records your meetings (or imports audio and video files) and turns them into transcripts with
            speaker names and timestamps, in <b className="text-fg">English, Hindi and Hinglish</b>.</p>
          <div className="flex gap-3 rounded-xl border border-success/30 bg-success/10 p-3.5">
            <Lock size={18} className="mt-0.5 shrink-0 text-success" />
            <p><b className="text-fg">Completely offline.</b> Speech recognition (NVIDIA Nemotron 3.5 ASR), speaker identification (NVIDIA
              Nemotron-3-Diarization) and search run on this PC. No account, no cloud, no telemetry: nothing ever leaves the machine.</p>
          </div>
        </div>
      )}

      {step === 1 && (
        <div className="space-y-3 text-[0.88rem]">
          <div className="flex items-center gap-3 rounded-xl border border-stroke bg-card p-3.5">
            {hardware && hardware.profile.accel !== "cpu" ? <Gpu className="text-success" /> : <Cpu className="text-fg-2" />}
            <div>
              <div className="font-medium">{hardware?.badge ?? "Detecting…"}</div>
              <div className="text-[0.78rem] text-fg-3">
                {hardware ? gpuName(hardware.info) : ""} · {hardware?.info.cpu_cores} CPU cores · {Math.round((hardware?.info.ram_mb ?? 0) / 1024)} GB RAM
              </div>
            </div>
          </div>
          {hardware?.warnings.map((w) => <p key={w} className="text-[0.8rem] text-warning">{w}</p>)}
          <div className="space-y-1.5">
            <div className="flex items-center gap-2">{models ? ok(asrReady) : <Loader2 size={17} className="animate-spin" />} Speech recognition model</div>
            <div className="flex items-center gap-2">{models ? ok(diarReady) : <Loader2 size={17} className="animate-spin" />} Speaker diarization model (Nemotron-3)</div>
          </div>
          <p className="text-[0.8rem] text-fg-3">
            {hardware?.profile.accel === "gpu"
              ? "Your graphics card does the speech recognition; speaker identification runs on the CPU and leaves the GPU memory free."
              : hardware?.profile.accel === "igpu"
                ? "Your processor's built-in graphics does the speech recognition; speaker identification runs on the CPU."
                : "Everything runs on the CPU. That works fine, it just takes about twice as long as with a graphics card."}
          </p>
        </div>
      )}

      {step === 2 && (
        <div className="space-y-3 text-[0.88rem] text-fg-2">
          <p>Click <b className="text-fg">Start test</b>, then <b className="text-fg">say something</b> and <b className="text-fg">play any sound</b>{" "}
            (a video, music) for 4 seconds. This checks that both your voice and other participants will be captured.</p>
          <Button variant="primary" disabled={testing} icon={testing ? <Loader2 size={15} className="animate-spin" /> : undefined}
            onClick={runTest}>{testing ? "Listening…" : "Start test"}</Button>
          {test && (
            <div className="space-y-1.5">
              <div className="flex items-center gap-2">{ok(test.mic?.ok)}<Mic size={15} /> Microphone {test.mic?.ok ? "works" : "was silent: check the device in Windows sound settings"}</div>
              <div className="flex items-center gap-2">{ok(test.system?.ok)}<Monitor size={15} /> System audio {test.system?.ok ? "works" : "was silent: did a sound play during the test?"}</div>
            </div>
          )}
        </div>
      )}

      {step === 3 && (
        <div className="space-y-3 text-[0.88rem] text-fg-2">
          <p>Record a 10-second test and watch Sabhalekh transcribe it. Say a sentence in English or Hindi.</p>
          {recState === "idle" && <Button variant="primary" icon={<Mic size={15} />} onClick={testRecording}>Record 10 seconds</Button>}
          {recState === "recording" && (
            <div className="flex items-center gap-2 text-fg"><span className="rec-dot h-3 w-3 rounded-full bg-rec" /> Recording… {count}s</div>
          )}
          {recState === "done" && <p className="text-success">Saved. It is being processed and will appear in your history.</p>}
          <p className="text-[0.8rem] text-fg-3">Tip: press {useStore.getState().settings?.hotkey.replace("CommandOrControl", "Ctrl")} anywhere to start or stop recording,
            and drop audio or video files onto the window to import them.</p>
        </div>
      )}
    </Modal>
  );
}
