# autoreg6: camoufox (Firefox anti-detect) + 2captcha Turnstile (action=password_signup)
# + stub window.turnstile -> React native submit with correlation + radar signalsId
import asyncio, json, os, re, sys, time, random, string, urllib.request, urllib.parse

BASE = "https://abliteration.ai"
SIGNUP_URL = BASE + "/sign-up?referral_code=ref_yrd8gnW-d4ir"
REFERRAL = "ref_yrd8gnW-d4ir"
SITEKEY = "0x4AAAAAAEcO2qYYBE_ztENL"
TS_ACTION = "password_signup"
HERE = os.path.dirname(os.path.abspath(__file__))
ACC_FILE = os.path.join(HERE, "accounts.jsonl")
DEBUG = os.environ.get("DEBUG", "1") == "1"

STUB_JS = """
window.__CAPTCHA_TOKEN__ = __TOKEN_PLACEHOLDER__;
(function(){
  if (window.turnstile && window.turnstile.__stub) return;
  var W = {};
  function fire(opts){
    if (!opts) return;
    try { if (opts["before-interactive-callback"]) opts["before-interactive-callback"](); } catch(e){}
    setTimeout(function(){
      try {
        if (typeof opts.callback === "function") opts.callback(window.__CAPTCHA_TOKEN__ || "");
      } catch(e){ console.error("stub cb err", e); }
    }, 250);
  }
  window.turnstile = {
    __stub: true,
    render: function(el, opts){
      var id = "stub-" + Math.random().toString(36).slice(2);
      W[id] = opts;
      if (el && el.appendChild && !el.querySelector(".cf-stub")) {
        var d = document.createElement("div");
        d.className = "cf-stub";
        d.textContent = "verifying...";
        el.appendChild(d);
      }
      fire(opts);
      return id;
    },
    reset: function(id){ fire(W[id]); },
    remove: function(id){ delete W[id]; },
    getResponse: function(){ return window.__CAPTCHA_TOKEN__ || ""; },
    isReady: function(cb){ if (cb) cb(); }
  };
})();
"""

def load_env():
    p = os.path.join(os.path.expanduser("~"), "Desktop", "_PROJECTS",
                     "\u0430\u0432\u0442\u043e\u0440\u0435\u0433 \u043f\u0440\u043e\u0435\u043a\u0442", ".env")
    env = {}
    for line in open(p, encoding="utf-8"):
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env

ENV = load_env()
TK = ENV.get("TWOCAPTCHA_KEY", "")

def _2c(url, data=None, timeout=40):
    if data is not None:
        req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode())
    else:
        req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())

def twocaptcha_solve():
    resp = _2c("https://2captcha.com/in.php", {
        "key": TK, "method": "turnstile", "sitekey": SITEKEY,
        "pageurl": SIGNUP_URL, "action": TS_ACTION, "json": "1",
    })
    if resp.get("status") != 1:
        raise RuntimeError("2captcha submit failed: " + json.dumps(resp))
    cid = resp["request"]
    print("  [*] 2captcha id:", cid)
    t0 = time.time()
    while time.time() - t0 < 300:
        r2 = _2c("https://2captcha.com/res.php", {"key": TK, "action": "get", "id": cid, "json": "1"})
        if r2.get("status") == 1:
            tok = r2["request"]
            print("  [+] 2captcha token", len(tok), "chars")
            return cid, tok
        if "CAPCHA_NOT_READY" in str(r2.get("request", "")):
            time.sleep(6); continue
        raise RuntimeError("2captcha get failed: " + json.dumps(r2))
    raise TimeoutError("2captcha timeout")

