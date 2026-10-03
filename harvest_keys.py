#!/usr/bin/env python3
# harvest_keys.py — login to verified accounts with api_key=null, create key via REST, update accounts.jsonl
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

async def harvest_one(acc, browser):
    email, pw = acc["email"], acc["password"]
    print(f"\n=== {email} ===")
    ctx = await browser.new_context()
    page = await ctx.new_page()
    key = None
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
        print("  [*] url:", page.url)
        if "accounts.google" in page.url:
            print("  [!] wrong button clicked (OAuth)")
            await ctx.close()
            return None

        # poll session until workspace ready (up to 120s)
        sess = ""
        proj_id = ""
        for i in range(24):
            sess = await page.evaluate("""async () => {
                const r = await fetch("/api/console/v1/session", {credentials:"include"});
                return await r.text();
            }""")
            if "workspace_setup_pending" in sess:
                print(f"  [*] workspace pending ({i+1}/24)")
                await asyncio.sleep(5)
                continue
            m = re.search(r'proj_[A-Za-z0-9_\-]+', sess)
            if m:
                proj_id = m.group(0)
                break
            await asyncio.sleep(5)
        print("  [*] proj:", proj_id)
        if not proj_id:
            await ctx.close()
            return None

        created = await page.evaluate("""async (projId) => {
            const idem = crypto.randomUUID ? crypto.randomUUID() : ("idem-" + Date.now());
            const r = await fetch("/api/console/v1/projects/" + projId + "/api-keys", {
                method: "POST", credentials: "include",
                headers: {"Content-Type":"application/json", "Idempotency-Key": idem},
                body: JSON.stringify({name: "autoreg"})
            });
            return {status: r.status, body: await r.text()};
        }""", proj_id)
        print("  [*] create key ->", created["status"], created["body"][:200])
        if created["status"] in (200, 201):
            try:
                j = json.loads(created["body"])
                key = j.get("secret_key")
            except Exception:
                m = re.search(r'"secret_key":"([^"]+)"', created["body"])
                key = m.group(1) if m else None
        if key:
            print("  [+] KEY:", key[:14] + "..." + key[-4:])
        # rewards/balance snapshot
        rw = await page.evaluate("""async () => {
            const r = await fetch("/api/console/v1/rewards", {credentials:"include"});
            return await r.text();
        }""")
        try:
            rwj = json.loads(rw)
            print("  [*] rewards: eligible=%s status=%s signup=%s social=%s ref_each=%s" % (
                rwj.get("eligible"), rwj.get("status"), rwj.get("signup_credit_usd_micros"),
                (rwj.get("social_bundle") or {}).get("amount_usd_micros"),
                (rwj.get("referrals") or {}).get("amount_each_usd_micros")))
        except Exception:
            print("  [*] rewards raw:", rw[:200])
    except Exception as e:
        print("  [!] err:", repr(e)[:250])
    await ctx.close()
    return key

async def main():
    only_missing = "--all" not in sys.argv
    accs = load_accounts()
    todo = [a for a in accs if a.get("verified") and (not only_missing or not a.get("api_key"))]
    print(f"accounts: {len(accs)} total, {len(todo)} to harvest")
    if not todo:
        return
    from camoufox.async_api import AsyncCamoufox
    async with AsyncCamoufox(headless=True, humanize=False) as browser:
        for a in todo:
            key = await harvest_one(a, browser)
            if key:
                a["api_key"] = key
                a["harvested"] = True
    save_accounts(accs)
    n_keys = sum(1 for a in accs if a.get("api_key"))
    print(f"\nDONE: {n_keys} accounts now have keys / {len(accs)} total")

asyncio.run(main())
