# probe_balance: login old verified account -> check rewards/balance/referral + create api key
import asyncio, json, os, re, sys

BASE = "https://abliteration.ai"
HERE = os.path.dirname(os.path.abspath(__file__))

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
        keyxhr = []
        async def on_resp(resp):
            u = resp.url
            if "abliteration.ai" in u and any(k in u for k in ["api-keys", "reward", "balance", "billing"]):
                try:
                    b = (await resp.text())[:1500]
                except Exception:
                    b = "?"
                keyxhr.append((resp.status, u, b))
                print("  [xhr]", resp.status, u.split("?")[0], "::", b[:400])
        page.on("response", on_resp)

        await page.goto(BASE + "/sign-in", wait_until="domcontentloaded", timeout=90000)
        await page.wait_for_selector('input[name="password"]', timeout=45000)
        await asyncio.sleep(1)
        await set_react_input(page, 'input[name="email"]', email)
        await set_react_input(page, 'input[name="password"]', pw)
        # click submit INSIDE the password form (not Google OAuth button)
        await page.evaluate("""() => {
            const f = document.querySelector('input[name="password"]').closest('form');
            const b = f.querySelector('button[type="submit"]') || Array.from(f.querySelectorAll('button')).pop();
            b.click();
        }""")
        await asyncio.sleep(8)
        print("  [*] after login:", page.url)

        # fetch all interesting endpoints in page context
        data = await page.evaluate("""async () => {
            const out = {};
            const eps = {
                session: "/api/console/v1/session",
                rewards: "/api/console/v1/rewards",
            };
            for (const [k, p] of Object.entries(eps)) {
                try { const r = await fetch(p, {credentials:"include"}); out[k] = await r.text(); } catch(e){ out[k] = "ERR " + e; }
            }
            return out;
        }""")
        print("=== session ===")
        print(data.get("session", "")[:800])
        print("=== rewards ===")
        print(data.get("rewards", "")[:800])

        m = re.search(r'org_[A-Za-z0-9_\-]+', data.get("session", ""))
        org_id = m.group(0) if m else ""
        proj_id = ""
        if org_id:
            pt = await page.evaluate("""async (o) => {
                const r = await fetch("/api/console/v1/organizations/" + o + "/projects", {credentials:"include"});
                return await r.text();
            }""", org_id)
            pm = re.search(r'proj_[A-Za-z0-9_\-]+', pt)
            proj_id = pm.group(0) if pm else ""
            # billing summary + rewards for org
            for name, path in [("billing_summary", f"/api/console/v1/organizations/{org_id}/billing/summary"),
                               ("credits", f"/api/console/v1/organizations/{org_id}/credits"),
                               ("balance", f"/api/console/v1/organizations/{org_id}/balance"),
                               ("rewards_org", f"/api/console/v1/organizations/{org_id}/rewards"),
                               ("referral", f"/api/console/v1/organizations/{org_id}/referral"),
                               ("api_keys_list", f"/api/console/v1/organizations/{org_id}/projects/{proj_id}/api-keys")]:
                r = await page.evaluate("""async (p) => {
                    try { const r = await fetch(p, {credentials:"include"}); return r.status + " " + (await r.text()).slice(0,600); } catch(e){ return "ERR " + e; }
                }""", path)
                print(f"=== {name} ===")
                print(r[:650])
        print("  [*] org:", org_id, "proj:", proj_id)

        # navigate to api-keys page and try create
        if proj_id:
            await page.goto(BASE + f"/console/projects/{proj_id}/api-keys", wait_until="domcontentloaded", timeout=45000)
            await asyncio.sleep(3)
            html = await page.content()
            open(os.path.join(HERE, "dump_apikeys_probe.html"), "w", encoding="utf-8").write(html)
            btns = await page.evaluate("""() => Array.from(document.querySelectorAll('button, a')).map(b => (b.textContent||'').trim()).filter(t => t && t.length < 40).slice(0,60)""")
            print("  [buttons]", btns)
            # click create
            for sel in ['button:has-text("Create API key")', 'a:has-text("Create API key")', 'button:has-text("Create key")', 'button:has-text("New API key")']:
                loc = page.locator(sel).first
                try:
                    if await loc.count():
                        await loc.click(timeout=8000)
                        print("  [*] clicked", sel)
                        break
                except Exception:
                    continue
            await asyncio.sleep(2.5)
            try:
                await page.screenshot(path=os.path.join(HERE, "apikeys_modal.png"))
            except Exception: pass
            # modal fields?
            inputs = await page.evaluate("""() => Array.from(document.querySelectorAll('input:not([type=hidden])')).map(i => ({name: i.name, type: i.type, placeholder: i.placeholder, visible: i.offsetParent !== null}))""")
            print("  [inputs]", inputs)
            html2 = await page.content()
            m2 = re.findall(r"sk-[A-Za-z0-9_\-]{16,}", html2)
            print("  [*] sk- in html after click:", m2[:2])
        await ctx.close()

asyncio.run(main())
