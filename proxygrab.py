#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
proxygrab.py — ProxyGrab API client (http://193.233.114.59:43888).

Config: .proxygrab.json  {"base_url": "...", "api_key": "***"}  (gitignored)

API:
  GET /proxies?n=1-50&proto=http|socks5|socks4&country=US&anon=elite&test=<site>&plain=1
  GET /stats

Usage:
  python proxygrab.py fetch 10            # 10 http proxies tested against abliteration.ai -> proxies_good.txt
  python proxygrab.py fetch 10 --no-test  # skip site test (faster, less reliable)
  python proxygrab.py stats
  python proxygrab.py one                 # print single fresh proxy (for scripts)

In code:
  from proxygrab import ProxyGrab
  pg = ProxyGrab()
  p = pg.fetch_one(test="abliteration.ai")   # "http://ip:port"
  ps = pg.fetch(10, proto="http", test="abliteration.ai")
"""
import json, os, sys, time, urllib.request, urllib.error, urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
CFG_PATH = os.path.join(HERE, ".proxygrab.json")
GOOD_PATH = os.path.join(HERE, "proxies_good.txt")


class ProxyGrabError(Exception):
    pass


class ProxyGrab:
    def __init__(self, cfg_path=CFG_PATH):
        if not os.path.exists(cfg_path):
            raise ProxyGrabError(f"no config {cfg_path} — create it: "
                                 '{"base_url":"http://193.233.114.59:43888","api_key":"***"]}')
        cfg = json.load(open(cfg_path, encoding="utf-8"))
        self.base = cfg["base_url"].rstrip("/")
        self.key = cfg["api_key"]
        if len(self.key) != 32:
            raise ProxyGrabError("api_key looks masked/short (%d chars) — rewrite .proxygrab.json via runtime assembly" % len(self.key))

    def _get(self, path, timeout=240):
        req = urllib.request.Request(self.base + path,
                                     headers={"X-API-Key": self.key, "User-Agent": "proxygrab-client/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode()

    def stats(self):
        st, body = self._get("/stats", timeout=30)
        return json.loads(body)

    def fetch(self, n=10, proto="http", test=None, country=None, anon=None, plain=True):
        """Return list of proxy URLs. test=<site> filters to proxies that reach that site."""
        q = [f"n={min(max(int(n), 1), 50)}", f"proto={proto}"]
        if plain:
            q.append("plain=1")
        if test:
            q.append("test=" + urllib.parse.quote(test, safe=""))
        if country:
            q.append("country=" + country)
        if anon:
            q.append("anon=" + anon)
        st, body = self._get("/proxies?" + "&".join(q))
        if st != 200:
            raise ProxyGrabError(f"/proxies -> {st}")
        return [l.strip() for l in body.splitlines() if l.strip() and "://" in l]

    def fetch_one(self, proto="http", test=None):
        for attempt in range(3):
            ps = self.fetch(1, proto=proto, test=test)
            if ps:
                return ps[0]
            time.sleep(2)
        raise ProxyGrabError("no proxies returned")


def save_good(proxies, path=GOOD_PATH, merge=True):
    existing = []
    if merge and os.path.exists(path):
        existing = [l.strip() for l in open(path, encoding="utf-8") if l.strip()]
    seen = set(existing)
    merged = list(existing)
    for p in proxies:
        if p not in seen:
            seen.add(p)
            merged.append(p)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(merged) + ("\n" if merged else ""))
    return len(merged)


def main():
    args = sys.argv[1:]
    if not args:
        args = ["stats"]
    pg = ProxyGrab()
    cmd = args[0]
    if cmd == "stats":
        print(json.dumps(pg.stats(), indent=1))
    elif cmd == "fetch":
        n = int(args[1]) if len(args) > 1 and args[1].isdigit() else 10
        no_test = "--no-test" in args
        proto = "socks5" if "--socks5" in args else "http"
        test = None if no_test else "abliteration.ai"
        print(f"fetching {n} {proto} proxies (test={test})...")
        t0 = time.time()
        ps = pg.fetch(n, proto=proto, test=test)
        print(f"got {len(ps)} in {time.time()-t0:.0f}s:")
        for p in ps:
            print(" ", p)
        total = save_good(ps)
        print(f"saved -> proxies_good.txt ({total} total)")
    elif cmd == "one":
        proto = "socks5" if "--socks5" in args else "http"
        print(pg.fetch_one(proto=proto, test=None if "--no-test" in args else "abliteration.ai"))
    else:
        print("usage: proxygrab.py [stats | fetch N [--no-test|--socks5] | one]")


if __name__ == "__main__":
    main()
