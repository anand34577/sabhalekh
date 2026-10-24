"""Hard offline guarantee for the Python process.

`install()` replaces the socket layer's outbound entry points so that any attempt to reach a non-loopback address
raises `NetworkBlockedError` (and is logged), no matter which library makes it. The local API server still binds to
127.0.0.1 and the UI still talks to it. Hugging Face / tokenizer libraries are additionally told to stay offline.
"""
from __future__ import annotations

import ipaddress
import logging
import os
import socket

log = logging.getLogger("sabhalekh.netguard")

_installed = False
_blocked_attempts: list[str] = []

_OFFLINE_ENV = {
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "HF_DATASETS_OFFLINE": "1",
    "HF_HUB_DISABLE_TELEMETRY": "1",
    "DO_NOT_TRACK": "1",
    "NO_PROXY": "*",
}


class NetworkBlockedError(ConnectionRefusedError):
    """Raised when code tries to open a connection to anything but this machine."""


def _is_loopback(host) -> bool:
    if host is None:
        return False
    if isinstance(host, bytes):
        host = host.decode(errors="ignore")
    host = str(host).strip("[]")
    if host in ("localhost", "") or host.endswith(".localhost"):
        return host != ""
    try:
        return ipaddress.ip_address(host.split("%", 1)[0]).is_loopback
    except ValueError:
        return False


def _check(address, what: str) -> None:
    if isinstance(address, (tuple, list)) and address:
        host = address[0]
    elif isinstance(address, (str, bytes)):  # AF_UNIX path
        return
    else:
        host = None
    if not _is_loopback(host):
        msg = f"blocked outbound network access ({what} -> {address!r}): Sabhalekh is offline-only"
        _blocked_attempts.append(msg)
        log.error(msg)
        raise NetworkBlockedError(msg)


def blocked_attempts() -> list[str]:
    return list(_blocked_attempts)


def install() -> None:
    global _installed
    if _installed:
        return
    for k, v in _OFFLINE_ENV.items():
        os.environ[k] = v
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
        os.environ.pop(k, None)

    orig_connect = socket.socket.connect
    orig_connect_ex = socket.socket.connect_ex
    orig_sendto = socket.socket.sendto
    orig_getaddrinfo = socket.getaddrinfo
    orig_create_connection = socket.create_connection

    def connect(self, address):
        if self.family in (socket.AF_INET, socket.AF_INET6):
            _check(address, "connect")
        return orig_connect(self, address)

    def connect_ex(self, address):
        if self.family in (socket.AF_INET, socket.AF_INET6):
            _check(address, "connect_ex")
        return orig_connect_ex(self, address)

    def sendto(self, data, *args):
        address = args[-1]
        if self.family in (socket.AF_INET, socket.AF_INET6):
            _check(address, "sendto")
        return orig_sendto(self, data, *args)

    def getaddrinfo(host, *args, **kwargs):
        if host is not None and not _is_loopback(host):
            _check((host,), "getaddrinfo")
        return orig_getaddrinfo(host, *args, **kwargs)

    def create_connection(address, *args, **kwargs):
        _check(address, "create_connection")
        return orig_create_connection(address, *args, **kwargs)

    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex
    socket.socket.sendto = sendto
    socket.getaddrinfo = getaddrinfo
    socket.create_connection = create_connection
    _installed = True
    log.info("network guard installed: only loopback connections are allowed")
