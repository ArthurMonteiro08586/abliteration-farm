# probe_createkey: login -> POST create api key via REST
import asyncio, json, os, re, sys

BASE = "https://abliteration.ai"

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
        await asyncio.sleep(8)
        print("[*] url:", page.url)

        sess = await page.evaluate("""async () => {
            const r = await fetch("/api/console/v1/session", {credentials:"include"});
            return await r.text();
        }""")
        proj = re.search(r'proj_[A-Za-z0-9_\-]+', sess)
        proj_id = proj.group(0) if proj else ""
        print("[*] proj:", proj_id)

        # try POST with Idempotency-Key header
        variants = [
            ("/api/console/v1/projects/" + proj_id + "/api-keys", {"name": "autoreg"}),
        ]
        for path, body in variants:
            r = await page.evaluate("""async ([p, b]) => {
                try {
                    const idem = (crypto && crypto.randomUUID) ? crypto.randomUUID() : ("idem-" + Date.now() + "-" + Math.random().toString(36).slice(2));
                    const r = await fetch(p, {method:"POST", credentials:"include",
                        headers:{"Content-Type":"application/json", "Idempotency-Key": idem}, body: JSON.stringify(b)});
                    return r.status + " " + (await r.text()).slice(0, 1500);
                } catch(e) { return "ERR " + e; }
            }""", [path, body])
            print("POST", json.dumps(body)[:60], "->", r[:1550])
        # list keys
        r2 = await page.evaluate("""async (p) => {
            const r = await fetch(p, {credentials:"include"});
            return r.status + " " + (await r.text()).slice(0, 1500);
        }""", "/api/console/v1/projects/" + proj_id + "/api-keys")
        print("GET list ->", r2[:1500])
        await ctx.close()

asyncio.run(main())
