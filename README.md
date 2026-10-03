# abliteration-farm

Autoreg + OpenAI-compatible gateway for [abliteration.ai](https://abliteration.ai) — uncensored GLM-5.3 API.

**Two parts:**
- `autoreg6.py` — mass account registration (Cloudflare Turnstile via 2captcha, temp email via Voidash)
- `gateway.py` — local OpenAI-compatible proxy with key-pool rotation + auto-failover

---

## How it works (autoreg)

abliteration.ai signup is a Next.js + WorkOS flow. The hard parts and how they're solved:

| Problem | Solution |
|---|---|
| Cloudflare Turnstile on signup (`action=password_signup`) | Solved by **2captcha** (`method=turnstile` + `action` param). YesCaptcha gives invalid tokens → `403 request_unverified` |
| `POST /auth/password/sign-up` from plain fetch → **403 Cloudflare HTML challenge** | Never fetch manually. Let the **React form submit itself** so WorkOS correlation headers + Radar `signalsId` are attached natively |
| Turnstile widget blocks submit (`disabled: !token`) | `window.turnstile` is **stubbed** before the real api.js loads (route-fulfill + init script). Stub receives `render(el, opts)` and calls `opts.callback(TOKEN)` → React state fills → button enables |
| Stub ran with empty token | The token must be **baked into the stub source** (`__TOKEN_PLACEHOLDER__` substitution), not set via a separate init script — api.js executes in a context where the earlier init script didn't apply |
| Patchright/Chromium → still 403 | Use **Camoufox** (Firefox anti-detect). Chromium fingerprints get WAF-blocked on POST |
| Email code never arrives | **Voidash generates its own address** — it ignores any `address`/`local_part` you pass. Must read `address` from the API response, never invent the email |
| Verification button click times out | The code form **auto-submits** on 6 digits. Wait for the response first, click only as fallback |
| `workspace_setup_pending` right after verify | Org/project provisioning is async. **Poll `/api/console/v1/session`** up to ~150s |
| Create API key → `422 param: header.Idempotency-Key` | `POST /api/console/v1/projects/{proj}/api-keys` requires an **`Idempotency-Key`** header (any UUID) |

Full chain per account (~3-4 min):

```
Voidash inbox -> 2captcha Turnstile (action=password_signup)
 -> camoufox: stub turnstile, fill email/password/referral via native setter
 -> React native submit -> POST /auth/password/sign-up -> 200 {challenge: email_verification}
 -> poll Voidash /api/v1/messages for 6-digit code
 -> fill code (auto-submit) -> POST /auth/password/verify -> 200 {authenticated}
 -> poll /api/console/v1/session until workspace ready -> org_id + proj_id
 -> POST /api/console/v1/projects/{proj}/api-keys {name:"autoreg"} + Idempotency-Key
 -> 201 {secret_key: "ak_..."} -> accounts.jsonl
```

## Credits / balance — THE $1 STORY

**$1 signup credit EXISTS but is gated by manual review.** Proof from `/api/console/v1/rewards`:

Most fresh accounts (4 of 5 tested):
```json
{"eligible": false, "status": "review_required", "signup_credit_usd_micros": 0, ...}
```

But one account (registered ~14:16, checked ~15:00):
```json
{"eligible": true, "status": "available", "signup_credit_usd_micros": 1000000, ...}
```
= **$1.00 granted** (1000000 micros). Chat completion with its key returned **200 OK**, while keys of non-eligible accounts get `insufficient_credits`. So: the credit lands **asynchronously after anti-fraud review** (voidash.bond emails likely trigger it; some pass, some stay in review).

Reward program (from console JS):
- **Email verified** → $1 signup credit (auto-claimed when eligible; `review_required` = "Promotional-credit eligibility needs a support review")
- **Social bundle** → $0.50 for following X + LinkedIn (`k.activate("x"|"linkedin")` mutations, needs real social auth)
- **Referrals** → $0.50 each after referred user's first **paid** API request; `maximum_rewards: 0` on fresh accounts
- Eligibility: "once per verified identity" — farm detection exists
- The `$1` on the pricing page = minimum custom prepaid top-up, separate thing

Balance check: `billing/summary` → `balance.available_usd_micros`.

## Setup

Python **3.11** (3.14 breaks camoufox deps):

```bash
pip install camoufox[geoip] playwright
python -m camoufox fetch          # downloads the browser once
```

Credentials:

| What | Where |
|---|---|
| `TWOCAPTCHA_KEY` | `.env` (default path: `~/Desktop/_PROJECTS/авторег проект/.env`, or edit `load_env()`) |
| Voidash | no key needed — public API, domain `voidash.bond` |
| Referral code | `REFERRAL` constant in `autoreg6.py` |

> On Windows run with `PYTHONPATH=""` if another venv (e.g. Hermes) leaks into the env.

## Usage — menu

```bash
python menu.py          # interactive menu
python menu.py reg 5    # register 5 accounts
python menu.py list     # show accounts + keys
python menu.py gw       # start gateway on :8300
python menu.py test     # health + chat test
```

Menu items: **1)** register N accounts · **2)** show accounts/keys · **3)** start gateway · **4)** test gateway · **5)** captcha-service balance check

