#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
autoreg7.py — abliteration.ai mass registration (full pipeline).

Pipeline per account:
  1. Voidash temp inbox (address taken from API response!)
  2. Turnstile token via solvers.py chain: FREE local sidecar -> 2captcha -> yescaptcha -> capmonster -> anticaptcha
  3. Camoufox (Firefox anti-detect; Chromium gets WAF 403) + optional proxy
  4. window.turnstile stub with token BAKED INTO stub body -> React form self-submits
     (native WorkOS correlation headers + Radar signalsId; manual fetch = 403 request_unverified)
  5. 6-digit email code from Voidash -> verify form auto-submits
  6. Poll session until workspace ready -> POST projects/{proj}/api-keys + Idempotency-Key -> ak_ key
  7. Claim social bundle ($0.50 X+LinkedIn, one POST each, no real accounts needed) if eligible

Usage:
  python autoreg7.py 5                  # register 5 accounts
  python autoreg7.py 5 --proxy          # via proxy pool (proxies.txt / proxies_good.txt)
  python autoreg7.py 5 --backends sidecar,2captcha   # captcha chain override
Env:
  CAPTCHA_BACKENDS, SIDECAR_URL, TWOCAPTCHA_KEY, YESCAPTCHA_KEY, CAPMONSTER_KEY, ANTICAPTCHA_KEY, PROXY_FILE
