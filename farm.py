#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
farm.py — one-command orchestrator for the whole abliteration.ai farm.

Pipeline (farm.py run N):
  1. register N accounts            (autoreg.py: FREE sidecar captcha -> paid fallbacks)
  2. harvest keys for any verified accounts missing one   (harvest_keys.py)
  3. run reward quests: claim social $0.50, record balances (quest_runner.py)
  4. report: accounts / keys / balances / ready-to-use keys

Other commands:
  python farm.py status              # full farm report (no browser needed)
  python farm.py run 5               # full pipeline, 5 new accounts
  python farm.py run 5 --proxy       # ... via ProxyGrab proxies
  python farm.py keys                # harvest missing keys only
  python farm.py quests              # reward quests only (claim $, balances)
  python farm.py quests --loop 600   # keep re-checking review approvals every 10min
  python farm.py gateway             # start OpenAI-compatible gateway (:8300 + dashboard)
  python farm.py export              # write keys.txt (keys WITH balance first) for the gateway

Everything appends to accounts.jsonl — safe to re-run at any time.
"""
import json, os, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
ACC_FILE = os.path.join(HERE, "accounts.jsonl")


def _py(script, *args):
    env = dict(os.environ)
    env["PYTHONPATH"] = ""
    cmd = [PY, os.path.join(HERE, script)] + list(args)
    print("\n$ " + " ".join(cmd))
    return subprocess.run(cmd, cwd=HERE, env=env).returncode


def load():
    rows = []
    if os.path.exists(ACC_FILE):
        for line in open(ACC_FILE, encoding="utf-8"):
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except Exception:
                    pass
    return rows


def status():
    rows = load()
    verified = [r for r in rows if r.get("verified")]
    with_key = [r for r in verified if r.get("api_key")]
    with_bal = [r for r in with_key if (r.get("balance_usd_micros") or 0) > 0]
    eligible = [r for r in verified if (r.get("rewards") or {}).get("eligible")]
    review = [r for r in verified if (r.get("rewards") or {}).get("eligible") is False]
    total_micros = sum(r.get("balance_usd_micros") or 0 for r in rows)
    print("=" * 62)
    print("  ABLITERATION FARM STATUS")
    print("=" * 62)
    print(f"  accounts total      : {len(rows)}")
    print(f"  verified            : {len(verified)}")
    print(f"  with API key        : {len(with_key)}")
    print(f"  reward-eligible     : {len(eligible)}")
    print(f"  in review (pending) : {len(review)}")
    print(f"  WITH BALANCE        : {len(with_bal)}  (${total_micros/1e6:.2f} total)")
    print("-" * 62)
    if with_bal:
        print("  ready-to-use keys (balance > 0):")
        for r in sorted(with_bal, key=lambda x: -(x.get("balance_usd_micros") or 0)):
            print(f"    ${r['balance_usd_micros']/1e6:<8.4f} {r['api_key']}")
    print("=" * 62)
    return {"total": len(rows), "keys": len(with_key), "with_balance": len(with_bal),
            "total_micros": total_micros}


def export_keys():
    """keys.txt for the gateway: balance-holders first, then the rest."""
    rows = load()
    with_key = [r for r in rows if r.get("api_key")]
    with_key.sort(key=lambda r: -(r.get("balance_usd_micros") or 0))
    out = os.path.join(HERE, "keys.txt")
    with open(out, "w", encoding="utf-8") as f:
        for r in with_key:
            f.write(r["api_key"] + "\n")
    nb = sum(1 for r in with_key if (r.get("balance_usd_micros") or 0) > 0)
    print(f"[export] {len(with_key)} keys -> keys.txt ({nb} with balance, sorted first)")


def main():
    args = sys.argv[1:]
    cmd = args[0] if args else "status"
    rest = args[1:]

    if cmd == "status":
        status()
    elif cmd == "run":
        n = next((a for a in rest if a.isdigit()), "1")
        extra = [a for a in rest if a.startswith("--")]
        _py("autoreg.py", n, *extra)
        _py("harvest_keys.py")
        _py("quest_runner.py")
        export_keys()
        status()
    elif cmd == "keys":
        _py("harvest_keys.py")
        export_keys()
        status()
    elif cmd == "quests":
        _py("quest_runner.py", *rest)
        export_keys()
        status()
    elif cmd == "gateway":
        export_keys()
        env = dict(os.environ)
        env["PYTHONPATH"] = ""
        env.setdefault("GATEWAY_API_KEY", "farm-master-key")
        print(f"\ngateway -> http://127.0.0.1:8300  (dashboard at /)")
        subprocess.run([PY, os.path.join(HERE, "gateway.py")], cwd=HERE, env=env)
    elif cmd == "export":
        export_keys()
    elif cmd == "reg":
        n = next((a for a in rest if a.isdigit()), "1")
        extra = [a for a in rest if a.startswith("--")]
        _py("autoreg.py", n, *extra)
        _py("harvest_keys.py")
        export_keys()
        status()
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