## Usage — direct

```bash
# register 10 accounts (appends to accounts.jsonl)
python autoreg6.py 10

# start gateway (reads keys from accounts.jsonl / keys.txt)
GATEWAY_API_KEY=*** python gateway.py

# use it as an OpenAI endpoint
curl http://127.0.0.1:8300/v1/chat/completions \
  -H "Authorization: Bearer ***" \
  -H "Content-Type: application/json" \
  -d '{"model":"abliterated-model","messages":[{"role":"user","content":"Hello"}]}'
```

OpenAI SDK:

```python
from openai import OpenAI
client = OpenAI(base_url="http://127.0.0.1:8300/v1", api_key="***")
r = client.chat.completions.create(
    model="abliterated-model",
    messages=[{"role": "user", "content": "Hello"}],
)
print(r.choices[0].message.content)
```

## Gateway

`gateway.py` — stdlib only, no deps.

- Upstream: `https://api.abliteration.ai/v1`
- Endpoints: `/v1/chat/completions`, `/v1/completions`, `/v1/embeddings`, `/v1/models`, `/health`, `/admin/keys`
- Key pool from `accounts.jsonl` (`api_key` field) or `keys.txt` (one key per line)
- Rotation: random pick among alive keys; **failover** up to 4 tries
- Auto-kill: `401/403` → dead instantly; 4 other fails → dead; **revive after 600s**
- `/admin/keys` (GET stats, POST `{"key":"ak_..."}` add) — protected by `GATEWAY_API_KEY`
- Streaming: passthrough for `stream: true`

Models (from `/console/playground` API): `abliterated-model` (256K ctx, text+vision), `abliterated-model-large`, `abliterated-model-large-v2` (GLM-5.3, 1M ctx).

Pricing: `abliterated-model` $1.00/1M input, $3.00/1M output · `-large-v2` $3.00/$5.00.

## Files

```
autoreg6.py       # WORKING autoreg (camoufox + 2captcha + native React submit)
gateway.py        # OpenAI-compatible gateway with key rotation
menu.py           # CLI menu launcher
check_balances.py # captcha service balance checker
accounts.jsonl    # output: email/password/verified/api_key/referral
key_pool.json     # gateway pool state (masked keys + statuses)
probe_*.py        # recon scripts used to reverse the flow
autoreg1-5.py     # earlier iterations (kept for reference, do not use)
```

## Notes

- Cost per account: ~$2-3 (2captcha Turnstile). Balance check: `python check_balances.py`
- `voidash.bond` is the only working Voidash domain for this site (`*.eu.cc` blocked)
- Accounts stay usable; keys have `permissions: ["model.invoke"]`, no expiry
- Console login = the same email/password (sign-in form has a `password` field; the OAuth buttons on that page are Google/GitHub/Microsoft — click the submit **inside the password form**)
