#!/usr/bin/env python3
# push v2: init repo via Contents API, then blobs/tree/commit via Git Data API
import base64, json, os, sys, time, urllib.request, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = "abliteration-farm"

def get_token():
    toks = json.load(open(os.path.expanduser("~/tmp/pw_alive.json"), encoding="utf-8"))
    want = sys.argv[1] if len(sys.argv) > 1 else None
    for tk, login in toks:
        if not want or login == want:
            return tk, login
    raise SystemExit("no token")

def api(method, path, token, body=None, tries=3):
    data = json.dumps(body).encode() if body is not None else None
    last = None
    for i in range(tries):
        req = urllib.request.Request("https://api.github.com" + path, data=data, method=method,
                                     headers={"Authorization": "Bearer " + token,
                                              "User-Agent": "farm", "Accept": "application/vnd.github+json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                t = r.read().decode()
                return r.status, (json.loads(t) if t else None)
        except urllib.error.HTTPError as e:
            last = (e.code, e.read().decode()[:300])
            if e.code == 409 and i < tries - 1:
                time.sleep(5); continue
            return last
    return last

FILES = ["README.md", ".gitignore", "menu.py", "autoreg6.py", "gateway.py", "check_balances.py", "push_github.py", "harvest_keys.py"]

def main():
    tk, login = get_token()
    print("account:", login)
    # init or update README via Contents API
    raw = open(os.path.join(HERE, "README.md"), "rb").read()
    st, ex = api("GET", f"/repos/{login}/{REPO}/contents/README.md", tk)
    payload = {"message": "init", "content": base64.b64encode(raw).decode()}
    if st == 200 and isinstance(ex, dict) and ex.get("sha"):
        payload["sha"] = ex["sha"]
    st, r = api("PUT", f"/repos/{login}/{REPO}/contents/README.md", tk, payload)
    print("init README:", st)
    if st not in (200, 201):
        raise SystemExit(str(r))

    # get current HEAD commit sha for base
    st, br = api("GET", f"/repos/{login}/{REPO}/branches/main", tk)
    base_sha = br["commit"]["sha"] if st == 200 else None
    print("base:", base_sha)

    tree_items = []
    for fn in FILES:
        p = os.path.join(HERE, fn)
        raw = open(p, "rb").read()
        st, b = api("POST", f"/repos/{login}/{REPO}/git/blobs", tk,
                    {"content": base64.b64encode(raw).decode(), "encoding": "base64"})
        if st not in (200, 201):
            print("blob FAIL", fn, st, b); continue
        print("blob", fn, st, len(raw))
        tree_items.append({"path": fn, "mode": "100644", "type": "blob", "sha": b["sha"]})

    tb = {"tree": tree_items}
    if base_sha:
        st, bc = api("GET", f"/repos/{login}/{REPO}/git/commits/{base_sha}", tk)
        if st == 200:
            tb["base_tree"] = bc["tree"]["sha"]
    st, t = api("POST", f"/repos/{login}/{REPO}/git/trees", tk, tb)
    print("tree:", st)
    if st not in (200, 201):
        raise SystemExit(str(t))

    st, c = api("POST", f"/repos/{login}/{REPO}/git/commits", tk,
                {"message": "abliteration-farm: autoreg (camoufox+2captcha+native submit) + OpenAI gateway + menu",
                 "tree": t["sha"], "parents": [base_sha] if base_sha else []})
    print("commit:", st)
    if st not in (200, 201):
        raise SystemExit(str(c))

    st, ref = api("PATCH", f"/repos/{login}/{REPO}/git/refs/heads/main", tk, {"sha": c["sha"], "force": True})
    print("ref update:", st)
    print(f"\nDONE: https://github.com/{login}/{REPO}")

main()
