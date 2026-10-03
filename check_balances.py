import os, json, urllib.request

env = {}
p = os.path.join(os.path.expanduser("~"), "Desktop", "_PROJECTS", "\u0430\u0432\u0442\u043e\u0440\u0435\u0433 \u043f\u0440\u043e\u0435\u043a\u0442", ".env")
for line in open(p, encoding='utf-8'):
    line = line.strip()
    if '=' in line and not line.startswith('#'):
        k, v = line.split('=', 1)
        env[k.strip()] = v.strip()

def get(url):
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            return r.status, r.read().decode('utf-8', 'replace')[:300]
    except Exception as e:
        return 0, str(e)[:300]

svc = {
    'TWOCAPTCHA_KEY': lambda kk: "https://2captcha.com/res.php?key=" + kk + "&action=getbalance&json=1",
    'ANTICAPTCHA_KEY': lambda kk: "https://api.anti-captcha.com/getBalance?clientKey=" + kk,
    'RUCAPTCHA_KEY': lambda kk: "https://api.rucaptcha.com/res.php?key=" + kk + "&action=getbalance&json=1",
    'YESCAPTCHA_KEY': lambda kk: "https://api.yescaptcha.com/getBalance?clientKey=" + kk,
}
for name, fn in svc.items():
    k = env.get(name, '')
    if not k:
        print(name, "EMPTY")
        continue
    st, body = get(fn(k))
    print(name, "HTTP", st, "->", body)
