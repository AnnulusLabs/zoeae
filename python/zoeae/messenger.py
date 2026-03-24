"""
Zoeae Messenger — Bare-metal messaging between phone and PC.

No third parties. No cloud. No accounts. Just HTTP over your LAN.
Part of the Zoeae orchestration runtime.

PC side: runs on port 7714, accepts messages + images from phone,
         queues outbound replies for phone to poll.

    python -m zoeae.messenger

Phone side: Termux script posts messages, polls for replies.
    See: termux_zoeae.sh

AnnulusLabs LLC — Taos, NM
"""
from __future__ import annotations

import base64
import json
import os
import sys
import time
import threading
import socket
import ssl
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from datetime import datetime

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ── Config ──

PORT = int(os.environ.get("ZOEAE_MSG_PORT", "7714"))
MEDIA_DIR = Path(os.environ.get("ZOEAE_MEDIA", str(Path.home() / ".zoeae" / "messenger" / "media")))
LOG_FILE = Path(os.environ.get("ZOEAE_MSG_LOG", str(Path.home() / ".zoeae" / "messenger" / "messages.jsonl")))
CERT_DIR = Path(os.environ.get("ZOEAE_CERTS", str(Path.home() / ".zoeae" / "certs")))
MAX_OUTBOX = 100

# ── State ──

_inbox: list[dict] = []
_outbox: list[dict] = []
_outbox_cursor: dict[str, int] = {}
_lock = threading.Lock()

# ── Callbacks ──

_on_message_callbacks: list = []


def on_message(callback):
    """Register a callback for incoming messages. callback(msg_dict)."""
    _on_message_callbacks.append(callback)


def send_to_phone(text: str, media_path: str = ""):
    """Queue a message for the phone to pick up."""
    msg = {
        "id": f"out-{int(time.time()*1000)}",
        "from": "zoeae",
        "text": text,
        "media": media_path,
        "timestamp": datetime.now().isoformat(),
    }
    with _lock:
        _outbox.append(msg)
        if len(_outbox) > MAX_OUTBOX:
            _outbox[:] = _outbox[-MAX_OUTBOX:]
    return msg


def get_inbox(since: int = 0) -> list[dict]:
    """Get inbox messages since index."""
    with _lock:
        return list(_inbox[since:])


