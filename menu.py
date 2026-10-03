#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
abliteration-farm menu — convenient CLI launcher.

Usage:
  python menu.py            # interactive menu
  python menu.py reg 5      # register 5 accounts (no menu)
  python menu.py gw         # start gateway
  python menu.py test       # test gateway chat
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
        print("no accounts yet")
        return
    rows = []
    for line in open(f, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue
        if d.get("verified"):
            rows.append(d)
    print(f"total verified accounts: {len(rows)}\n")
    print(f"{'email':<40} {'key':<24} {'ts'}")
    for d in rows[-30:]:
        k = d.get("api_key") or "-"
        if k != "-":
            k = k[:16] + "..."
        print(f"{d.get('email',''):<40} {k:<24} {d.get('ts','')}")
    if not rows:
        print("no verified accounts yet")

def start_gateway():
    env = dict(os.environ)
    env.setdefault("ABLIT_GW_PORT", "8300")
    if not env.get("GATEWAY_API_KEY"):
        env["GATEWAY_API_KEY"] = "farm-master-key"
    print(f"gateway on http://127.0.0.1:{env['ABLIT_GW_PORT']}")
    print(f"master key: {env['GATEWAY_API_KEY']}")
    subprocess.run([PY, os.path.join(HERE, "gateway.py")], cwd=HERE, env=env)

def test_gateway():
    import urllib.request
    port = os.environ.get("ABLIT_GW_PORT", "8300")
    mk = os.environ.get("GATEWAY_API_KEY", "farm-master-key")
    base = f"http://127.0.0.1:{port}"
    # health
    try:
        with urllib.request.urlopen(base + "/health", timeout=10) as r:
            print("health:", r.read().decode()[:300])
    except Exception as e:
        print("health ERR (gateway not running?):", e)
        return
    # chat
    body = json.dumps({"model": "abliterated-model", "messages": [{"role": "user", "content": "Say hello in one word."}], "max_tokens": 16}).encode()
    req = urllib.request.Request(base + "/v1/chat/completions", data=body,
                                 headers={"Content-Type": "application/json", "Authorization": "***" + mk})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            print("chat:", r.read().decode()[:600])
    except Exception as e:
        print("chat ERR:", e)

MENU = """
=== abliteration.ai farm ===
 1) Register accounts (autoreg, asks count)
 2) Show accounts / keys
 3) Start gateway (OpenAI-compatible, :8300)
 4) Test gateway (health + chat)
 5) Balance check (2captcha)
 0) Exit
"""

def main():
    if len(sys.argv) > 1:
        cmd = sys.argv[1].lower()
        if cmd in ("reg", "r", "1"):
            n = sys.argv[2] if len(sys.argv) > 2 else "1"
            run([PY, os.path.join(HERE, "autoreg6.py"), n])
        elif cmd in ("gw", "g", "3"):
            start_gateway()
        elif cmd in ("test", "t", "4"):
            test_gateway()
        elif cmd in ("list", "l", "2"):
            show_accounts()
        return
    while True:
        clear()
        print(MENU)
        c = input("> ").strip()
        if c == "1":
            n = input("how many accounts? [1]: ").strip() or "1"
            run([PY, os.path.join(HERE, "autoreg6.py"), n])
        elif c == "2":
            clear(); show_accounts(); input("\n[Enter] back...")
        elif c == "3":
            start_gateway()
        elif c == "4":
            clear(); test_gateway(); input("\n[Enter] back...")
        elif c == "5":
            run([PY, os.path.join(HERE, "check_balances.py")])
        elif c == "0":
            break

if __name__ == "__main__":
    main()
