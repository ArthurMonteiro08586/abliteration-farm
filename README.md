# abliteration-farm

Full farm for [abliteration.ai](https://abliteration.ai) — uncensored GLM-5.3 API.
Autoreg (FREE captcha) + $1/$0.50 credit farming + OpenAI-compatible gateway + web dashboard.

```
┌─────────────┐   ┌──────────────┐   ┌─────────────┐   ┌──────────────┐
│ autoreg.py  │ → │ accounts.jsonl│ → │ gateway.py  │ → │ OpenAI client│
│ camoufox +  │   │ email/pass/key│   │ rotation +  │   │ base_url=    │
│ FREE captcha│   │ /balance      │   │ failover    │   │ :8300/v1     │
└─────────────┘   └──────────────┘   └─────────────┘   └──────────────┘
      ↑ captcha token                     ↑ dashboard http://127.0.0.1:8300/
┌─────────────────────┐
│ captcha-solver      │  FREE local sidecar (:8877)
│ (CloakBrowser)      │  11 captcha types, no paid API needed
└─────────────────────┘
```

## Quick start

```bash
# 1. install (Python 3.11)
pip install camoufox[geoip]
python -m camoufox fetch

# 2. free captcha sidecar (optional but recommended — zero cost per account)
git clone https://github.com/waguriagentic/captcha-solver cs_sidecar
cd cs_sidecar && PORT=8877 BROWSER_HEADLESS=1 python server.py &

# 3. register 5 accounts (free captcha first, paid services as fallback)
python autoreg.py 5

# 4. start gateway + dashboard
GATEWAY_API_KEY=*** python gateway.py
# -> http://127.0.0.1:8300/  (live pool status + chat test in browser)

# or just: python menu.py
```

## Menu

```
python menu.py
 1) Register accounts        (free sidecar captcha first)
 2) Register via PROXY       (proxy pool rotation)
 3) Harvest keys             (older accounts missing a key)
 4) Claim social $0.50       (X+LinkedIn, eligible accounts)
 5) Show accounts / keys
 6) Start gateway            (:8300, dashboard at /)
 7) Test gateway             (health + chat)
 8) Captcha backends status
 9) Check proxy pool
```

CLI: `python menu.py reg 5 [--proxy]` · `gw` · `test` · `list`

## Captcha backends (solvers.py)

Chain order: `CAPTCHA_BACKENDS` env or `--backends=a,b` flag.

| Backend | Cost | Notes |
|---|---|---|
| `sidecar-realpage` | **FREE** | local [waguriagentic/captcha-solver](https://github.com/waguriagentic/captcha-solver) (:8877), CloakBrowser drives the REAL page → token accepted by abliteration (verified: sign-up 200). ~17s/solve |
| `sidecar` | **FREE** | same sidecar, route-intercept mode — **rejected** by abliteration (`request_unverified`), keep last in chain |
| `2captcha` | ~$2-3/1000 | `method=turnstile` + `action=password_signup`. `TWOCAPTCHA_KEY` |
| `yescaptcha` | ~$1-2/1000 | `AntiTurnstileTaskProxyLess`. `YESCAPTCHA_KEY` |
| `capmonster` | ~$1-2/1000 | `TurnstileTaskProxyless`. `CAPMONSTER_KEY` |
| `anticaptcha` | ~$2/1000 | `TurnstileTaskProxyless`. `ANTICAPTCHA_KEY` |

Sidecar also solves: reCAPTCHA v2/v3, hCaptcha, Cloudflare clearance, AWS WAF, DataDome, PerimeterX, Akamai, Aliyun, Arkose FunCaptcha — reusable for other farms.

Keys go in `.env` (see `.env.example`).

## Money: how much does an account get

Verified via `/api/console/v1/rewards` + `billing/summary`:

| Reward | Amount | How |
|---|---|---|
| Signup credit | **$1.00** | auto after email verify, BUT gated by async anti-fraud review (`review_required` → `eligible:true` after ~30-60min, not everyone passes) |
| Social bundle | **$0.50** | `POST /api/console/v1/rewards/social/x` + `/linkedin` — **just two POSTs, no real social accounts** (claim once review passes; `social_claim.py` does it for all accounts) |
| Referrals | $0.50 each | referred user's first PAID request; max 3 |

Max promo per account = **$3** (`maximum_promotional_usd_micros: 3000000`).
Real proof: account got `balance.available_usd_micros: 1499630` ($1.50) after signup+social claim, chat completion 200 OK.

Accounts stuck in `review_required` = $0 (billing `state: blocked`, API returns `insufficient_credits`). Gateway auto-skips them and retries every 30 min (review may pass later).

## Gateway

`gateway.py` — stdlib only. Upstream `https://api.abliteration.ai/v1`.

| Endpoint | What |
|---|---|
| `GET /` | **web dashboard** — live pool stats, key table, chat tester |
| `POST /v1/chat/completions` | OpenAI chat (+`stream:true` passthrough) |
| `POST /v1/responses` | OpenAI Responses API |
| `POST /v1/messages` | Anthropic-style messages |
| `POST /v1/messages/count_tokens` | token counting |
| `POST /v1/completions` `/v1/embeddings` | legacy |
| `GET /v1/models` | models (`abliterated-model`, `-large`, `-large-v2`=GLM-5.3) |
| `GET /v1/credits` `/v1/organization/balance` | billing passthrough |
| `GET /health` `/admin/keys` `/admin/reload` | pool control |

Key pool logic:
- loads from `accounts.jsonl` (`api_key` field, `sk-`/`ak_` prefixes) + `keys.txt`
- **hot-reload every 60s** — new registrations appear without restart
- random pick among `ok` keys, failover up to 8 tries
- `insufficient_credits` → status `nobalance`, retry in 30 min
- `401/403` → `dead`, retry in 10 min
- `GATEWAY_API_KEY` protects everything except `/health` and dashboard

```python
from openai import OpenAI
client = OpenAI(base_url="http://127.0.0.1:8300/v1", api_key="***")
r = client.chat.completions.create(model="abliterated-model",
    messages=[{"role": "user", "content": "Hello"}])
```

## Proxies (optional)

`python proxy_pool.py check` — tests `proxies.txt` (one `http://ip:port` or `scheme://user:pass@host:port` per line), saves working to `proxies_good.txt`.
`python autoreg.py 5 --proxy` — random proxy per account (camoufox + sidecar both honor it).
No proxy file = direct connection (works too).

## How autoreg bypasses everything (technical)

| Wall | Bypass |
|---|---|
| Cloudflare Turnstile (`action=password_signup`) | token from sidecar **real-page** mode or paid solver; stub `window.turnstile` (token BAKED INTO stub body) fires `opts.callback(token)` → React state → submit unlocks |
| WAF 403 on manual `fetch` sign-up | NEVER fetch manually — let the React form submit itself (native WorkOS correlation headers + Radar signalsId attach automatically) |
| Chromium fingerprints blocked | **Camoufox** (Firefox anti-detect) |
| Email code | Voidash temp inbox — address comes FROM the API response (it ignores requested addresses); poll `/api/v1/messages` for 6-digit code |
| Verify button hangs | form auto-submits on 6 digits — wait first, click as fallback |
| `workspace_setup_pending` | org/project provisioning is async — poll `/api/console/v1/session` up to 150s |
| Key create `422 Idempotency-Key` | `POST /api/console/v1/projects/{proj}/api-keys` + UUID header → 201 `{secret_key:"ak_..."}` |
| Social $0.50 "follow us" | no real follow check — two POSTs to `/rewards/social/{x,linkedin}` mark both complete |

Full chain per account (~3-5 min, $0 with sidecar):

```
sidecar real-page solve -> Voidash inbox -> camoufox: stub turnstile + fill form
-> React native submit -> 200 challenge:email_verification -> poll code -> verify 200
-> poll workspace -> create key (Idempotency-Key) -> ak_... -> accounts.jsonl
-> (if eligible) claim social $0.50 -> gateway hot-reloads key
```

## Files

```
autoreg.py         # WORKING autoreg (multi-captcha + proxy + key + social claim)
gateway.py         # OpenAI gateway + dashboard (:8300)
menu.py            # CLI menu
solvers.py         # 6 captcha backends with fallback chain
proxy_pool.py      # proxy load/check/rotate
harvest_keys.py    # create keys for older verified accounts
social_claim.py    # claim $0.50 social bundle on eligible accounts
check_balances.py  # captcha-service balance checker
tools/             # recon probes (balance, key-create, social endpoints)
docs/openapi.json  # full platform API spec (41 endpoints)
accounts.jsonl     # output (gitignored): email/password/key/balance
```

## Notes

- Site: Next.js + WorkOS auth + Cloudflare Turnstile + Radar. Console API = `/api/console/v1/*`
- Console login = same email/password (click submit INSIDE the password form — page has OAuth buttons)
- Models: `abliterated-model` $1/1M in, $3/1M out (256K ctx, vision) · `-large-v2` = GLM-5.3 $3/$5 (1M ctx)
- Windows: run with `PYTHONPATH=""` if another venv leaks into env
- Referral in autoreg: `REFERRAL` constant (yours: put your own code, you get $0.50 per referred paid user)
