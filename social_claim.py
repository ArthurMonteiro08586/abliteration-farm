#!/usr/bin/env python3
# social_claim.py — claim $0.50 social bundle (X+LinkedIn) for eligible accounts.
# POST /api/console/v1/rewards/social/{x,linkedin} — no real social actions needed.
# Only works when rewards eligible=true (after signup-credit review passes).
import asyncio, json, os, re, sys

BASE = "https://abliteration.ai"
HERE = os.path.dirname(os.path.abspath(__file__))
ACC_FILE = os.path.join(HERE, "accounts.jsonl")

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
    for line in open(ACC_FILE, encoding="utf-8"):
        line = line.strip()
        if line:
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

async def claim_one(acc, browser):
    email, pw = acc["email"], acc["password"]
    ctx = await browser.new_context()
    page = await ctx.new_page()
    result = {"email": email, "eligible": False, "claimed": False, "balance": 0}
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
            print(f"  [!] {email}: OAuth redirect (bad click)")
            await ctx.close()
            return result

        rw = await page.evaluate("""async () => {
            const r = await fetch("/api/console/v1/rewards", {credentials:"include"});
            return await r.text();
        }""")
        try:
            rwj = json.loads(rw)
        except Exception:
            rwj = {}
        eligible = rwj.get("eligible", False)
        bundle = (rwj.get("social_bundle") or {}).get("status")
        print(f"  [*] {email}: eligible={eligible} social={bundle}")
        result["eligible"] = eligible
        if not eligible:
            await ctx.close()
            return result

        if bundle == "claimed":
            print(f"  [+] {email}: already claimed")
            result["claimed"] = True
        else:
            ok = True
            for plat in ["x", "linkedin"]:
                r = await page.evaluate("""async (p) => {
                    try {
                        const r = await fetch("/api/console/v1/rewards/social/" + p, {
                            method: "POST", credentials: "include",
                            headers: {"Content-Type": "application/json"}
                        });
                        return r.status + " " + (await r.text()).slice(0, 200);
                    } catch(e) { return "ERR " + e; }
                }""", plat)
                print(f"  [{plat}] {r[:120]}")
                if not r.startswith("200"):
                    ok = False
            result["claimed"] = ok

        # balance
        sess = await page.evaluate("""async () => {
            const r = await fetch("/api/console/v1/session", {credentials:"include"});
            return await r.text();
        }""")
        m = re.search(r'org_[A-Za-z0-9_\-]+', sess)
        if m:
            bal = await page.evaluate("""async (o) => {
                const r = await fetch("/api/console/v1/organizations/" + o + "/billing/summary", {credentials:"include"});
                return await r.text();
            }""", m.group(0))
            mb = re.search(r'"available_usd_micros":(\d+)', bal)
            if mb:
                result["balance"] = int(mb.group(1))
        print(f"  [balance] ${result['balance']/1e6:.4f}")
    except Exception as e:
        print(f"  [!] {email} err:", repr(e)[:150])
    await ctx.close()
    return result

async def main():
    accs = load_accounts()
    todo = [a for a in accs if a.get("verified")]
    print(f"accounts to claim: {len(todo)}")
    from camoufox.async_api import AsyncCamoufox
    total_claimed = 0
    total_balance = 0
    async with AsyncCamoufox(headless=True, humanize=False) as browser:
        for a in todo:
            r = await claim_one(a, browser)
            if r["claimed"]:
                a["social_claimed"] = True
                total_claimed += 1
            if r["balance"]:
                a["balance_usd_micros"] = r["balance"]
                total_balance += r["balance"]
    save_accounts(accs)
    print(f"\nDONE: claimed={total_claimed} total_balance=${total_balance/1e6:.2f}")

asyncio.run(main())