def voidash_inbox(domain="voidash.bond"):
    body = json.dumps({"domain": domain}).encode()
    req = urllib.request.Request("https://api.voidash.com/api/v1/inboxes", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        resp = json.loads(r.read().decode())
    data = resp.get("data", resp)
    sk = data.get("session_key") or data.get("sessionKey")
    email = data.get("address") or data.get("email")
    if not sk or not email:
        raise RuntimeError("voidash bad resp: " + json.dumps(resp)[:200])
    return email, sk

def voidash_wait_code(sk, timeout=240):
    t0 = time.time()
    while time.time() - t0 < timeout:
        req = urllib.request.Request("https://api.voidash.com/api/v1/messages",
                                     headers={"Authorization": "Bearer " + sk})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                resp = json.loads(r.read().decode())
        except Exception:
            try:
                req2 = urllib.request.Request("https://api.voidash.com/api/v1/inboxes/messages",
                                              headers={"Authorization": "Bearer " + sk})
                with urllib.request.urlopen(req2, timeout=30) as r:
                    resp = json.loads(r.read().decode())
            except Exception:
                time.sleep(5); continue
        msgs = []
        if isinstance(resp, dict):
            msgs = resp.get("messages") or resp.get("data") or []
        elif isinstance(resp, list):
            msgs = resp
        for m in msgs:
            blob = json.dumps(m)
            # try body/html/text fields first
            body_text = " ".join(str(m.get(f, "")) for f in ("body", "html", "text", "text_body", "html_body", "snippet", "subject", "intro"))
            codes = re.findall(r"\b(\d{6})\b", body_text) or re.findall(r"\b(\d{6})\b", blob)
            if codes:
                return codes[0]
        time.sleep(5)
    return None

def gen_password():
    up = random.choice(string.ascii_uppercase)
    lo = "".join(random.choices(string.ascii_lowercase, k=7))
    dg = "".join(random.choices(string.digits, k=3))
    sp = random.choice("!@#$%^&*")
    pw = up + lo + dg + sp
    lst = list(pw); random.shuffle(lst)
    return "".join(lst)

async def set_react_input(page, selector, value):
    await page.evaluate("""([sel, val]) => {
        const el = document.querySelector(sel);
        if (!el) throw new Error("no input " + sel);
        const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
        const setter = Object.getOwnPropertyDescriptor(proto, "value").set;
        setter.call(el, val);
        el.dispatchEvent(new Event("input", {bubbles: true}));
        el.dispatchEvent(new Event("change", {bubbles: true}));
    }""", [selector, value])

def stub_with_token(tok):
    return STUB_JS.replace("__TOKEN_PLACEHOLDER__", json.dumps(tok))

async def run_one(idx):
    from camoufox.async_api import AsyncCamoufox
    print(f"\n=== account {idx} ===")
    email, sk = voidash_inbox()
    pw = gen_password()
    print(f"[*] {email}")

    cid, tok = await asyncio.to_thread(twocaptcha_solve)

    results: dict = {"signup": None, "verify": None}
    async with AsyncCamoufox(headless=True, humanize=False) as browser:
        ctx = await browser.new_context()
        page = await ctx.new_page()

        async def handle_route(route):
            await route.fulfill(status=200, content_type="application/javascript", body=stub_with_token(tok))
        await page.route("**/challenges.cloudflare.com/turnstile/**", handle_route)
        await page.add_init_script(stub_with_token(tok))

        async def on_response(resp):
            u = resp.url
            if "/auth/password/sign-up" in u:
                try:
                    body = await resp.json()
                except Exception:
                    try:
                        body = (await resp.text())[:300]
                    except Exception:
                        body = "<no body>"
                results["signup"] = (resp.status, body)
                print("  [*] sign-up resp:", resp.status, json.dumps(body)[:300] if isinstance(body, (dict, list)) else str(body)[:300])
            elif "/auth/password/verify" in u and "resend" not in u:
                try:
                    body = await resp.json()
                except Exception:
                    try:
                        body = (await resp.text())[:300]
                    except Exception:
                        body = "<no body>"
                results["verify"] = (resp.status, body)
                print("  [*] verify resp:", resp.status, json.dumps(body)[:300] if isinstance(body, (dict, list)) else str(body)[:300])
        page.on("response", on_response)

        await page.goto(SIGNUP_URL, wait_until="domcontentloaded", timeout=90000)
        await page.wait_for_selector('input[name="email"]', timeout=45000)
        await asyncio.sleep(2)

        await set_react_input(page, 'input[name="email"]', email)
        await set_react_input(page, 'input[name="password"]', pw)
        try:
            await set_react_input(page, 'input[name="referral_code"]', REFERRAL)
        except Exception:
            print("  [!] no referral input (maybe prefilled)")

        btn = page.locator("button.auth-primary-action")
        for _ in range(50):
            if await btn.count() and await btn.first.is_enabled():
                break
            await asyncio.sleep(0.5)
        enabled = await btn.first.is_enabled() if await btn.count() else False
        print("  [*] submit enabled:", enabled)
        if DEBUG:
            try:
                await page.screenshot(path=os.path.join(HERE, f"cf_signup_{idx}.png"))
            except Exception:
                pass
        if not enabled:
            print("  [!] form stuck; stub:", await page.evaluate("!!(window.turnstile && window.turnstile.__stub)"))
            await ctx.close()
            return False

        await btn.first.click()
        for _ in range(60):
            if results["signup"]:
                break
            await asyncio.sleep(0.5)

        st, body = results["signup"] if results["signup"] else (0, None)
        ok = st in (200, 201)
        if not ok:
            print("  [!] signup failed, status:", st)
            if DEBUG:
                try:
                    await page.screenshot(path=os.path.join(HERE, f"cf_fail_{idx}.png"))
                except Exception:
                    pass
            await ctx.close()
            return False

        print("  [*] signup OK, waiting verification step...")
        try:
            await page.wait_for_selector('[data-auth-step="verification"] input[name="code"]', timeout=30000)
        except Exception:
            print("  [!] verification form not found; url:", page.url)
            await ctx.close()
            return False

        code = await asyncio.to_thread(voidash_wait_code, sk)
        print("  [*] email code:", code)
        if not code:
            await ctx.close()
            return False

        await set_react_input(page, '[data-auth-step="verification"] input[name="code"]', code)
        # form may auto-submit when code is complete; wait first, click only if needed
        for _ in range(16):
            if results["verify"]:
                break
            await asyncio.sleep(0.5)
        if not results["verify"]:
            try:
                vbtn = page.locator('[data-auth-step="verification"] button[type="submit"]').first
                if await vbtn.is_enabled():
                    await vbtn.click(timeout=10000)
            except Exception as e:
                print("  [!] verify click err:", repr(e)[:150])
        for _ in range(40):
            if results["verify"]:
                break
            await asyncio.sleep(0.5)

        vst, vbody = results["verify"] if results["verify"] else (0, None)
        vok = vst in (200, 201)
        print("  [*] verify ok:", vok, "url:", page.url)

        api_key = None
        if vok:
            await asyncio.sleep(2)
            try:
                # workspace provisioning poll -> get org/proj ids from session
                sess = ""
                org_id = ""
                proj_id = ""
                for attempt in range(30):  # up to ~150s
                    try:
                        await page.goto(BASE + "/console", wait_until="domcontentloaded", timeout=45000)
                    except Exception:
                        pass
                    sess = await page.evaluate("""async () => {
                        const r = await fetch("/api/console/v1/session", {credentials:"include"});
                        return await r.text();
                    }""")
                    if "workspace_setup_pending" in sess:
                        if attempt % 5 == 0:
                            print(f"  [*] workspace pending ({attempt+1}/30)...")
                        await asyncio.sleep(5)
                        continue
                    m_org = re.search(r'org_[A-Za-z0-9_\-]+', sess)
                    m_proj = re.search(r'proj_[A-Za-z0-9_\-]+', sess)
                    org_id = m_org.group(0) if m_org else ""
                    proj_id = m_proj.group(0) if m_proj else ""
                    if org_id:
                        break
                    await asyncio.sleep(5)
                print("  [*] org:", org_id, "proj:", proj_id)
                if not proj_id and org_id:
                    pt = await page.evaluate("""async (o) => {
                        const r = await fetch("/api/console/v1/organizations/" + o + "/projects", {credentials:"include"});
                        return await r.text();
                    }""", org_id)
                    pm = re.search(r'proj_[A-Za-z0-9_\-]+', pt)
                    proj_id = pm.group(0) if pm else ""
                if proj_id:
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
                            api_key = j.get("secret_key") or (j.get("api_key") or {}).get("secret_key")
                        except Exception:
                            m = re.search(r'"secret_key":"([^"]+)"', created["body"])
                            api_key = m.group(1) if m else None
                    if api_key:
                        print("  [+] API KEY:", api_key[:12] + "..." + api_key[-4:])
                    # also capture balance/rewards state
                    rw = await page.evaluate("""async () => {
                        const r = await fetch("/api/console/v1/rewards", {credentials:"include"});
                        return await r.text();
                    }""")
                    print("  [*] rewards:", rw[:300])
            except Exception as e:
                print("  [!] key extract err:", repr(e)[:250])
            if DEBUG:
                try:
                    await page.screenshot(path=os.path.join(HERE, f"cf_console_{idx}.png"))
                except Exception:
                    pass
        await ctx.close()

    if ok:
        rec = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "email": email, "password": pw,
               "verified": bool(vok), "api_key": api_key, "referral": REFERRAL,
               "solver": "2captcha+camoufox", "voidash_sk": sk}
        with open(ACC_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print("  [+] SAVED", email, "verified:", vok, "key:", bool(api_key))
        return True
    return False

async def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    oks = 0
    for i in range(1, n + 1):
        try:
            if await run_one(i):
                oks += 1
        except Exception as e:
            print("  [!] err:", repr(e)[:400])
    print(f"\nDONE: ok={oks} total={n}")

asyncio.run(main())