"""
import asyncio, json, os, re, sys, time, random, string, urllib.request, urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from solvers import solve_turnstile, SolverError
from proxy_pool import ProxyPool, to_camoufox

BASE = "https://abliteration.ai"
SIGNUP_URL = BASE + "/sign-up?referral_code=ref_yrd8gnW-d4ir"
REFERRAL = "ref_yrd8gnW-d4ir"
SITEKEY = "0x4AAAAAAEcO2qYYBE_ztENL"
TS_ACTION = "password_signup"
HERE = os.path.dirname(os.path.abspath(__file__))
ACC_FILE = os.path.join(HERE, "accounts.jsonl")
DEBUG = os.environ.get("DEBUG", "0") == "1"

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
        d.className = "cf-stub"; d.textContent = "verifying...";
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

def stub_with_token(tok):
    return STUB_JS.replace("__TOKEN_PLACEHOLDER__", json.dumps(tok))

# ---------------------------------------------------------------- helpers
# Voidash free domains — rotate to avoid one domain getting flagged by anti-fraud.
# voidash.com is premium/paid (plan_required) — skip. cyou/bond tier2, eu.cc tier3.
VOIDASH_DOMAINS = ["voidash.cyou", "govno.eu.cc", "musor.eu.cc", "pomoi.eu.cc", "voidash.bond"]
_dom_i = 0

def _next_domain():
    global _dom_i
    d = VOIDASH_DOMAINS[_dom_i % len(VOIDASH_DOMAINS)]
    _dom_i += 1
    return d

def voidash_inbox(domain=None, tries=None):
    """Create temp inbox. domain=None -> rotate across all free domains (with fallback)."""
    tries = tries or (len(VOIDASH_DOMAINS) if domain is None else 1)
    last_err = None
    for _ in range(tries):
        dom = domain or _next_domain()
        body = json.dumps({"domain": dom}).encode()
        req = urllib.request.Request("https://api.voidash.com/api/v1/inboxes", data=body,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                resp = json.loads(r.read().decode())
        except Exception as e:
            last_err = e; continue
        data = resp.get("data", resp)
        sk = data.get("session_key") or data.get("sessionKey")
        email = data.get("address") or data.get("email")
        if sk and email:
            return email, sk
        last_err = RuntimeError("voidash bad resp: " + json.dumps(resp)[:150])
    raise RuntimeError(f"voidash all domains failed: {last_err}")

def voidash_wait_code(sk, timeout=240):
    t0 = time.time()
    while time.time() - t0 < timeout:
        for path in ("/api/v1/messages", "/api/v1/inboxes/messages"):
            req = urllib.request.Request("https://api.voidash.com" + path,
                                         headers={"Authorization": "Bea" + "rer " + sk})
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    resp = json.loads(r.read().decode())
                break
            except Exception:
                resp = None
        if resp is None:
            time.sleep(5); continue
        msgs = []
        if isinstance(resp, dict):
            msgs = resp.get("messages") or resp.get("data") or []
        elif isinstance(resp, list):
            msgs = resp
        for m in msgs:
            blob = json.dumps(m)
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
    lst = list(up + lo + dg + sp); random.shuffle(lst)
    return "".join(lst)

async def set_react_input(page, selector, value):
    await page.evaluate("""([sel, val]) => {
        const el = document.querySelector(sel);
        if (!el) throw new Error("no input " + sel);
        const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
        setter.call(el, val);
        el.dispatchEvent(new Event("input", {bubbles: true}));
        el.dispatchEvent(new Event("change", {bubbles: true}));
    }""", [selector, value])

# ---------------------------------------------------------------- main flow
async def run_one(idx, use_proxy=False, backends=None, pool=None):
    from camoufox.async_api import AsyncCamoufox
    print(f"\n=== account {idx} ===")

    proxy_url = None
    if use_proxy:
        proxy_url = pool.next() if pool is not None else None
        if not proxy_url:
            raise RuntimeError("NO_PROXY: proxy pool empty/burned — home IP is blocked, refusing direct")
        print(f"[*] proxy: {proxy_url}")

    email, sk = voidash_inbox()
    pw = gen_password()
    print(f"[*] {email}")

    # 1. captcha (chain: free sidecar first)
    tok, backend = await asyncio.to_thread(
        solve_turnstile, SITEKEY, SIGNUP_URL, TS_ACTION, proxy_url, backends)
    print(f"  [+] token via {backend} ({len(tok)} chars)")

    results = {"signup": None, "verify": None}
    browser_kwargs = {"headless": True, "humanize": False}
    if proxy_url:
        browser_kwargs["proxy"] = to_camoufox(proxy_url)
        # NOTE: geoip=True crashes (camoufox hits ipecho.net THROUGH the proxy -> InvalidIP).
        # Leave geoip off; NL/datacenter IP still passes the site (verified: sidecar solved OK).

    ok = False
    vok = False
    api_key = None
    claimed_social = False
    rewards_snapshot = None
    async with AsyncCamoufox(**browser_kwargs) as browser:
        ctx = await browser.new_context()
        page = await ctx.new_page()

        async def handle_route(route):
            await route.fulfill(status=200, content_type="application/javascript",
                                body=stub_with_token(tok))
        await page.route("**/challenges.cloudflare.com/turnstile/**", handle_route)
        await page.add_init_script(stub_with_token(tok))

        async def on_response(resp):
            u = resp.url
            if "/auth/password/sign-up" in u:
                try:
                    body = await resp.json()
                except Exception:
                    body = (await resp.text())[:300]
                results["signup"] = (resp.status, body)
                print("  [*] sign-up:", resp.status, json.dumps(body)[:200] if isinstance(body, (dict, list)) else str(body)[:200])
            elif "/auth/password/verify" in u and "resend" not in u:
                try:
                    body = await resp.json()
                except Exception:
                    body = (await resp.text())[:300]
                results["verify"] = (resp.status, body)
                print("  [*] verify:", resp.status, json.dumps(body)[:200] if isinstance(body, (dict, list)) else str(body)[:200])
        page.on("response", on_response)

        await page.goto(SIGNUP_URL, wait_until="domcontentloaded", timeout=90000)
        await page.wait_for_selector('input[name="email"]', timeout=45000)
        await asyncio.sleep(1.5)
        await set_react_input(page, 'input[name="email"]', email)
        await set_react_input(page, 'input[name="password"]', pw)
        try:
            await set_react_input(page, 'input[name="referral_code"]', REFERRAL)
        except Exception:
            pass

        btn = page.locator("button.auth-primary-action")
        for _ in range(50):
            if await btn.count() and await btn.first.is_enabled():
                break
            await asyncio.sleep(0.5)
        if not (await btn.count() and await btn.first.is_enabled()):
            print("  [!] submit stays disabled — token rejected by widget stub?")
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
            print("  [!] signup failed:", st)
            await ctx.close()
            return False

        # verification code
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
        for _ in range(16):
            if results["verify"]:
                break
            await asyncio.sleep(0.5)
        if not results["verify"]:
            try:
                vbtn = page.locator('[data-auth-step="verification"] button[type="submit"]').first
                if await vbtn.is_enabled():
                    await vbtn.click(timeout=10000)
            except Exception:
                pass
        for _ in range(40):
            if results["verify"]:
                break
            await asyncio.sleep(0.5)
        vst, _ = results["verify"] if results["verify"] else (0, None)
        vok = vst in (200, 201)
        print("  [*] verified:", vok)
        if not vok:
            await ctx.close()
            return False

        # workspace ready -> create key
        await asyncio.sleep(2)
        proj_id = ""
        sess = ""
        for attempt in range(48):
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
                    print(f"  [*] workspace pending ({attempt+1}/48)...")
                await asyncio.sleep(5)
                continue
            m = re.search(r'proj_[A-Za-z0-9_\-]+', sess)
            if m:
                proj_id = m.group(0)
                break
            await asyncio.sleep(5)
        if not proj_id:
            m2 = re.search(r'org_[A-Za-z0-9_\-]+', sess)
            if m2:
                pt = await page.evaluate("""async (o) => {
                    const r = await fetch("/api/console/v1/organizations/" + o + "/projects", {credentials:"include"});
                    return await r.text();
                }""", m2.group(0))
                pm = re.search(r'proj_[A-Za-z0-9_\-]+', pt)
                proj_id = pm.group(0) if pm else ""
        print("  [*] proj:", proj_id)

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
            print("  [*] create key ->", created["status"])
            if created["status"] in (200, 201):
                try:
                    j = json.loads(created["body"])
                    api_key = j.get("secret_key") or (j.get("api_key") or {}).get("secret_key")
                except Exception:
                    m = re.search(r'"secret_key":"([^"]+)"', created["body"])
                    api_key = m.group(1) if m else None
            if api_key:
                print("  [+] API KEY:", api_key[:14] + "..." + api_key[-4:])

            # rewards snapshot + social claim (free $0.50 if eligible)
            rw = await page.evaluate("""async () => {
                const r = await fetch("/api/console/v1/rewards", {credentials:"include"});
                return await r.text();
            }""")
            try:
                rwj = json.loads(rw)
                rewards_snapshot = {"eligible": rwj.get("eligible"),
                                    "signup_micros": rwj.get("signup_credit_usd_micros"),
                                    "social": (rwj.get("social_bundle") or {}).get("status")}
                print("  [*] rewards:", rewards_snapshot)
                if rwj.get("eligible") and (rwj.get("social_bundle") or {}).get("status") != "claimed":
                    for plat in ["x", "linkedin"]:
                        r2 = await page.evaluate("""async (p) => {
                            const r = await fetch("/api/console/v1/rewards/social/" + p, {
                                method: "POST", credentials: "include",
                                headers: {"Content-Type":"application/json"}});
                            return r.status;
                        }""", plat)
                        print(f"  [social {plat}] ->", r2)
                        if r2 == 200:
                            claimed_social = True
            except Exception:
                pass
        await ctx.close()

    rec = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "email": email, "password": pw,
           "verified": True, "api_key": api_key, "referral": REFERRAL,
           "captcha_backend": backend, "proxy": proxy_url,
           "social_claimed": claimed_social, "rewards": rewards_snapshot,
           "voidash_sk": sk}
    with open(ACC_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"  [+] SAVED {email} | key:{bool(api_key)} backend:{backend} social:{claimed_social}")
    return True

async def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    opts = [a for a in sys.argv[1:] if a.startswith("--")]
    n = int(args[0]) if args else 1
    use_proxy = "--proxy" in opts
    backends = None
    for o in opts:
        if o.startswith("--backends="):
            backends = o.split("=", 1)[1].split(",")
    pool = ProxyPool() if use_proxy else None
    if use_proxy:
        print(f"[*] proxy pool: {len(pool) if pool else 0} proxies")
    oks = 0
    for i in range(1, n + 1):
        for attempt in range(3):
            try:
                if await run_one(i, use_proxy=use_proxy, backends=backends, pool=pool):
                    oks += 1
                break
            except SolverError as e:
                print("  [!] captcha fail:", str(e)[:200])
                break
            except RuntimeError as e:
                if "NO_PROXY" in str(e):
                    print("  [!] no working proxies left — refresh proxies_verified.txt"); break
                print(f"  [!] err (attempt {attempt+1}):", repr(e)[:200]); await asyncio.sleep(3)
            except Exception as e:
                msg = repr(e)
                # only burn the proxy on genuine network failures, not app-level denials
                net_err = any(k in msg for k in ("NET_TIMEOUT", "ProxyError", "Tunnel connection",
                            "ERR_CONNECTION", "ERR_TUNNEL", "InvalidIP", "NS_ERROR_NET"))
                print(f"  [!] err (attempt {attempt+1}):", msg[:200], "(proxy burned)" if net_err else "")
                if use_proxy and pool is not None and net_err:
                    # mark the CURRENT proxy bad by re-picking deterministically is unreliable;
                    # instead force a refresh so next attempt gets a fresh tested proxy
                    pool._live_fetch()
                await asyncio.sleep(3)
    print(f"\nDONE: ok={oks} total={n}")

if __name__ == "__main__":
    asyncio.run(main())
