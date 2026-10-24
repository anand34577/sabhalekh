"""Local HTTP + WebSocket API for the desktop shell. Bound to 127.0.0.1, every request needs the per-launch token.

(No `from __future__ import annotations` here: FastAPI must see the request models declared inside create_app.)
"""
import asyncio
import hmac
import logging
import shutil
import sys
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import Body, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel

from . import __version__, config, export, netguard
from .audio import media
from .audio import recorder as rec

log = logging.getLogger("sabhalekh.api")

ALLOWED_HOSTS = {"127.0.0.1", "localhost"}


class App:
    """Holds the long-lived services; created by main.py."""

    def __init__(self, db, hw, registry, bus, queue, recorder, token: str):
        self.db, self.hw, self.registry, self.bus = db, hw, registry, bus
        self.queue, self.recorder, self.token = queue, recorder, token


def create_app(app_state: App) -> FastAPI:
    api = FastAPI(title="Sabhalekh local API", version=__version__, docs_url=None, redoc_url=None,
                  openapi_url=None)
    S = app_state

    # ------------------------------------------------------------------ security
    @api.middleware("http")
    async def guard(request: Request, call_next):
        host = (request.headers.get("host") or "").rsplit(":", 1)[0].strip("[]")
        if host not in ALLOWED_HOSTS:  # DNS-rebinding protection
            return JSONResponse({"detail": "forbidden host"}, status_code=403)
        if request.method == "OPTIONS":
            return _cors(Response(status_code=204), request)
        token = request.headers.get("authorization", "").removeprefix("Bearer ").strip() \
            or request.query_params.get("token", "")
        if not hmac.compare_digest(token, S.token):
            return _cors(JSONResponse({"detail": "unauthorized"}, status_code=401), request)
        try:
            resp = await call_next(request)
        except Exception as e:  # noqa: BLE001
            log.exception("unhandled error on %s", request.url.path)
            resp = JSONResponse({"detail": f"{type(e).__name__}: {e}"}, status_code=500)
        return _cors(resp, request)

    def _cors(resp: Response, request: Request) -> Response:
        origin = request.headers.get("origin")
        if origin and (origin.startswith("http://tauri.localhost") or origin.startswith("https://tauri.localhost")
                       or origin.startswith("tauri://") or origin.startswith("http://localhost:1420")):
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Access-Control-Allow-Headers"] = "authorization, content-type, range"
            resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
            resp.headers["Access-Control-Expose-Headers"] = "content-range, accept-ranges, content-length"
        return resp

    def need(obj, what="not found"):
        if obj is None:
            raise HTTPException(404, what)
        return obj

    def bad(e: Exception):
        raise HTTPException(400, str(e))

    # ------------------------------------------------------------------ system
    @api.get("/api/health")
    def health():
        return {"ok": True, "version": __version__, "models": S.registry.verify_state,
                "bad_model_files": S.registry.bad_files, "recording": S.recorder.status(),
                "busy": S.queue.busy, "data_dir": str(config.DATA_DIR), "logs_dir": str(config.LOGS_DIR),
                "network_blocked_attempts": len(netguard.blocked_attempts()),
                "windows_build": sys.getwindowsversion().build if sys.platform == "win32" else 0}

    @api.get("/api/hardware")
    def hardware():
        return S.hw.status(S.db.get_settings().get("profile_override"))

    @api.post("/api/hardware/refresh")
    def hardware_refresh():
        S.hw.refresh()
        st = S.hw.status(S.db.get_settings().get("profile_override"))
        S.db.log_hardware(S.hw.info, st["profile"]["name"])
        return st

    @api.get("/api/models")
    def models():
        return {"models": S.registry.catalog(), "verify_state": S.registry.verify_state}

    @api.post("/api/models/verify")
    def models_verify():
        threading.Thread(target=S.registry.verify, daemon=True).start()
        return {"started": True}

    class ImportPack(BaseModel):
        path: str

    @api.post("/api/models/import")
    def models_import(body: ImportPack):
        def work():
            try:
                res = S.registry.import_pack(body.path, progress=lambda f: S.bus.publish("pack_progress",
                                                                                           progress=f))
                S.bus.publish("pack_imported", **res)
            except Exception as e:  # noqa: BLE001
                S.bus.publish("pack_failed", error=str(e))
        threading.Thread(target=work, daemon=True).start()
        return {"started": True}

    @api.get("/api/settings")
    def get_settings():
        return S.db.get_settings()

    @api.put("/api/settings")
    def put_settings(values: dict[str, Any] = Body(...)):
        st = S.db.set_settings(values)
        S.bus.publish("settings_updated")
        return st

    @api.get("/api/storage")
    def storage():
        def size(p: Path) -> int:
            return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p.exists() else 0
        return {"data_dir": str(config.DATA_DIR), "sessions_bytes": size(config.SESSIONS_DIR),
                "db_bytes": config.DB_PATH.stat().st_size if config.DB_PATH.exists() else 0,
                "logs_bytes": size(config.LOGS_DIR), "models_bytes": size(config.USER_MODELS_DIR),
                "free_bytes": shutil.disk_usage(config.DATA_DIR).free, "logs_dir": str(config.LOGS_DIR)}

    @api.post("/api/storage/cleanup")
    def storage_cleanup():
        return {"deleted": apply_retention(S)}

    # ------------------------------------------------------------------ sessions
    @api.get("/api/sessions")
    def sessions(status: str | None = None, tag: str | None = None, language: str | None = None,
                 source: str | None = None, date_from: float | None = None, date_to: float | None = None,
                 sort: str = "date", order: str = "desc", q: str | None = None):
        return S.db.list_sessions(status, tag, language, source, date_from, date_to, sort, order, q)

    @api.get("/api/tags")
    def tags():
        return S.db.all_tags()

    @api.get("/api/sessions/{sid}")
    def session(sid: int):
        s = need(S.db.get_session(sid))
        return {"session": s, **S.db.get_transcript(sid), "talk_time": S.db.talk_time(sid),
                "has_audio": bool(s.get("audio_path") and Path(s["audio_path"]).exists())}

    class SessionPatch(BaseModel):
        title: str | None = None
        tags: list[str] | None = None

    @api.patch("/api/sessions/{sid}")
    def patch_session(sid: int, body: SessionPatch):
        need(S.db.get_session(sid))
        fields = {}
        if body.title is not None:
            if not body.title.strip():
                raise HTTPException(400, "title cannot be empty")
            fields["title"] = body.title.strip()
        if body.tags is not None:
            fields["tags"] = sorted({t.strip() for t in body.tags if t.strip()})
        S.db.update_session(sid, **fields)
        S.bus.publish("session_updated", session_id=sid)
        return S.db.get_session(sid)

    @api.delete("/api/sessions/{sid}")
    def delete_session(sid: int, mode: str = Query("all", pattern="^(all|audio)$")):
        s = need(S.db.get_session(sid))
        for j in S.db.list_jobs(["queued", "running"]):
            if j["session_id"] == sid:
                S.queue.cancel(j["id"])
        sdir = config.SESSIONS_DIR / str(sid)
        if mode == "all":
            S.db.delete_session(sid)
            _rmtree_later(sdir)
        else:
            for p in (s.get("audio_path"), s.get("norm_path"), s.get("mic_track_path"), s.get("system_track_path")):
                if p:
                    Path(p).unlink(missing_ok=True)
            S.db.update_session(sid, audio_path=None, norm_path=None, mic_track_path=None, system_track_path=None)
        S.bus.publish("session_deleted" if mode == "all" else "session_updated", session_id=sid)
        return {"ok": True}

    class ImportBody(BaseModel):
        paths: list[str]
        language_mode: str | None = None

    @api.post("/api/sessions/import")
    def import_files(body: ImportBody):
        created, errors = [], []
        auto = S.db.get_settings().get("auto_process", True)
        for p in body.paths:
            path = Path(p)
            try:
                if not path.is_file():
                    raise ValueError("file not found")
                if path.suffix.lower() not in media.SUPPORTED_EXT:
                    raise ValueError(f"unsupported format {path.suffix} (supported: "
                                     f"{', '.join(sorted(e[1:] for e in media.SUPPORTED_EXT))})")
                info = media.probe(path)
                sid = S.db.create_session(path.stem, "imported", original_filename=path.name,
                                          source_path=str(path.resolve()), duration_sec=info["duration"],
                                          status="new")
                config.session_dir(sid)
                if auto:
                    S.queue.enqueue(sid, {"language_mode": body.language_mode} if body.language_mode else None)
                created.append(sid)
                S.bus.publish("session_created", session_id=sid)
            except Exception as e:  # noqa: BLE001
                errors.append({"path": p, "error": str(e)})
        return {"created": created, "errors": errors}

    class ProcessBody(BaseModel):
        language_mode: str | None = None
        script_mode: str | None = None
        asr_model: str | None = None
        profile_override: str | None = None
        initial_prompt: str | None = None
        min_speakers: int | None = None
        max_speakers: int | None = None

    @api.post("/api/sessions/{sid}/process")
    def process(sid: int, body: ProcessBody = Body(default_factory=ProcessBody)):
        s = need(S.db.get_session(sid))
        if s["source_type"] == "imported" and not (s.get("norm_path") and Path(s["norm_path"]).exists()) \
                and not Path(s.get("source_path") or "").is_file():
            raise HTTPException(400, "The audio of this session was deleted and the original file is gone.")
        if s["source_type"] == "recorded" and not any(
                p and Path(p).exists() for p in (s.get("norm_path"), s.get("mic_track_path"),
                                                  s.get("system_track_path"))):
            raise HTTPException(400, "The audio of this recording was deleted; it cannot be re-processed.")
        try:
            jid = S.queue.enqueue(sid, body.model_dump(exclude_none=True))
        except ValueError as e:
            bad(e)
        return {"job_id": jid}

    @api.get("/api/sessions/{sid}/peaks")
    def peaks(sid: int):
        s = need(S.db.get_session(sid))
        p = s.get("peaks_path")
        if not p or not Path(p).exists():
            raise HTTPException(404, "waveform not ready")
        return FileResponse(p, media_type="application/json")

    @api.get("/api/sessions/{sid}/audio")
    def audio(sid: int):
        s = need(S.db.get_session(sid))
        p = s.get("audio_path")
        if not p or not Path(p).exists():
            raise HTTPException(404, "audio not available")
        mt = "audio/ogg" if p.endswith(".ogg") else "audio/wav"
        return FileResponse(p, media_type=mt, headers={"Cache-Control": "no-store"})

    @api.post("/api/sessions/{sid}/revert")
    def revert(sid: int):
        try:
            S.db.revert_session(sid)
        except ValueError as e:
            bad(e)
        S.bus.publish("transcript_updated", session_id=sid)
        return session(sid)

    # ------------------------------------------------------------------ speakers & segments
    class SpeakerPatch(BaseModel):
        display_name: str | None = None
        color: str | None = None

    @api.patch("/api/speakers/{spk}")
    def patch_speaker(spk: int, body: SpeakerPatch):
        row = need(S.db.conn.execute("SELECT session_id FROM speakers WHERE id = ?", (spk,)).fetchone())
        try:
            if body.display_name is not None:
                S.db.rename_speaker(spk, body.display_name)
            if body.color is not None:
                S.db.set_speaker_color(spk, body.color)
        except ValueError as e:
            bad(e)
        S.bus.publish("transcript_updated", session_id=row[0])
        return {"ok": True}

    class NewSpeaker(BaseModel):
        name: str

    @api.post("/api/sessions/{sid}/speakers")
    def add_speaker(sid: int, body: NewSpeaker):
        need(S.db.get_session(sid))
        return {"id": S.db.add_speaker(sid, body.name)}

    class SegmentPatch(BaseModel):
        text: str | None = None
        speaker_id: int | None = None

    @api.patch("/api/segments/{seg}")
    def patch_segment(seg: int, body: SegmentPatch):
        try:
            sid = S.db.edit_segment(seg, body.text, body.speaker_id)
        except KeyError as e:
            raise HTTPException(404, str(e))
        except ValueError as e:
            bad(e)
        S.bus.publish("transcript_updated", session_id=sid)
        return {"ok": True}

    @api.post("/api/segments/{seg}/revert")
    def revert_segment(seg: int):
        try:
            sid = S.db.revert_segment(seg)
        except KeyError as e:
            raise HTTPException(404, str(e))
        S.bus.publish("transcript_updated", session_id=sid)
        return {"ok": True}

    class MergeBody(BaseModel):
        ids: list[int]

    @api.post("/api/segments/merge")
    def merge(body: MergeBody):
        try:
            sid = S.db.merge_segments(body.ids)
        except (KeyError, ValueError) as e:
            bad(e)
        S.bus.publish("transcript_updated", session_id=sid)
        return {"ok": True}

    class SplitBody(BaseModel):
        at_word: int | None = None
        at_char: int | None = None

    @api.post("/api/segments/{seg}/split")
    def split(seg: int, body: SplitBody):
        try:
            sid = S.db.split_segment(seg, body.at_word, body.at_char)
        except (KeyError, ValueError) as e:
            bad(e)
        S.bus.publish("transcript_updated", session_id=sid)
        return {"ok": True}

    # ------------------------------------------------------------------ search & export
    @api.get("/api/search")
    def search(q: str, session_id: int | None = None, limit: int = 200):
        return S.db.search(q, session_id, limit)

    class ExportBody(BaseModel):
        session_ids: list[int]
        formats: list[str]
        path: str
        timestamps: bool = True
        speakers: bool = True
        merge: bool = True

    def _doc(sid: int) -> dict:
        s = need(S.db.get_session(sid), f"session {sid} not found")
        return {"session": s, **S.db.get_transcript(sid), "talk_time": S.db.talk_time(sid)}

    @api.post("/api/export")
    def do_export(body: ExportBody):
        opts = export.ExportOptions(body.timestamps, body.speakers, body.merge)
        for f in body.formats:
            if f not in export.FORMATS:
                raise HTTPException(400, f"unknown format {f}")
        out = Path(body.path)
        out.parent.mkdir(parents=True, exist_ok=True)
        docs = [_doc(i) for i in body.session_ids]
        if len(docs) == 1 and len(body.formats) == 1 and not out.suffix.lower() == ".zip":
            data = export.export(docs[0], body.formats[0], opts)
        else:
            data = export.export_zip(docs, body.formats, opts)
        tmp = out.with_name(out.name + ".part")
        tmp.write_bytes(data)
        tmp.replace(out)
        return {"path": str(out), "bytes": len(data)}

    class AudioExport(BaseModel):
        path: str

    @api.post("/api/sessions/{sid}/export-audio")
    def export_audio(sid: int, body: AudioExport):
        s = need(S.db.get_session(sid))
        src = s.get("audio_path")
        if not src or not Path(src).exists():
            raise HTTPException(404, "audio not available")
        shutil.copy2(src, body.path)
        return {"path": body.path}

    # ------------------------------------------------------------------ jobs
    @api.get("/api/jobs")
    def jobs(active: bool = False):
        return S.db.list_jobs(["queued", "running"] if active else None)

    @api.post("/api/jobs/{jid}/cancel")
    def cancel(jid: int):
        try:
            S.queue.cancel(jid)
        except KeyError as e:
            raise HTTPException(404, str(e))
        return {"ok": True}

    @api.post("/api/jobs/{jid}/retry")
    def retry(jid: int):
        try:
            return {"job_id": S.queue.retry(jid)}
        except KeyError as e:
            raise HTTPException(404, str(e))
        except ValueError as e:
            bad(e)

    # ------------------------------------------------------------------ recording
    @api.get("/api/recording/devices")
    def devices():
        try:
            return rec.list_devices()
        except Exception as e:  # noqa: BLE001
            raise HTTPException(500, f"cannot list audio devices: {e}")

    @api.get("/api/recording/status")
    def rec_status():
        return S.recorder.status()

    class StartBody(BaseModel):
        title: str | None = None
        mic_device: int | None = None
        loopback_device: int | None = None
        capture_mic: bool = True
        capture_system: bool = True

    @api.post("/api/recording/start")
    def rec_start(body: StartBody = Body(default_factory=StartBody)):
        st = S.db.get_settings()
        title = (body.title or "").strip() or time.strftime("Meeting %d %b %Y, %H:%M")
        try:
            return S.recorder.start(title, body.mic_device if body.mic_device is not None else st.get("mic_device"),
                                    body.loopback_device if body.loopback_device is not None
                                    else st.get("loopback_device"), body.capture_mic, body.capture_system)
        except rec.RecorderError as e:
            bad(e)

    @api.post("/api/recording/pause")
    def rec_pause():
        return S.recorder.pause()

    @api.post("/api/recording/resume")
    def rec_resume():
        return S.recorder.resume()

    @api.post("/api/recording/stop")
    def rec_stop():
        try:
            result = S.recorder.stop()
        except rec.RecorderError as e:
            bad(e)
        return finalize_recording(S, result)

    @api.get("/api/recording/recoverable")
    def rec_recoverable():
        st = S.recorder.status()
        return rec.recoverable(st.get("id") if st.get("active") else None)

    @api.post("/api/recording/recover/{rid}")
    def rec_recover(rid: str):
        try:
            result = rec.recover(rid)
        except rec.RecorderError as e:
            raise HTTPException(404, str(e))
        return finalize_recording(S, result)

    @api.delete("/api/recording/recoverable/{rid}")
    def rec_discard(rid: str):
        d = config.RECORDING_TMP_DIR / rid
        if d.is_dir() and d.parent == config.RECORDING_TMP_DIR:
            shutil.rmtree(d, ignore_errors=True)
        return {"ok": True}

    class TestBody(BaseModel):
        seconds: float = 4.0

    @api.post("/api/recording/test")
    def rec_test(body: TestBody = Body(default_factory=TestBody)):
        """Onboarding: record a few seconds of mic + system audio and report their levels (nothing is kept)."""
        if S.recorder.active:
            raise HTTPException(409, "a recording is running")
        st = S.db.get_settings()
        r = rec.Recorder(lambda *a, **k: None)
        try:
            r.start("test", st.get("mic_device"), st.get("loopback_device"))
        except rec.RecorderError as e:
            bad(e)
        time.sleep(max(1.0, min(10.0, body.seconds)))
        result = r.stop()
        out = {"devices": {}, "tracks": {}}
        for kind, path in result["tracks"].items():
            w = media.Wav16k(path)
            a = np.array(w.int16(0, w.frames))  # a copy: a memory-mapped view would keep the file locked on Windows
            w.close()
            peak = float(abs(a).max()) / 32768 if len(a) else 0.0
            rms = float((a.astype("float32") ** 2).mean() ** 0.5) / 32768 if len(a) else 0.0
            out["tracks"][kind] = {"peak": round(peak, 4), "rms": round(rms, 4), "ok": peak > 0.01}
        # a left-over folder would show up as an "unfinished recording" to recover on the next start
        try:
            shutil.rmtree(result["dir"])
        except OSError as e:
            log.warning("could not remove the device-test recording %s: %s", result["dir"], e)
        return out

    # ------------------------------------------------------------------ events
    @api.websocket("/api/events")
    async def events(ws: WebSocket):
        host = (ws.headers.get("host") or "").rsplit(":", 1)[0]
        if host not in ALLOWED_HOSTS or not hmac.compare_digest(ws.query_params.get("token", ""), S.token):
            await ws.close(code=4401)
            return
        await ws.accept()
        q = S.bus.subscribe()
        try:
            await ws.send_json({"type": "hello", "version": __version__})
            while True:
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=15)
                except asyncio.TimeoutError:
                    msg = {"type": "ping"}
                await ws.send_json(msg)
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            S.bus.unsubscribe(q)

    return api


