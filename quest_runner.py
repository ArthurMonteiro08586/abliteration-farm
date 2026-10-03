#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
quest_runner.py — maximize BALANCE on every account by completing all reward quests.

Reward system (abliteration.ai /api/console/v1/rewards):
  1. signup credit  $1.00 — auto-granted after email verify, BUT gated by async
                            anti-fraud review (review_required -> eligible:true later)
  2. social bundle  $0.50 — POST /rewards/social/x + /rewards/social/linkedin
                            (two POSTs, NO real social account needed) — only if eligible
  3. referrals      $0.50 each — referred user's first PAID request (max 3)
  Max promo per account = $3.00

This script, per account:
  - logs in (camoufox, submit inside password form — page also has OAuth buttons)
  - reads rewards + balance
  - if eligible and social not claimed -> claims X + LinkedIn (+$0.50)
  - records balance_usd_micros / rewards_eligible / social_claimed into accounts.jsonl
  - review_required accounts are retried (review passes async, ~30-60min)

Usage:
  python quest_runner.py                # all verified accounts
  python quest_runner.py --review-only  # only accounts still in review_required
  python quest_runner.py --loop 600     # re-check every 600s (catch review approvals)
  python quest_runner.py --max-bal      # report accounts that reached max balance
"""
import asyncio, json, os, re, sys, time, urllib.request

BASE = "https://abliteration.ai"
HERE = os.path.dirname(os.path.abspath(__file__))
ACC_FILE = os.path.join(HERE, "accounts.jsonl")
AUTH = "Bea" + "rer "


async def set_react_input(page, selector, value):
    await page.evaluate("""([sel, val]) => {
        const el = document.querySelector(sel);
        if (!el) throw new Error("no input " + sel);
        const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
        setter.call(el, val);
        el.dispatchEvent(new Event("input", {bubbles: true}));
        el.dispatchEvent(new Event("change", {bubbles: true}));
    }""", [selector, value])


def load_accounts():
    accs = []
    if os.path.exists(ACC_FILE):
        for line in open(ACC_FILE, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                accs.append(json.loads(line))
            except Exception:
                pass
    return accs


def save_accounts(accs):
    tmp = ACC_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for a in accs:
            f.write(json.dumps(a, ensure_ascii=False) + "\n")
    os.replace(tmp, ACC_FILE)


async def process_one(acc, browser):
    email, pw = acc["email"], acc["password"]
    res = {"email": email, "eligible": None, "signup_micros": 0, "social": None,
           "balance": 0, "claimed_now": False, "error": None}
    ctx = await browser.new_context()
    page = await ctx.new_page()
    try:
        await page.goto(BASE + "/sign-in", wait_until="domcontentloaded", timeout=90000)
        await page.wait_for_selector('input[name="password"]', timeout=45000)
        await asyncio.sleep(1)
        await set_react_input(page, 'input[name="email"]', email)
        await set_react_input(page, 'input[name="password"]', pw)
        await page.evaluate("""() => {
            const f = document.querySelector('input[name="password"]').closest('form');
            const b = f.querySelector('button[type="submit"]') || Array.from(f.querySelectorAll('button')).pop();
            b.click();
        }""")
        await asyncio.sleep(6)
        if "accounts.google" in page.url:
            res["error"] = "oauth-redirect"
            await ctx.close()
            return res

        async def jfetch(path, method="GET", body=None):
            return await page.evaluate("""async ([p, m, b]) => {
                try {
                    const opt = {method: m, credentials: "include", headers: {"Content-Type":"application/json"}};
                    if (b) opt.body = JSON.stringify(b);
                    const r = await fetch(p, opt);
                    return {status: r.status, body: await r.text()};
                } catch(e) { return {status: 0, body: String(e)}; }
            }""", [path, method, body])

        # workspace may still be provisioning
        rw = None
        for i in range(12):
            r = await jfetch("/api/console/v1/rewards")
            if r["status"] == 200 and "workspace_setup_pending" not in r["body"]:
                try:
                    rw = json.loads(r["body"])
                except Exception:
                    rw = None
                if rw:
                    break
            await asyncio.sleep(4)

        if not rw:
            res["error"] = "no-rewards"
            await ctx.close()
            return res

        res["eligible"] = rw.get("eligible")
        res["signup_micros"] = rw.get("signup_credit_usd_micros", 0)
        bundle = rw.get("social_bundle") or {}
        res["social"] = bundle.get("status")

        # claim social bundle if eligible and not claimed
        if rw.get("eligible") and bundle.get("status") != "claimed":
            for plat in ["x", "linkedin"]:
                rr = await jfetch(f"/api/console/v1/rewards/social/{plat}", "POST", {})
                if rr["status"] == 200:
                    res["claimed_now"] = True
            await asyncio.sleep(2)
            # re-read
            r2 = await jfetch("/api/console/v1/rewards")
            try:
                rw2 = json.loads(r2["body"])
                res["social"] = (rw2.get("social_bundle") or {}).get("status")
            except Exception:
                pass

        # balance
        sess = await jfetch("/api/console/v1/session")
        m = re.search(r'org_[A-Za-z0-9_\-]+', sess["body"])
        if m:
            bal = await jfetch(f"/api/console/v1/organizations/{m.group(0)}/billing/summary")
            mb = re.search(r'"available_usd_micros":(\d+)', bal["body"])
            if mb:
                res["balance"] = int(mb.group(1))
    except Exception as e:
        res["error"] = repr(e)[:120]
    await ctx.close()
    return res


async def run_pass(accs, review_only=False):
    from camoufox.async_api import AsyncCamoufox
    todo = [a for a in accs if a.get("verified")]
    if review_only:
        todo = [a for a in todo if (a.get("rewards") or {}).get("eligible") is not True
                and not a.get("social_claimed")]
    if not todo:
        print("nothing to do")
        return
    print(f"quest pass: {len(todo)} accounts")
    total_balance = 0
    n_eligible = 0
    n_claimed = 0
    idx = {a["email"]: a for a in accs}
    async with AsyncCamoufox(headless=True, humanize=False, geoip=True) as browser:
        for a in todo:
            r = await process_one(a, browser)
            tgt = idx.get(r["email"], a)
            tgt["rewards"] = {"eligible": r["eligible"], "signup_micros": r["signup_micros"],
                              "social": r["social"]}
            tgt["balance_usd_micros"] = r["balance"]
            if r["claimed_now"]:
                tgt["social_claimed"] = True
                n_claimed += 1
            if r["eligible"]:
                n_eligible += 1
            total_balance += r["balance"]
            bal_s = f"${r['balance']/1e6:.4f}" if r["balance"] else "$0"
            print(f"  {r['email'][:32]:<33} eligible={r['eligible']} signup={r['signup_micros']} "
                  f"social={r['social']} bal={bal_s}"
                  + (f" CLAIMED+0.5" if r["claimed_now"] else "")
                  + (f" ERR:{r['error']}" if r["error"] else ""))
    save_accounts(accs)
    print(f"\npass done: eligible={n_eligible} claimed_now={n_claimed} total_balance=${total_balance/1e6:.2f}")


async def main():
    loop_sec = None
    review_only = "--review-only" in sys.argv
    if "--loop" in sys.argv:
        i = sys.argv.index("--loop")
        loop_sec = int(sys.argv[i + 1]) if len(sys.argv) > i + 1 else 600
    while True:
        accs = load_accounts()
        await run_pass(accs, review_only=review_only)
        if not loop_sec:
            break
        print(f"\n[loop] sleeping {loop_sec}s (re-check review approvals)... Ctrl+C to stop")
        await asyncio.sleep(loop_sec)


if __name__ == "__main__":
    asyncio.run(main())
