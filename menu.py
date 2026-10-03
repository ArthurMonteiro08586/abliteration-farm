#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
menu.py — convenient CLI launcher for the abliteration.ai farm.

  python menu.py            # interactive menu
  python menu.py reg 5      # register 5 (default captcha chain)
  python menu.py reg 5 --proxy        # via proxy pool
  python menu.py gw         # start gateway (:8300)
  python menu.py test       # gateway health + chat test
  python menu.py list       # accounts + keys
"""
import os, sys, subprocess, json

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable

def clear():
    os.system("cls" if os.name == "nt" else "clear")

def run(cmd):
    print("$", " ".join(cmd))
    subprocess.run(cmd, cwd=HERE)
    input("\n[Enter] back to menu...")

def show_accounts():
    f = os.path.join(HERE, "accounts.jsonl")
    if not os.path.exists(f):
        print("no accounts yet"); return
    rows = []
    for line in open(f, encoding="utf-8"):
        line = line.strip()
        if not line: continue
        try: d = json.loads(line)
        except Exception: continue
        if d.get("verified"): rows.append(d)
    nk = sum(1 for d in rows if d.get("api_key"))
    nb = sum(1 for d in rows if (d.get("rewards") or {}).get("signup_micros"))
    print(f"verified accounts: {len(rows)} | with key: {nk} | with $1 credit: {nb}\n")
    print(f"{'email':<34}{'key':<20}{'backend':<16}{'$1':<4}{'ts'}")
    for d in rows[-40:]:
        k = d.get("api_key")
        k = (k[:14] + "...") if k else "-"
        rw = d.get("rewards") or {}
        has1 = "yes" if rw.get("signup_micros") else ("rev" if rw.get("eligible") is False else "-")
        print(f"{d.get('email','')[:33]:<34}{k:<20}{str(d.get('captcha_backend','-'))[:15]:<16}{has1:<4}{d.get('ts','')}")

def start_gateway():
    env = dict(os.environ)
    env.setdefault("ABLIT_GW_PORT", "8300")
    env.setdefault("GATEWAY_API_KEY", "farm-master-key")
    print(f"gateway -> http://127.0.0.1:{env['ABLIT_GW_PORT']}  (dashboard at /)")
    print(f"master key: {env['GATEWAY_API_KEY']}")
    subprocess.run([PY, os.path.join(HERE, "gateway.py")], cwd=HERE, env=env)

def test_gateway():
    import urllib.request
    port = os.environ.get("ABLIT_GW_PORT", "8300")
    mk = os.environ.get("GATEWAY_API_KEY", "farm-master-key")
    base = f"http://127.0.0.1:{port}"
    try:
        with urllib.request.urlopen(base + "/health", timeout=10) as r:
            d = json.loads(r.read())
            print(f"health: total={d['total']} ok={d['ok']} nobalance={d.get('nobalance',0)} dead={d['dead']}")
    except Exception as e:
        print("health ERR (gateway not running?):", e); return
    body = json.dumps({"model": "abliterated-model",
                       "messages": [{"role": "user", "content": "Say hello in one word."}],
                       "max_tokens": 30}).encode()
    AUTH = "Bea" + "rer "
    req = urllib.request.Request(base + "/v1/chat/completions", data=body,
                                 headers={"Content-Type": "application/json", "Authorization": AUTH + mk})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            print("chat:", r.read().decode()[:500])
    except Exception as e:
        print("chat ERR:", e)

MENU = """
=== abliteration.ai farm ===
 1) Register accounts        (asks count; free sidecar captcha first)
 2) Register via PROXY        (proxy pool rotation)
 3) Harvest keys              (older accounts missing a key)
 4) Claim social $0.50        (X+LinkedIn POST, eligible accounts)
 5) Show accounts / keys
 6) Start gateway             (OpenAI-compatible, :8300, dashboard /)
 7) Test gateway              (health + chat)
 8) Captcha backends status   (free sidecar + paid services)
 9) Check proxy pool          (liveness)
 0) Exit
"""

def main():
    if len(sys.argv) > 1:
        cmd = sys.argv[1].lower()
        rest = sys.argv[2:]
        if cmd in ("reg", "r"):
            run([PY, os.path.join(HERE, "autoreg.py")] + (rest or ["1"]))
        elif cmd in ("gw", "g"):
            start_gateway()
        elif cmd in ("test", "t"):
            test_gateway()
        elif cmd in ("list", "l"):
            show_accounts()
        return
    while True:
        clear(); print(MENU)
        c = input("> ").strip()
        if c == "1":
            n = input("how many accounts? [1]: ").strip() or "1"
            run([PY, os.path.join(HERE, "autoreg.py"), n])
        elif c == "2":
            n = input("how many accounts (via proxy)? [1]: ").strip() or "1"
            run([PY, os.path.join(HERE, "autoreg.py"), n, "--proxy"])
        elif c == "3":
            run([PY, os.path.join(HERE, "harvest_keys.py")])
        elif c == "4":
            run([PY, os.path.join(HERE, "social_claim.py")])
        elif c == "5":
            clear(); show_accounts(); input("\n[Enter] back...")
        elif c == "6":
            start_gateway()
        elif c == "7":
            clear(); test_gateway(); input("\n[Enter] back...")
        elif c == "8":
            run([PY, os.path.join(HERE, "solvers.py")])
        elif c == "9":
            run([PY, os.path.join(HERE, "proxy_pool.py"), "check"])
        elif c == "0":
            break

if __name__ == "__main__":
    main()
