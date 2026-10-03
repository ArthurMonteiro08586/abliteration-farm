#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
abliteration.ai OpenAI-compatible gateway
- Multi-key pool with rotation + auto-failover on 401/429/5xx
- Endpoints: /v1/chat/completions, /v1/models, /v1/completions, /health, /admin/keys
- Key pool loaded from accounts.jsonl (autoreg output) or keys.txt
- Optional master key auth (GATEWAY_API_KEY)

Run: python gateway.py [--port 8300]
Env: GATEWAY_API_KEY (optional), ABLIT_KEYS_FILE
"""
import json, os, re, sys, time, threading, random
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import urllib.request, urllib.error

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPSTREAM = "https://api.abliteration.ai/v1"
PORT = int(os.environ.get("ABLIT_GW_PORT", "8300"))
MASTER_KEY = os.environ.get("GATEWAY_API_KEY", "")
KEYS_FILE = os.environ.get("ABLIT_KEYS_FILE", os.path.join(BASE_DIR, "accounts.jsonl"))
POOL_FILE = os.path.join(BASE_DIR, "key_pool.json")

# ---------------------------------------------------------------- key pool
class KeyPool:
    def __init__(self):
        self.lock = threading.Lock()
        self.keys = []          # list of dict {key, status, fails, last_fail}
        self.load()

    def load(self):
        found = []
        # accounts.jsonl (autoreg output)
        if os.path.exists(KEYS_FILE):
            with open(KEYS_FILE, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                    except Exception:
                        continue
                    k = d.get("api_key")
                    if k and (k.startswith("sk-") or k.startswith("ak_")):
                        found.append(k)
        # keys.txt (one key per line)
        alt = os.path.join(BASE_DIR, "keys.txt")
        if os.path.exists(alt):
            with open(alt, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("sk-") or line.startswith("ak_"):
                        found.append(line)
        # dedupe preserve order
        seen = set()
        with self.lock:
            for k in found:
                if k not in seen:
                    seen.add(k)
                    self.keys.append({"key": k, "status": "ok", "fails": 0, "last_fail": 0})
            # merge existing statuses
            self._persist()
        print(f"[pool] loaded {len(self.keys)} keys")

    def _persist(self):
        try:
            with open(POOL_FILE, "w", encoding="utf-8") as f:
                json.dump([{"key": k["key"][:12] + "...", "status": k["status"],
                            "fails": k["fails"]} for k in self.keys], f, indent=2)
        except Exception:
            pass

    def pick(self):
        with self.lock:
            # auto-reload new keys from files every 60s
            if time.time() - getattr(self, "_last_reload", 0) > 60:
                self._reload_locked()
                self._last_reload = time.time()
            alive = [k for k in self.keys if k["status"] == "ok"]
            if not alive:
                # revive dead after 600s, nobalance after 1800s (review may pass later)
                now = time.time()
                for k in self.keys:
                    if k["status"] == "dead" and now - k["last_fail"] > 600:
                        k["status"] = "ok"; k["fails"] = 0
                    elif k["status"] == "nobalance" and now - k["last_fail"] > 1800:
                        k["status"] = "ok"; k["fails"] = 0
                alive = [k for k in self.keys if k["status"] == "ok"]
            if not alive:
                return None
            return random.choice(alive)

    def _reload_locked(self):
        found = []
        for path, is_jsonl in ((KEYS_FILE, True), (os.path.join(BASE_DIR, "keys.txt"), False)):
            if not os.path.exists(path):
                continue
            try:
                with open(path, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        if is_jsonl:
                            try:
                                d = json.loads(line)
                            except Exception:
                                continue
                            k = d.get("api_key")
                        else:
                            k = line
                        if k and (k.startswith("sk-") or k.startswith("ak_")):
                            found.append(k)
            except Exception:
                pass
        added = 0
        for k in found:
            if not any(x["key"] == k for x in self.keys):
                self.keys.append({"key": k, "status": "ok", "fails": 0, "last_fail": 0})
                added += 1
        if added:
            print(f"[pool] hot-reload: +{added} keys (total {len(self.keys)})")
            self._persist()

    def mark_fail(self, key, code, body=b""):
        with self.lock:
            for k in self.keys:
                if k["key"] == key:
                    k["fails"] += 1
                    k["last_fail"] = time.time()
                    if b"insufficient_credits" in (body or b""):
                        k["status"] = "nobalance"   # $1 review not passed — skip, retry later
                    elif code in (401, 403) or k["fails"] >= 4:
                        k["status"] = "dead"
                    break
            self._persist()

    def mark_ok(self, key):
        with self.lock:
            for k in self.keys:
                if k["key"] == key:
                    k["fails"] = 0
                    if k["status"] != "dead":
                        k["status"] = "ok"
                    break

    def add(self, key):
        with self.lock:
            if not any(k["key"] == key for k in self.keys):
                self.keys.append({"key": key, "status": "ok", "fails": 0, "last_fail": 0})
                self._persist()
                return True
        return False

    def stats(self):
        with self.lock:
            return {
                "total": len(self.keys),
                "ok": sum(1 for k in self.keys if k["status"] == "ok"),
                "dead": sum(1 for k in self.keys if k["status"] == "dead"),
                "nobalance": sum(1 for k in self.keys if k["status"] == "nobalance"),
                "keys": [{"key": k["key"][:12] + "...", "status": k["status"], "fails": k["fails"]} for k in self.keys],
            }


POOL = KeyPool()


# ---------------------------------------------------------------- upstream call
def upstream(path, method, body, key, timeout=180):
    url = UPSTREAM + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {key}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers or {})
    except Exception as e:
        return 599, json.dumps({"error": {"message": str(e), "type": "upstream_error"}}).encode(), {}


def proxy_with_failover(path, method, body, max_tries=8):
    tried = set()
    last = (503, b'{"error":{"message":"no keys available"}}', {})
    for _ in range(max_tries):
        k = POOL.pick()
        if not k:
            break
        if k["key"] in tried:
            continue
        tried.add(k["key"])
        status, resp, hdrs = upstream(path, method, body, k["key"])
        if status < 400:
            POOL.mark_ok(k["key"])
            return status, resp, hdrs
        POOL.mark_fail(k["key"], status, resp)
        last = (status, resp, hdrs)
        if b"insufficient_credits" in (resp or b""):
            continue   # key without $1 credit — try next
        if status in (400, 404, 422):   # client error not key-related
            return status, resp, hdrs
    return last


# ---------------------------------------------------------------- HTTP handler
class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        sys.stderr.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), fmt % args))

    def _send(self, status, payload, ctype="application/json"):
        if isinstance(payload, (dict, list)):
            payload = json.dumps(payload, ensure_ascii=False).encode()
        elif isinstance(payload, str):
            payload = payload.encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(payload)

    def _auth_ok(self):
        if not MASTER_KEY:
            return True
        h = self.headers.get("Authorization", "")
        return h == f"Bearer {MASTER_KEY}" or h.replace("Bearer ", "") == MASTER_KEY

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization,Content-Type")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        p = self.path.split("?")[0]
        if p == "/health":
            self._send(200, {"status": "ok", "upstream": UPSTREAM, **POOL.stats()})
            return
        if p == "/admin/keys":
            if not self._auth_ok():
                self._send(401, {"error": "unauthorized"}); return
            self._send(200, POOL.stats()); return
        if p == "/v1/models":
            status, resp, hdrs = proxy_with_failover("/models", "GET", None)
            self._send(status, resp); return
        self._send(404, {"error": {"message": "not found", "path": p}})

    def do_POST(self):
        if not self._auth_ok():
            self._send(401, {"error": {"message": "unauthorized"}}); return
        p = self.path.split("?")[0]
        ln = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(ln) if ln else b"{}"
        try:
            body = json.loads(raw or b"{}")
        except Exception:
            self._send(400, {"error": {"message": "invalid json"}}); return

        if p == "/admin/keys":
            k = body.get("key")
            if k and (k.startswith("sk-") or k.startswith("ak_")):
                added = POOL.add(k)
                self._send(200, {"added": added, **POOL.stats()})
            else:
                self._send(400, {"error": "key must start with sk-"})
            return

        if p in ("/v1/chat/completions", "/v1/completions", "/v1/embeddings"):
            sub = p.replace("/v1", "")
            stream = bool(body.get("stream"))
            if stream:
                # streaming passthrough
                k = POOL.pick()
                if not k:
                    self._send(503, {"error": {"message": "no keys"}}); return
                status, resp, hdrs = upstream(sub, "POST", body, k["key"], timeout=300)
                if status >= 400:
                    POOL.mark_fail(k["key"], status, resp)
                    self._send(status, resp); return
                POOL.mark_ok(k["key"])
                self.send_response(status)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                try:
                    self.wfile.write(resp)
                    self.wfile.flush()
                except Exception:
                    pass
                return
            status, resp, hdrs = proxy_with_failover(sub, "POST", body)
            self._send(status, resp); return

        self._send(404, {"error": {"message": "not found", "path": p}})


def main():
    print(f"[gateway] abliteration.ai -> http://127.0.0.1:{PORT}")
    print(f"[gateway] upstream {UPSTREAM}")
    print(f"[gateway] master key: {'ON' if MASTER_KEY else 'OFF (open)'}")
    print(f"[gateway] pool: {POOL.stats()['total']} keys ({POOL.stats()['ok']} ok)")
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    srv.daemon_threads = True
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n[gateway] stopping"); srv.shutdown()


if __name__ == "__main__":
    main()
