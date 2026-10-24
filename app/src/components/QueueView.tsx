import { CheckCircle2, CircleSlash, Clock, Loader2, RefreshCw, X, XCircle } from "lucide-react";
import { useEffect } from "react";
import { post } from "../lib/api";
import { date, eta, STAGE_LABEL } from "../lib/format";
import type { Job } from "../lib/types";
import { useStore } from "../store";
import { Button, Card, ProgressBar } from "./ui";

export function QueueView() {
  const { jobs, refreshJobs, select, toast } = useStore();
  useEffect(() => {
    refreshJobs();
    const t = setInterval(refreshJobs, 5000);
    return () => clearInterval(t);
  }, [refreshJobs]);

  const active = jobs.filter((j) => j.status === "running" || j.status === "queued");
  const done = jobs.filter((j) => !(j.status === "running" || j.status === "queued"));
  const act = async (fn: () => Promise<unknown>) => {
    try {
      await fn();
      refreshJobs();
    } catch (e) {
      toast({ kind: "error", title: "Action failed", body: String(e) });
    }
  };

  const row = (j: Job) => (
    <Card key={j.id} className="p-4">
      <div className="flex items-start gap-3">
        <span className="mt-0.5">{icon(j)}</span>
        <div className="min-w-0 flex-1">
          <button className="truncate text-left text-[0.92rem] font-medium hover:text-accent hover:underline"
            onClick={() => select(j.session_id)}>{j.title}</button>
          <div className="mt-0.5 text-[0.76rem] text-fg-3">
            {j.status === "running" ? `${STAGE_LABEL[j.stage ?? ""] ?? "Starting"} · ${Math.round(j.progress * 100)}% · ${eta(j.eta_sec)}`
              : j.status === "queued" ? "Waiting for the current job"
                : `${j.status === "done" ? "Finished" : j.status === "error" ? "Failed" : "Cancelled"} ${date(j.finished_at ?? j.created_at)}`}
            {" · "}{String(j.params.language_mode ?? "auto").replace("auto", "Auto (EN+HI)").replace("translate", "Translate to English")}
          </div>
          {(j.status === "running" || j.status === "queued") && (
            <ProgressBar className="mt-2.5" value={j.progress} indeterminate={j.status === "queued"} />
          )}
          {j.error && <pre className="selectable mt-2 max-h-28 overflow-auto whitespace-pre-wrap rounded-md bg-layer-2 p-2 text-[0.74rem] text-danger">{j.error}</pre>}
        </div>
        <div className="flex shrink-0 gap-1.5">
          {(j.status === "running" || j.status === "queued") && (
            <Button size="sm" variant="ghost" icon={<X size={14} />} onClick={() => act(() => post(`/api/jobs/${j.id}/cancel`))}>Cancel</Button>
          )}
          {(j.status === "error" || j.status === "cancelled") && (
            <Button size="sm" icon={<RefreshCw size={14} />} onClick={() => act(() => post(`/api/jobs/${j.id}/retry`))}>Retry</Button>
          )}
        </div>
      </div>
    </Card>
  );

  return (
    <div className="h-full overflow-y-auto bg-layer px-8 py-6">
      <div className="mx-auto max-w-3xl">
        <h1 className="text-[1.3rem] font-semibold">Processing queue</h1>
        <p className="mt-1 text-[0.84rem] text-fg-3">
          One meeting is processed at a time so the GPU never runs out of memory. Jobs survive restarts and continue automatically.
        </p>
        <h2 className="mb-2 mt-6 text-[0.8rem] font-semibold uppercase tracking-wider text-fg-3">Active</h2>
        <div className="space-y-2">
          {active.length ? active.map(row) : <div className="text-[0.86rem] text-fg-3">Nothing is being processed.</div>}
        </div>
        {done.length > 0 && <>
          <h2 className="mb-2 mt-8 text-[0.8rem] font-semibold uppercase tracking-wider text-fg-3">Recent</h2>
          <div className="space-y-2">{done.slice(0, 30).map(row)}</div>
        </>}
      </div>
    </div>
  );
}

function icon(j: Job) {
  switch (j.status) {
    case "running": return <Loader2 size={18} className="animate-spin text-accent" />;
    case "queued": return <Clock size={18} className="text-fg-3" />;
    case "done": return <CheckCircle2 size={18} className="text-success" />;
    case "error": return <XCircle size={18} className="text-danger" />;
    default: return <CircleSlash size={18} className="text-warning" />;
  }
}