def get_lan_ip() -> str:
    """Get this machine's LAN IP."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def _get_chat_html() -> str:
    """Return self-contained chat UI HTML. Tries to load from zoeae_chat.html first."""
    # Try workspace file
    for candidate in [
        Path(__file__).parent.parent / "zoeae_chat.html",
        Path.home() / ".openclaw" / "workspace" / "zoeae_chat.html",
    ]:
        if candidate.exists():
            return candidate.read_text(encoding="utf-8")
    return "<html><body><h1>zoeae_chat.html not found</h1></body></html>"


# ── HTTP Handler ──

class MessengerHandler(BaseHTTPRequestHandler):

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Device-ID")

    def _json(self, data, code=200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        if length > 10_485_760:  # 10MB max
            self._json({"error": "payload too large"}, 413)
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        if self.path in ("/", "/chat"):
            # Serve the chat UI — self-contained, no external dependencies
            chat_html = _get_chat_html()
            body = chat_html.encode("utf-8")
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        elif self.path == "/ping":
            self._json({"status": "alive", "name": "zoeae-messenger", "t": time.time()})

        elif self.path.startswith("/outbox"):
            device_id = self.headers.get("X-Device-ID", "default")
            with _lock:
                cursor = _outbox_cursor.get(device_id, 0)
                msgs = _outbox[cursor:]
                _outbox_cursor[device_id] = len(_outbox)
            self._json({"messages": msgs, "count": len(msgs)})

        elif self.path == "/inbox":
            self._json({"messages": _inbox[-50:], "count": len(_inbox)})

        elif self.path == "/status":
            self._json({
                "name": "zoeae-messenger",
                "inbox": len(_inbox),
                "outbox": len(_outbox),
                "lan_ip": get_lan_ip(),
                "port": PORT,
                "uptime": time.time(),
            })

        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        if self.path == "/inbox":
            body = self._read_body()
            msg = {
                "id": f"in-{int(time.time()*1000)}",
                "from": body.get("from", "phone"),
                "text": body.get("text", ""),
                "timestamp": datetime.now().isoformat(),
            }

            if body.get("image_b64"):
                try:
                    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
                    ext = body.get("image_ext", "jpg")
                    fname = f"img_{int(time.time()*1000)}.{ext}"
                    fpath = MEDIA_DIR / fname
                    fpath.write_bytes(base64.b64decode(body["image_b64"]))
                    msg["media"] = str(fpath)
                    msg["media_name"] = fname
                except Exception:
                    msg["media_error"] = "invalid base64"

            LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(msg) + "\n")

            with _lock:
                _inbox.append(msg)

            for cb in _on_message_callbacks:
                try:
                    cb(msg)
                except Exception as e:
                    print(f"  callback error: {e}")

            self._json({"ok": True, "id": msg["id"]})

        elif self.path == "/outbox":
            body = self._read_body()
            msg = send_to_phone(
                text=body.get("text", ""),
                media_path=body.get("media", ""),
            )
            self._json({"ok": True, "id": msg["id"]})

        else:
            self._json({"error": "not found"}, 404)

    def log_message(self, fmt, *args):
        pass


# ── Server ──

class DualStackHTTPServer(HTTPServer):
    """HTTP server that listens on both IPv4 and IPv6 (dual-stack)."""
    address_family = socket.AF_INET6

    def server_bind(self):
        # Allow dual-stack (IPv4 + IPv6) on the same socket
        self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        super().server_bind()


def _wrap_tls(server: HTTPServer) -> HTTPServer:
    """Wrap server socket with TLS if cert files exist."""
    cert_file = CERT_DIR / "cert.pem"
    key_file = CERT_DIR / "key.pem"
    if cert_file.exists() and key_file.exists():
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(str(cert_file), str(key_file))
        server.socket = ctx.wrap_socket(server.socket, server_side=True)
        return server
    return server


def start_server(port: int = PORT, background: bool = False, tls: bool = True) -> HTTPServer:
    """Start the messenger server on IPv4+IPv6 with optional TLS."""
    server = DualStackHTTPServer(("::", port), MessengerHandler)
    if tls:
        server = _wrap_tls(server)
    if background:
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        return server
    else:
        return server


def start_dual_servers(tls_port: int = PORT, http_port: int = PORT + 1, background: bool = True):
    """Start both HTTPS (7714) and HTTP (7715) servers.
    HTTP is safe on Yggdrasil — the mesh encrypts at the network layer.
    """
    servers = []
    # HTTPS on main port
    s1 = DualStackHTTPServer(("::", tls_port), MessengerHandler)
    s1 = _wrap_tls(s1)
    t1 = threading.Thread(target=s1.serve_forever, daemon=True)
    t1.start()
    servers.append(s1)
    # Plain HTTP on secondary port (for Yggdrasil / browsers that fight self-signed certs)
    s2 = DualStackHTTPServer(("::", http_port), MessengerHandler)
    t2 = threading.Thread(target=s2.serve_forever, daemon=True)
    t2.start()
    servers.append(s2)
    return servers


def get_ygg_ip() -> str:
    """Get this machine's Yggdrasil IPv6 address."""
    try:
        import subprocess
        result = subprocess.run(
            ["ipconfig"], capture_output=True, text=True, timeout=5
        )
        lines = result.stdout.splitlines()
        in_ygg = False
        for line in lines:
            if "Yggdrasil" in line:
                in_ygg = True
            elif in_ygg and "IPv6 Address" in line:
                return line.split(":")[-6] + ":" + ":".join(line.split(":")[-5:])
            elif in_ygg and line.strip() == "":
                in_ygg = False
    except Exception:
        pass
    # Fallback: scan interfaces
    try:
        import subprocess
        result = subprocess.run(
            ["powershell", "-c", "Get-NetIPAddress -InterfaceAlias Yggdrasil -AddressFamily IPv6 | Select -ExpandProperty IPAddress"],
            capture_output=True, text=True, timeout=5
        )
        addr = result.stdout.strip().splitlines()
        for a in addr:
            if a.startswith("2") or a.startswith("3"):
                return a.strip()
    except Exception:
        pass
    return ""


def main():
    lan_ip = get_lan_ip()
    ygg_ip = get_ygg_ip()
    has_tls = (CERT_DIR / "cert.pem").exists()
    proto = "https" if has_tls else "http"
    ygg_line = f"\n  YGG:  {proto}://[{ygg_ip}]:{PORT}" if ygg_ip else "\n  YGG:  not detected"
    tls_line = "  TLS:  enabled (self-signed)" if has_tls else "  TLS:  disabled (no certs)"
    print(f"""
     /|\\ /|\\ /|\\ /|\\ /|\\ /|\\ /|\\
      1   2   3   4   5   6   7
     ZOEAE MESSENGER — bare metal
  ──────────────────────────────────
  LAN:  {proto}://{lan_ip}:{PORT}{ygg_line}
  {tls_line}
  ──────────────────────────────────
  GET   /chat    — open chat UI
  POST  /inbox   — phone sends message
  GET   /outbox  — phone polls for replies
  POST  /outbox  — PC queues reply
  GET   /ping    — keepalive
  ──────────────────────────────────
  No cloud. No accounts. Sovereign.
  Waiting for messages...
""")

    def _print_msg(msg):
        ts = msg.get("timestamp", "")[:19]
        text = msg.get("text", "")
        media = msg.get("media_name", "")
        print(f"  [{ts}] {msg['from']}: {text}")
        if media:
            print(f"           media: {media}")

    on_message(_print_msg)

    if has_tls:
        # Run HTTPS on PORT, plain HTTP on PORT+1 (for Yggdrasil browsers)
        http_port = PORT + 1
        print(f"  HTTP:  http://{lan_ip}:{http_port}  (Yggdrasil-safe)")
        if ygg_ip:
            print(f"         http://[{ygg_ip}]:{http_port}/chat")
        print()
        servers = start_dual_servers(tls_port=PORT, http_port=http_port, background=True)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n  Shutting down.")
            for s in servers:
                s.shutdown()
    else:
        server = DualStackHTTPServer(("::", PORT), MessengerHandler)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\n  Shutting down.")
            server.shutdown()


if __name__ == "__main__":
    main()
