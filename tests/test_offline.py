"""The app must never touch the network. These tests fail if any outbound connection is possible."""
import json
import re
import socket
import threading
import urllib.request

import pytest

from conftest import ROOT
from sabhalekh import netguard

netguard.install()


@pytest.mark.parametrize("target", [("93.184.215.14", 80), ("8.8.8.8", 53), ("2606:4700:4700::1111", 443)])
def test_outbound_tcp_is_blocked(target):
    with pytest.raises(netguard.NetworkBlockedError):
        socket.create_connection(target, timeout=1)


def test_raw_socket_connect_is_blocked():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    with pytest.raises(netguard.NetworkBlockedError):
        s.connect(("1.1.1.1", 443))
    s.close()


def test_udp_sendto_is_blocked():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    with pytest.raises(netguard.NetworkBlockedError):
        s.sendto(b"x", ("8.8.8.8", 53))
    s.close()


def test_dns_lookup_is_blocked():
    with pytest.raises(netguard.NetworkBlockedError):
        socket.getaddrinfo("huggingface.co", 443)


def test_http_libraries_are_blocked():
    with pytest.raises(Exception) as ei:
        urllib.request.urlopen("https://huggingface.co", timeout=2)
    assert "offline-only" in str(ei.value) or isinstance(ei.value.__cause__, netguard.NetworkBlockedError) \
        or isinstance(getattr(ei.value, "reason", None), netguard.NetworkBlockedError)
    import httpx

    with pytest.raises(Exception) as ei2:
        httpx.get("https://example.com", timeout=2)
    assert "offline-only" in repr(ei2.value) or "offline-only" in str(ei2.value.__context__)


def test_loopback_is_allowed():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    threading.Thread(target=lambda: srv.accept()[0].close(), daemon=True).start()
    c = socket.create_connection(("127.0.0.1", port), timeout=2)
    c.close()
    srv.close()


def test_offline_environment_flags():
    import os

    assert os.environ["HF_HUB_OFFLINE"] == "1"
    assert os.environ["HF_HUB_DISABLE_TELEMETRY"] == "1"


def test_shell_content_security_policy_is_local_only():
    """The webview may only talk to the bundled UI and the backend on 127.0.0.1 (no CDN, fonts or telemetry)."""
    conf = json.loads((ROOT / "app" / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))
    csp = conf["app"]["security"]["csp"]
    csp = csp if isinstance(csp, str) else "; ".join(f"{k} {v}" for k, v in csp.items())
    urls = re.findall(r"(?:https?|wss?)://[^\s;']+", csp)
    assert urls, "CSP should whitelist the local backend"
    for u in urls:
        assert re.match(r"^(https?|wss?)://(127\.0\.0\.1|localhost|ipc\.localhost|tauri\.localhost)(:\*|:\d+)?/?",
                        u), f"non-local origin in CSP: {u}"
    assert "default-src 'self'" in csp
    assert not conf.get("plugins", {}).get("updater"), "no auto-updater (it would phone home)"


def test_ui_bundle_has_no_remote_urls():
    """Fonts, icons and scripts are bundled: the built UI must not reference any remote host."""
    dist = ROOT / "app" / "dist"
    if not dist.exists():
        pytest.skip("UI not built (npm run build)")
    allowed = re.compile(r"https?://(127\.0\.0\.1|localhost|www\.w3\.org|reactjs\.org|react\.dev|github\.com/"
                         r"(facebook|remix-run|anand34577/sabhalekh)|tauri\.localhost|ipc\.localhost)")
    offenders = []
    for f in dist.rglob("*"):
        if f.suffix not in (".js", ".css", ".html"):
            continue
        txt = f.read_text(encoding="utf-8", errors="ignore")
        for m in re.finditer(r"""(?:https?:)?//[a-z0-9.-]+\.[a-z]{2,}[^\s"'`)]*""", txt):
            u = m.group(0)
            if u.startswith("//"):
                u = "https:" + u
            if not allowed.match(u):
                # URLs inside license comments / error-message links are not fetched; only flag fetchable assets
                ctx = txt[max(0, m.start() - 12):m.start()]
                if any(k in ctx for k in ("src=", "href=", "url(", "import(", "fetch(", "@import")):
                    offenders.append((f.name, u))
    assert not offenders, f"remote resources referenced by the UI: {offenders[:5]}"
