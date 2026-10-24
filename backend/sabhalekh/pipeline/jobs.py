"""Job queue: one heavy job at a time, persisted in SQLite, resumable after restart, cancellable, retryable."""
from __future__ import annotations

import logging
import threading
import time
import traceback

from .runner import Cancelled, Context, JobParams, Run, params_dict, params_from

log = logging.getLogger("sabhalekh.jobs")


class JobQueue:
    def __init__(self, db, hw, registry, bus):
        self.db, self.hw, self.registry, self.bus = db, hw, registry, bus
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._cancel: dict[int, threading.Event] = {}
        self._current: int | None = None
        self._asr_cache: dict = {}
        self._thread = threading.Thread(target=self._loop, name="job-worker", daemon=True)

    def start(self) -> None:
        n = self.db.requeue_interrupted_jobs()
        if n:
            log.info("re-queued %d job(s) interrupted by the last shutdown", n)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        for ev in self._cancel.values():
            ev.set()
        self._wake.set()

    # ------------------------------------------------------------------ API
    def enqueue(self, session_id: int, overrides: dict | None = None) -> int:
        for j in self.db.list_jobs(["queued", "running"]):
            if j["session_id"] == session_id:
                raise ValueError("this session is already queued or processing")
        params = params_from(self.db.get_settings(), overrides)
        job_id = self.db.create_job(session_id, params_dict(params))
        self.db.update_session(session_id, status="queued", stage=None, progress=0, error_message=None)
        self.bus.publish("job_queued", job_id=job_id, session_id=session_id)
        self.bus.publish("session_updated", session_id=session_id)
        self._wake.set()
        return job_id

    def cancel(self, job_id: int) -> None:
        job = self.db.get_job(job_id)
        if job is None:
            raise KeyError("job not found")
        if job["status"] == "queued":
            self.db.update_job(job_id, status="cancelled", finished_at=time.time())
            self.db.update_session(job["session_id"], status="cancelled", stage=None)
            self.bus.publish("job_finished", job_id=job_id, session_id=job["session_id"], status="cancelled")
            self.bus.publish("session_updated", session_id=job["session_id"])
        elif job["status"] == "running":
            self._cancel.setdefault(job_id, threading.Event()).set()

    def retry(self, job_id: int) -> int:
        job = self.db.get_job(job_id)
        if job is None:
            raise KeyError("job not found")
        if job["status"] in ("queued", "running"):
            raise ValueError("job is still active")
        return self.enqueue(job["session_id"], job["params"])

    @property
    def busy(self) -> bool:
        return self._current is not None

    # ------------------------------------------------------------------ worker
    def _loop(self) -> None:
        while not self._stop.is_set():
            job = self.db.next_queued_job()
            if job is None:
                self._wake.wait(timeout=2.0)
                self._wake.clear()
                continue
            self._run(job)

    def _run(self, job: dict) -> None:
        jid, sid = job["id"], job["session_id"]
        cancel = self._cancel.setdefault(jid, threading.Event())
        self._current = jid
        self.db.update_job(jid, status="running", started_at=time.time(), error=None, progress=0)
        self.bus.publish("job_started", job_id=jid, session_id=sid)
        ctx = Context(self.db, self.hw, self.registry, self.bus.publish,
                      lambda: cancel.is_set() or self._stop.is_set(), self._asr_cache)
        params = JobParams(**{k: v for k, v in job["params"].items() if k in JobParams.__dataclass_fields__})
        status, error = "done", None
        try:
            Run(ctx, sid, jid, params).run()
        except Cancelled:
            status = "cancelled" if not self._stop.is_set() else "queued"
        except Exception as e:  # noqa: BLE001 - every failure is reported, never swallowed
            status, error = "error", _friendly(e)
            log.error("job %s failed: %s\n%s", jid, e, traceback.format_exc())
        finally:
            self._current = None
            self._cancel.pop(jid, None)
        if status == "queued":  # app shutting down: resume on next start
            self.db.update_job(jid, status="queued", stage=None, progress=0)
            self.db.update_session(sid, status="queued")
            return
        self.db.update_job(jid, status=status, finished_at=time.time(), error=error,
                           progress=1.0 if status == "done" else job.get("progress", 0))
        if status != "done":
            self.db.update_session(sid, status=status, error_message=error)
        session = self.db.get_session(sid)
        self.bus.publish("job_finished", job_id=jid, session_id=sid, status=status, error=error,
                         title=session["title"] if session else "")
        self.bus.publish("session_updated", session_id=sid)


def _friendly(e: Exception) -> str:
    msg = str(e).strip() or type(e).__name__
    low = msg.lower()
    if "no space left" in low or "disk full" in low:
        return "The disk is full. Free some space and retry."
    if "permission" in low or "access is denied" in low:
        return f"Windows denied access to a file ({msg}). Check that the file is not open elsewhere and retry."
    return msg
