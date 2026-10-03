#!/usr/bin/env python3
# probe_social: login -> POST /api/console/v1/rewards/social/{x,linkedin} -> check $0.50 credit
import asyncio, json, os, re, sys, urllib.request

BASE = "https://abliteration.ai"
HERE = os.path.dirname(os.path.abspath(__file__))
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

async def main():
    email, pw = sys.argv[1], sys.argv[2]
    from camoufox.async_api import AsyncCamoufox
    async with AsyncCamoufox(headless=True, humanize=False) as browser:
        ctx = await browser.new_context()
        page = await ctx.new_page()
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
        print("[*] url:", page.url)

        # rewards BEFORE
        before = await page.evaluate("""async () => {
            const r = await fetch("/api/console/v1/rewards", {credentials:"include"});
            return await r.text();
        }""")
        print("[before]", before[:400])

        # activate both platforms
        for plat in ["x", "linkedin"]:
            r = await page.evaluate("""async (p) => {
                try {
                    const r = await fetch("/api/console/v1/rewards/social/" + p, {
                        method: "POST", credentials: "include",
                        headers: {"Content-Type": "application/json"}
                    });
                    return r.status + " " + (await r.text()).slice(0, 400);
                } catch(e) { return "ERR " + e; }
            }""", plat)
            print(f"[activate {plat}]", r)

        await asyncio.sleep(3)
        after = await page.evaluate("""async () => {
            const r = await fetch("/api/console/v1/rewards", {credentials:"include"});
            return await r.text();
        }""")
        print("[after]", after[:500])

        # session for org id -> balance
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
            mb = re.search(r'"balance":\{[^}]*\}', bal)
            print("[balance]", mb.group(0) if mb else bal[:300])
        await ctx.close()

asyncio.run(main())
