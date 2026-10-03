# abliteration-farm

Full farm software for [abliteration.ai](https://abliteration.ai) — uncensored GLM-5.3 API.

**One command does everything**: register accounts → solve captcha for FREE → verify email → create API keys → claim reward quests ($1 + $0.50) → feed keys into an OpenAI-compatible gateway with web dashboard.

```
                    ┌──────────── farm.py run 5 ────────────┐
                    │                                       │
  ┌─────────┐   ┌───▼─────┐   ┌───────────┐   ┌──────────┐  │  ┌──────────┐
  │ captcha │   │autoreg  │   │harvest_   │   │quest_    │  └─▶│ gateway  │──▶ OpenAI SDK
  │ sidecar │──▶│.py      │──▶│keys.py    │──▶│runner.py │     │ :8300    │    any client
  │ (FREE)  │   │camoufox │   │ak_ keys   │   │$1 + $0.5 │     │dashboard │
  └─────────┘   └─────────┘   └───────────┘   └──────────┘     └──────────┘
       11 captcha types        accounts.jsonl (single source of truth)
```

## Quick start

```bash
# Python 3.11
pip install camoufox[geoip]
python -m camoufox fetch

# FREE captcha solver (local sidecar, no paid API)
git clone https://github.com/waguriagentic/captcha-solver cs_sidecar
cd cs_sidecar && PORT=8877 BROWSER_HEADLESS=1 python server.py &
cd ..

# FULL PIPELINE: 5 accounts -> keys -> quests -> report
python farm.py run 5

# gateway with dashboard
python farm.py gateway     # -> http://127.0.0.1:8300/
```

## farm.py — orchestrator

| Command | What |
|---|---|
| `farm.py run 5` | register 5 → harvest keys → quests → export → status |
| `farm.py run 5 --proxy` | same via ProxyGrab proxies (rotating, tested vs site) |
| `farm.py status` | farm report: accounts/keys/eligible/balances, ready keys list |
| `farm.py reg 5` | register only |
| `farm.py keys` | harvest missing keys |
| `farm.py quests` | claim rewards + record balances |
| `farm.py quests --loop 600` | re-check every 10min (catches async review approvals) |
| `farm.py gateway` | export keys + start gateway :8300 |
| `farm.py export` | write keys.txt (balance-holders first) |

`menu.py` = same things as an interactive menu (9 items).

## Reward quests (free money per account)

Verified from live API (`/api/console/v1/rewards`):

| Quest | Amount | How it works |
|---|---|---|
| Email verified | **$1.00** | auto after signup, gated by async anti-fraud review (`review_required` → `eligible:true` in ~30-60min, not every account passes) |
| Social bundle | **$0.50** | `POST /rewards/social/x` + `/rewards/social/linkedin` — **two POSTs, no real social accounts needed** |
| Referrals | $0.50 × 3 | referred user's first paid request |
| **Max** | **$3.00** | `maximum_promotional_usd_micros: 3000000` |

`quest_runner.py` does all of it: logs into every account, claims social when eligible, records balance, and `--loop`/cron mode keeps re-checking accounts stuck in review until they pass. Proof: one account reached **$1.50 balance**, chat completion 200 OK.

## Captcha — FREE by default

`solvers.py` fallback chain (`CAPTCHA_BACKENDS` env / `--backends` flag):

| Backend | Cost | Notes |
|---|---|---|
| `sidecar-realpage` | **FREE** | local [waguriagentic/captcha-solver](https://github.com/waguriagentic/captcha-solver) (:8877), CloakBrowser on the REAL page — token accepted (sign-up 200), ~17s |
| `2captcha` | ~$2.99/1000 | fallback, `TWOCAPTCHA_KEY` |
| `yescaptcha` | paid | `YESCAPTCHA_KEY` |
| `capmonster` | paid | `CAPMONSTER_KEY` |
| `anticaptcha` | paid | `ANTICAPTCHA_KEY` |
| `sidecar` | FREE | route-intercept mode — rejected by this site (`request_unverified`), kept last |

Sidecar also solves reCAPTCHA v2/v3, hCaptcha, Cloudflare clearance, AWS WAF, DataDome, PerimeterX, Akamai, Aliyun, Arkose — 11 types total.

## Proxies (optional)

Two sources, merged automatically:
- **ProxyGrab API** (`proxygrab.py`, config `.proxygrab.json`): 400k pool, returns proxies **pre-tested against abliteration.ai** (`GET /proxies?proto=http&n=10&test=abliteration.ai`), auto-refresh every 5min
- files: `proxies.txt` / `proxies_good.txt` (`proxy_pool.py check` tests them)

`farm.py run 5 --proxy` rotates a fresh proxy per account. Note: free proxies are slow — direct connection works fine too (100% success rate observed).

## Gateway (:8300)

stdlib-only OpenAI-compatible proxy over the key pool:

- `GET /` — **web dashboard**: live pool (ok/nobalance/dead/wins), chat tester, endpoint list
- `POST /v1/chat/completions` (+stream), `/v1/responses`, `/v1/messages`, `/v1/messages/count_tokens`, `/v1/completions`, `/v1/embeddings`
- `GET /v1/models`, `/v1/credits`, `/v1/organization/balance` (+projects/costs/usage)
- `GET /health`, `/admin/keys`, `/admin/reload` (master-key protected)

Pool logic: hot-reload keys every 60s · exhaustive failover (tries every alive key, winners first) · `insufficient_credits` → `nobalance`, auto-retry in 30min (review may pass) · 401/403 → `dead`, retry 10min.

```python
from openai import OpenAI
client = OpenAI(base_url="http://127.0.0.1:8300/v1", api_key="***")
r = client.chat.completions.create(model="abliterated-model",
    messages=[{"role": "user", "content": "Hello"}])
```

Models: `abliterated-model` $1/$3 per 1M (256K ctx, vision) · `abliterated-model-large-v2` = **GLM-5.3** $3/$5 (1M ctx).

`demo_key.txt` — a live key with ~$1.5 balance to test immediately.

## How the bypass works

| Wall | Solution |
|---|---|
| Turnstile (`action=password_signup`) | token via free sidecar real-page / paid solver → `window.turnstile` **stub with token baked into its body** → `opts.callback(token)` → React state → button unlocks |
| WAF 403 on manual fetch | never fetch sign-up manually — the **React form submits itself** (native WorkOS correlation + Radar signalsId) |
| Chromium fingerprint ban | **Camoufox** (Firefox anti-detect) |
| Email code | Voidash API — address comes FROM the response (requested addresses are ignored); 6-digit code from `/api/v1/messages` |
| verify click hangs | form auto-submits on 6 digits |
| `workspace_setup_pending` | poll `/api/console/v1/session` up to 4min |
| key create 422 | `POST /projects/{proj}/api-keys` + **`Idempotency-Key`** header → `{secret_key:"ak_..."}` |
| social quest | two POSTs, no OAuth — server just marks steps complete |

## Files

```
farm.py           # ORCHESTRATOR — one command full pipeline
autoreg.py        # registration (multi-captcha + proxy + key + auto social claim)
quest_runner.py   # reward quests: claim $0.50, track $1 review, balances, --loop
harvest_keys.py   # create keys for older verified accounts
gateway.py        # OpenAI gateway + dashboard (:8300)
solvers.py        # 6 captcha backends, fallback chain
proxygrab.py      # ProxyGrab API client (proxies pre-tested vs target site)
proxy_pool.py     # proxy pool: live API + files, rotation, health
social_claim.py   # standalone social bundle claimer
menu.py           # interactive menu
check_balances.py # captcha service balances
tools/            # recon probes (rewards/key/balance endpoints)
docs/openapi.json # full platform API (41 endpoints)
accounts.jsonl    # THE database (gitignored): email/pass/key/rewards/balance
keys.txt          # gateway pool file (gitignored), balance-first order
```

## Notes

- Windows: run with `PYTHONPATH=""` (other venvs leak)
- Cost per account: $0 with sidecar, ~$0.003 with 2captcha fallback
- Console login: same email/password; click submit **inside the password form** (page has OAuth buttons that hijack broad selectors)
- Referral: `REFERRAL` constant in autoreg.py — set your own code to earn $0.50/referral
- Site stack: Next.js + WorkOS + Cloudflare Turnstile/Radar; console API `/api/console/v1/*`