def finalize_recording(S: App, result: dict) -> dict:
    """Move a stopped (or recovered) recording into the library, then queue it if auto-processing is on."""
    tracks = {k: Path(v) for k, v in result["tracks"].items() if Path(v).exists() and Path(v).stat().st_size > 44}
    if not tracks:
        shutil.rmtree(result["dir"], ignore_errors=True)
        raise HTTPException(400, "the recording is empty")
    sid = S.db.create_session(result["title"], "recorded", status="new", duration_sec=result["duration"])
    if result.get("started_at"):
        with S.db.tx() as c:
            c.execute("UPDATE sessions SET created_at = ? WHERE id = ?", (result["started_at"], sid))
    sdir = config.session_dir(sid)
    fields: dict = {}
    for kind, p in tracks.items():
        dst = sdir / f"{kind}_16k.wav"
        shutil.move(str(p), dst)
        fields[f"{'mic' if kind == 'mic' else 'system'}_track_path"] = str(dst)
    if len(tracks) == 1:
        fields["norm_path"] = next(iter(fields.values()))
    else:  # mixed track: playable right away, and the pipeline's input
        mixed = sdir / "audio_16k.wav"
        media.mix_wavs([fields["mic_track_path"], fields["system_track_path"]], mixed)
        fields["norm_path"] = str(mixed)
    fields["audio_path"] = fields["norm_path"]  # replaced by the Opus copy once processed
    S.db.update_session(sid, **fields)
    try:
        media.compute_peaks(fields["norm_path"], sdir / "peaks.json")
        S.db.update_session(sid, peaks_path=str(sdir / "peaks.json"))
    except Exception:  # noqa: BLE001
        pass
    shutil.rmtree(result["dir"], ignore_errors=True)
    S.bus.publish("session_created", session_id=sid)
    if S.db.get_settings().get("auto_process", True):
        S.queue.enqueue(sid)
    return S.db.get_session(sid)


def apply_retention(S: App) -> int:
    """Auto-delete rule: remove the audio (not the transcript) of finished sessions older than N days."""
    days = int(S.db.get_settings().get("auto_delete_audio_days") or 0)
    if days <= 0:
        return 0
    cutoff = time.time() - days * 86400
    n = 0
    for s in S.db.list_sessions(status="done"):
        if s["created_at"] < cutoff and s.get("audio_path"):
            for p in (s.get("audio_path"), s.get("norm_path"), s.get("mic_track_path"), s.get("system_track_path")):
                if p:
                    Path(p).unlink(missing_ok=True)
            S.db.update_session(s["id"], audio_path=None, norm_path=None, mic_track_path=None,
                                system_track_path=None)
            n += 1
    return n


def _rmtree_later(path: Path) -> None:
    """Session folders can be briefly locked by the player on Windows: retry for a few seconds."""
    def work():
        for _ in range(20):
            shutil.rmtree(path, ignore_errors=True)
            if not path.exists():
                return
            time.sleep(0.5)
    threading.Thread(target=work, daemon=True).start()
