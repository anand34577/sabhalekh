"""Thread-safe event bus: worker threads publish, WebSocket clients (asyncio) receive."""
from __future__ import annotations

import asyncio
import threading
import time
from typing import Any


class EventBus:
    def __init__(self):
        self._subs: set[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = set()
        self._lock = threading.Lock()

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        with self._lock:
            self._subs.add((asyncio.get_running_loop(), q))
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        with self._lock:
            self._subs = {s for s in self._subs if s[1] is not q}

    def publish(self, kind: str, **data: Any) -> None:
        msg = {"type": kind, "ts": time.time(), **data}
        with self._lock:
            subs = list(self._subs)
        for loop, q in subs:
            try:
                loop.call_soon_threadsafe(_put, q, msg)
            except RuntimeError:  # loop closed
                self.unsubscribe(q)


def _put(q: asyncio.Queue, msg: dict) -> None:
    if q.full():
        try:
            q.get_nowait()  # drop the oldest (level meters are high-rate and disposable)
        except asyncio.QueueEmpty:
            pass
    q.put_nowait(msg)
