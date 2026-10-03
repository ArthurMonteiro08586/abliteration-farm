#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
solvers.py — multi-backend Cloudflare Turnstile solver with fallback chain.

Backends (order configurable via CAPTCHA_BACKENDS env, comma-separated):
  sidecar    — FREE local waguriagentic/captcha-solver (:8877, CloakBrowser, no paid API)
  2captcha   — paid, method=turnstile (+action)
  yescaptcha — paid, AntiTurnstileTaskProxyLess
  capmonster — paid, TurnstileTaskProxyless
  anticaptcha— paid, TurnstileTaskProxyless

Usage:
  from solvers import solve_turnstile
  token, backend = solve_turnstile(sitekey, pageurl, action="password_signup", proxy=None)

Env (any of, read from .env files too):
  SIDECAR_URL (default http://127.0.0.1:8877)
  TWOCAPTCHA_KEY / YESCAPTCHA_KEY / CAPMONSTER_KEY / ANTICAPTCHA_KEY
  CAPTCHA_BACKENDS=sidecar,2captcha,yescaptcha,capmonster,anticaptcha
"""
import json, os, time, urllib.request, urllib.parse, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CHAIN = ["sidecar-realpage", "2captcha", "yescaptcha", "capmonster", "anticaptcha", "sidecar"]

def _load_env_files():
    env = {}
    candidates = [
        os.path.join(HERE, ".env"),
        os.path.join(os.path.expanduser("~"), "Desktop", "_PROJECTS",
                     "\u0430\u0432\u0442\u043e\u0440\u0435\u0433 \u043f\u0440\u043e\u0435\u043a\u0442", ".env"),
    ]
    for p in candidates:
        if not os.path.exists(p):
            continue
        try:
            for line in open(p, encoding="utf-8"):
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    env.setdefault(k.strip(), v.strip())
        except Exception:
            pass
    return env

_ENV = _load_env_files()

def _get(name, default=""):
    return os.environ.get(name) or _ENV.get(name) or default

class SolverError(Exception):
    pass

def _http_json(url, data=None, headers=None, timeout=60, method=None):
    hdrs = {"User-Agent": "farm-solver/1.0"}
    if headers:
        hdrs.update(headers)
    body = None
    if data is not None:
        if isinstance(data, dict):
            body = json.dumps(data).encode()
            hdrs.setdefault("Content-Type", "application/json")
        else:
            body = data
    req = urllib.request.Request(url, data=body, headers=hdrs, method=method or ("POST" if body else "GET"))
    with urllib.request.urlopen(req, timeout=timeout) as r:
        t = r.read().decode()
        try:
            return json.loads(t)
        except Exception:
            return t

# ---------------------------------------------------------------- sidecar (FREE)
def solve_sidecar(sitekey, pageurl, action=None, proxy=None, timeout=150):
    url = _get("SIDECAR_URL", "http://127.0.0.1:8877")
    payload = {"type": "turnstile", "sitekey": sitekey, "url": pageurl, "timeout_s": min(timeout, 300)}
    if action:
        payload["action"] = action
    if proxy:
        payload["proxy"] = proxy
    try:
        r = _http_json(url.rstrip("/") + "/solve", payload, timeout=timeout + 20)
    except urllib.error.URLError as e:
        raise SolverError(f"sidecar unreachable ({e.reason}) — start it: cd cs_sidecar && python server.py")
    if isinstance(r, dict) and r.get("solved") and r.get("token"):
        return r["token"]
    raise SolverError("sidecar: " + json.dumps(r)[:200] if isinstance(r, dict) else str(r)[:200])

def solve_sidecar_realpage(sitekey, pageurl, action=None, proxy=None, timeout=180):
    """real_page=true: sidecar navigates the ACTUAL site -> token from real page context.
    Needed when route-intercept tokens are rejected (invalid-input-response / request_unverified)."""
    url = _get("SIDECAR_URL", "http://127.0.0.1:8877")
    payload = {"type": "turnstile", "sitekey": sitekey, "url": pageurl,
               "real_page": True, "timeout_s": min(timeout, 300)}
    if action:
        payload["action"] = action
    if proxy:
        payload["proxy"] = proxy
    try:
        r = _http_json(url.rstrip("/") + "/solve", payload, timeout=timeout + 20)
    except urllib.error.URLError as e:
        raise SolverError(f"sidecar unreachable ({e.reason})")
    if isinstance(r, dict) and r.get("solved") and r.get("token"):
        return r["token"]
    raise SolverError("sidecar-realpage: " + (json.dumps(r)[:200] if isinstance(r, dict) else str(r)[:200]))

# ---------------------------------------------------------------- 2captcha
def solve_2captcha(sitekey, pageurl, action=None, proxy=None, timeout=300):
    key = _get("TWOCAPTCHA_KEY")
    if not key:
        raise SolverError("2captcha: no TWOCAPTCHA_KEY")
    params = {"key": key, "method": "turnstile", "sitekey": sitekey, "pageurl": pageurl, "json": "1"}
    if action:
        params["action"] = action
    r = _http_json("https://2captcha.com/in.php", urllib.parse.urlencode(params).encode(),
                   headers={"Content-Type": "application/x-www-form-urlencoded"})
    if r.get("status") != 1:
        raise SolverError("2captcha in: " + json.dumps(r))
    cid = r["request"]
    t0 = time.time()
    while time.time() - t0 < timeout:
        q = urllib.parse.urlencode({"key": key, "action": "get", "id": cid, "json": "1"})
        r2 = _http_json("https://2captcha.com/res.php?" + q)
        if r2.get("status") == 1:
            return r2["request"]
        if "CAPCHA_NOT_READY" in str(r2.get("request", "")):
            time.sleep(6); continue
        raise SolverError("2captcha res: " + json.dumps(r2))
    raise SolverError("2captcha timeout")

# ---------------------------------------------------------------- yescaptcha
def solve_yescaptcha(sitekey, pageurl, action=None, proxy=None, timeout=300):
    key = _get("YESCAPTCHA_KEY")
    if not key:
        raise SolverError("yescaptcha: no YESCAPTCHA_KEY")
    task = {"type": "AntiTurnstileTaskProxyLess", "websiteURL": pageurl, "websiteKey": sitekey}
    if action:
        task["turnstileAction"] = action
    r = _http_json("https://api.yescaptcha.com/createTask",
                   {"clientKey": key, "task": task})
    if r.get("errorId"):
        raise SolverError("yescaptcha create: " + json.dumps(r)[:200])
    tid = r["taskId"]
    t0 = time.time()
    while time.time() - t0 < timeout:
        r2 = _http_json("https://api.yescaptcha.com/getTaskResult", {"clientKey": key, "taskId": tid})
        st = r2.get("status")
        if st == "ready":
            tok = (r2.get("solution") or {}).get("token")
            if tok:
                return tok
            raise SolverError("yescaptcha: no token in solution")
        if r2.get("errorId"):
            raise SolverError("yescaptcha get: " + json.dumps(r2)[:200])
        time.sleep(5)
    raise SolverError("yescaptcha timeout")

# ---------------------------------------------------------------- capmonster
def solve_capmonster(sitekey, pageurl, action=None, proxy=None, timeout=300):
    key = _get("CAPMONSTER_KEY")
    if not key:
        raise SolverError("capmonster: no CAPMONSTER_KEY")
    task = {"type": "TurnstileTaskProxyless", "websiteURL": pageurl, "websiteKey": sitekey}
    if action:
        task["turnstileAction"] = action
    r = _http_json("https://api.capmonster.cloud/createTask", {"clientKey": key, "task": task})
    if r.get("errorId"):
        raise SolverError("capmonster create: " + json.dumps(r)[:200])
    tid = r["taskId"]
    t0 = time.time()
    while time.time() - t0 < timeout:
        r2 = _http_json("https://api.capmonster.cloud/getTaskResult", {"clientKey": key, "taskId": tid})
        if r2.get("status") == "ready":
            tok = (r2.get("solution") or {}).get("token")
            if tok:
                return tok
        if r2.get("errorId"):
            raise SolverError("capmonster get: " + json.dumps(r2)[:200])
        time.sleep(5)
    raise SolverError("capmonster timeout")

# ---------------------------------------------------------------- anti-captcha
def solve_anticaptcha(sitekey, pageurl, action=None, proxy=None, timeout=300):
    key = _get("ANTICAPTCHA_KEY") or _get("ANTI_CAPTCHA_KEY")
    if not key:
        raise SolverError("anticaptcha: no ANTICAPTCHA_KEY")
    task = {"type": "TurnstileTaskProxyless", "websiteURL": pageurl, "websiteKey": sitekey}
    if action:
        task["turnstileAction"] = action
    r = _http_json("https://api.anti-captcha.com/createTask", {"clientKey": key, "task": task})
    if r.get("errorId"):
        raise SolverError("anticaptcha create: " + json.dumps(r)[:200])
    tid = r["taskId"]
    t0 = time.time()
    while time.time() - t0 < timeout:
        r2 = _http_json("https://api.anti-captcha.com/getTaskResult", {"clientKey": key, "taskId": tid})
        if r2.get("status") == "ready":
            tok = (r2.get("solution") or {}).get("token")
            if tok:
                return tok
        if r2.get("errorId"):
            raise SolverError("anticaptcha get: " + json.dumps(r2)[:200])
        time.sleep(5)
    raise SolverError("anticaptcha timeout")

BACKENDS = {
    "sidecar": solve_sidecar,
    "sidecar-realpage": solve_sidecar_realpage,
    "2captcha": solve_2captcha,
    "yescaptcha": solve_yescaptcha,
    "capmonster": solve_capmonster,
    "anticaptcha": solve_anticaptcha,
}

def solve_turnstile(sitekey, pageurl, action=None, proxy=None, chain=None, verbose=True):
    """Try each backend in chain order. Returns (token, backend_name). Raises SolverError if all fail."""
    chain = chain or [b.strip() for b in _get("CAPTCHA_BACKENDS", ",".join(DEFAULT_CHAIN)).split(",") if b.strip()]
    errors = []
    for name in chain:
        fn = BACKENDS.get(name)
        if not fn:
            errors.append(f"{name}: unknown backend")
            continue
        try:
            if verbose:
                print(f"  [captcha] trying {name}...")
            t0 = time.time()
            tok = fn(sitekey, pageurl, action=action, proxy=proxy)
            if verbose:
                print(f"  [captcha] {name} OK ({len(tok)} chars, {time.time()-t0:.1f}s)")
            return tok, name
        except SolverError as e:
            if verbose:
                print(f"  [captcha] {name} FAIL: {str(e)[:120]}")
            errors.append(f"{name}: {e}")
        except Exception as e:
            if verbose:
                print(f"  [captcha] {name} ERR: {repr(e)[:120]}")
            errors.append(f"{name}: {repr(e)[:120]}")
    raise SolverError("all backends failed: " + " | ".join(errors))

def backends_status():
    """Report which backends are configured/available."""
    out = {}
    out["sidecar"] = "url:" + _get("SIDECAR_URL", "http://127.0.0.1:8877")
    try:
        r = _http_json(out["sidecar"].split("url:")[1] + "/health", timeout=5)
        out["sidecar"] += " ONLINE"
    except Exception:
        out["sidecar"] += " offline"
    for name, envk in [("2captcha", "TWOCAPTCHA_KEY"), ("yescaptcha", "YESCAPTCHA_KEY"),
                       ("capmonster", "CAPMONSTER_KEY"), ("anticaptcha", "ANTICAPTCHA_KEY")]:
        out[name] = "key set" if _get(envk) else "no key"
    return out

if __name__ == "__main__":
    import sys
    print("backend status:")
    for k, v in backends_status().items():
        print(f"  {k:<12} {v}")
    if len(sys.argv) > 2:
        tok, be = solve_turnstile(sys.argv[1], sys.argv[2], action=sys.argv[3] if len(sys.argv) > 3 else None)
        print("token:", tok[:40] + "...", "via", be)
