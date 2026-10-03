#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
proxy_pool.py — proxy loading, liveness check, rotation.

Sources (first existing wins, or PROXY_FILE env):
  proxies.txt       — one per line: http://ip:port  or  scheme://user:pass@ip:port
  ../live_http_proxies.txt
  ../bpproxies_fresh.txt

Usage:
  python proxy_pool.py              # check all + report
  python proxy_pool.py check        # same
  python proxy_pool.py good         # print only working ones (saves proxies_good.txt)

In code:
  from proxy_pool import ProxyPool
  pool = ProxyPool()
  p = pool.next()        # "http://ip:port" or None
  pool.report_bad(p)     # mark failed
"""
import json, os, random, socket, sys, time, urllib.request, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))

def parse_line(line):
    """Normalize a proxy line to scheme://[user:pass@]host:port. Tolerates 'http://ip:port ip' junk."""
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    tok = line.split()[0]
    if "://" not in tok:
        tok = "http://" + tok
    return tok

def to_camoufox(proxy_url):
    """'http://user:pass@ip:port' -> {'server':..., 'username':..., 'password':...}"""
    if not proxy_url:
        return None
    from urllib.parse import urlparse
    p = urlparse(proxy_url)
    d = {"server": f"{p.scheme}://{p.hostname}:{p.port}"}
    if p.username:
        d["username"] = p.username
    if p.password:
        d["password"] = p.password
    return d

class ProxyPool:
    def __init__(self, path=None, only_good=True, refresh_sec=300):
        self.refresh_sec = refresh_sec
        self._last_live = 0.0
        self.path = path or os.environ.get("PROXY_FILE")
        if not self.path:
            for cand in [os.path.join(HERE, "proxies.txt"),
                         os.path.join(HERE, "proxies_good.txt"),
                         os.path.join(HERE, "..", "live_http_proxies.txt"),
                         os.path.join(HERE, "..", "bpproxies_fresh.txt")]:
                if os.path.exists(cand):
                    self.path = cand
                    break
        self.proxies = []
        self.bad = set()
        self._load(only_good)

    def _live_fetch(self):
        """ProxyGrab API live fetch (tested against target site). Returns count added."""
        if os.environ.get("USE_PROXYGRAB", "1") != "1":
            return 0
        try:
            from proxygrab import ProxyGrab
            pg = ProxyGrab()
            want = int(os.environ.get("PROXYGRAB_N", "8"))
            proto = os.environ.get("PROXYGRAB_PROTO", "http")
            test = os.environ.get("PROXYGRAB_TEST", "abliteration.ai")
            live = pg.fetch(want, proto=proto, test=test or None)
            added = 0
            for p in live:
                if p not in self.proxies:
                    self.proxies.append(p)
                    added += 1
                self.bad.discard(p)   # freshly tested = give another chance
            self._last_live = time.time()
            if live:
                print(f"[proxy] ProxyGrab: {len(live)} live (+{added} new, proto={proto}, test={test})")
            return added
        except Exception as e:
            print(f"[proxy] ProxyGrab unavailable ({str(e)[:80]}) — files fallback")
            return 0

    def _load(self, only_good):
        self._live_fetch()
        if not self.path or not os.path.exists(self.path):
            return
        seen = set(self.proxies)
        for line in open(self.path, encoding="utf-8", errors="replace"):
            p = parse_line(line)
            if p and p not in seen:
                seen.add(p)
                self.proxies.append(p)
        if only_good:
            gp = os.path.join(HERE, "proxies_good.txt")
            if os.path.exists(gp) and gp != self.path:
                for line in open(gp, encoding="utf-8", errors="replace"):
                    p = parse_line(line)
                    if p and p not in seen:
                        seen.add(p)
                        self.proxies.insert(0, p)   # known-good first

    def next(self):
        # refresh live proxies periodically (free ones die fast)
        if self.refresh_sec and time.time() - self._last_live > self.refresh_sec:
            self._live_fetch()
        alive = [p for p in self.proxies if p not in self.bad]
        if not alive:
            # everything burned -> force live refresh once
            self._live_fetch()
            alive = [p for p in self.proxies if p not in self.bad]
        if not alive:
            return None
        return random.choice(alive)

    def report_bad(self, proxy_url):
        if proxy_url:
            self.bad.add(proxy_url)

    def __len__(self):
        return len(self.proxies)


def check_one(proxy_url, timeout=12):
    """Return (ok, exit_ip_or_error)."""
    try:
        req = urllib.request.Request("https://api.ipify.org?format=json",
                                    headers={"User-Agent": "Mozilla/5.0"})
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url}))
        with opener.open(req, timeout=timeout) as r:
            d = json.loads(r.read().decode())
            return True, d.get("ip", "?")
    except Exception as e:
        return False, str(e)[:60]


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "check"
    pool = ProxyPool(only_good=False)
    print(f"loaded {len(pool)} proxies from {pool.path}")
    if not pool.proxies:
        print("no proxy file found — put proxies in proxies.txt (one per line)")
        return
    good = []
    for i, p in enumerate(pool.proxies, 1):
        ok, info = check_one(p)
        mark = "OK " if ok else "DEAD"
        print(f"[{i}/{len(pool.proxies)}] {mark} {p} -> {info}")
        if ok:
            good.append(p)
        if mode == "good" and len(good) >= 10:
            break
    out = os.path.join(HERE, "proxies_good.txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(good) + ("\n" if good else ""))
    print(f"\nworking: {len(good)}/{len(pool.proxies)} -> {out}")


if __name__ == "__main__":
    main()
