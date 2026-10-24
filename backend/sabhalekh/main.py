"""Sabhalekh backend sidecar.

    sabhalekh-backend --token TOKEN [--port 0] [--parent-pid PID]

Binds to 127.0.0.1 only. Prints `SABHALEKH_READY port=<port>` on stdout once it accepts connections, so the desktop
shell can connect. Exits when the parent process (the shell) goes away.
"""
from __future__ import annotations

import argparse
import logging
import os
import socket
import sys
import threading
import time

from . import netguard

netguard.install()  # before anything else can open a socket

from . import __version__, config, logging_setup  # noqa: E402

log = logging.getLogger("sabhalekh")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _watch_parent(pid: int, on_exit) -> None:
    import psutil

    def loop():
        while True:
            if not psutil.pid_exists(pid):
                log.info("parent process %s is gone, shutting down", pid)
                on_exit()
                os._exit(0)
            time.sleep(2)

    threading.Thread(target=loop, name="parent-watch", daemon=True).start()


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="sabhalekh-backend")
    ap.add_argument("--token", default=os.environ.get("SABHALEKH_TOKEN"))
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--parent-pid", type=int, default=0)
    ap.add_argument("--log-level", default="INFO")
    args = ap.parse_args(argv)
    if not args.token or len(args.token) < 16:
        sys.exit("a --token of at least 16 characters is required")

    logging_setup.setup(args.log_level)
    config.ensure_dirs()
    log.info("Sabhalekh backend %s, app dir %s, data dir %s", __version__, config.APP_DIR, config.DATA_DIR)

    import uvicorn

    from .api import App, apply_retention, create_app
    from .audio.recorder import Recorder
    from .db import Database
    from .events import EventBus
    from .hardware import HardwareManager
    from .models import ModelRegistry
    from .pipeline.jobs import JobQueue

    db = Database(config.DB_PATH)
    moved = db.relocate_session_files(config.SESSIONS_DIR)
    if moved:
        log.info("updated file locations of %d meetings after the data folder moved", moved)
    bus = EventBus()
    hw = HardwareManager()
    st = hw.status(db.get_settings().get("profile_override"))
    db.log_hardware(hw.info, st["profile"]["name"])
    log.info("hardware: %s | %s", st["badge"], {k: hw.info.get(k) for k in ("gpu_name", "vram_mb", "cpu_cores",
                                                                              "ram_mb", "free_disk_mb")})
    registry = ModelRegistry()
    threading.Thread(target=registry.verify, kwargs={"progress": lambda f: bus.publish("verify_progress",
                                                                                         progress=f)},
                     name="verify-models", daemon=True).start()
    queue = JobQueue(db, hw, registry, bus)
    recorder = Recorder(bus.publish)
    state = App(db, hw, registry, bus, queue, recorder, args.token)
    app = create_app(state)
    queue.start()

    def retention_loop():
        while True:
            try:
                apply_retention(state)
            except Exception:  # noqa: BLE001
                log.exception("retention cleanup failed")
            time.sleep(6 * 3600)

    threading.Thread(target=retention_loop, name="retention", daemon=True).start()

    def shutdown():
        try:
            if recorder.active:
                recorder.stop()  # stopped recordings stay recoverable on next launch
        except Exception:  # noqa: BLE001
            pass
        queue.stop()

    if args.parent_pid:
        _watch_parent(args.parent_pid, shutdown)

    port = args.port or _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", access_log=False,
                                           ws_ping_interval=None, http="h11", ws="websockets-sansio", loop="asyncio",
                                           lifespan="on"))
    orig_startup = server.startup

    async def startup(sockets=None):
        await orig_startup(sockets)
        print(f"SABHALEKH_READY port={port}", flush=True)
        log.info("listening on 127.0.0.1:%d", port)

    server.startup = startup
    try:
        server.run()
    finally:
        shutdown()


if __name__ == "__main__":
    main()
