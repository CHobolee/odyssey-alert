import os, re, time
from curl_cffi import requests
U = "https://cgv.co.kr/api/v1/booking/searchSiteScnscYmdListByMov"
P = {"coCd": "A420", "siteNo": "0013", "movNo": "30001323"}
REF = {"Referer": "https://cgv.co.kr/cnm/movieBook/cinema"}
out = []
try: out.append("runner_ip " + requests.get("https://api.ipify.org", timeout=10).text)
except Exception as e: out.append(f"ip err {e}")
def kind(r):
    b = r.text
    return "JSON" if b.lstrip().startswith("{") else ("CGV차단" if "비정상적으로" in b else b[:60].replace("\n", " "))
def one(t, warm, extra=None):
    try:
        s = requests.Session(impersonate=t)
        w = ""
        if warm:
            w = f"home={s.get('https://cgv.co.kr/', timeout=20).status_code} "
        h = dict(REF); h.update(extra or {})
        r = s.get(U, params=P, headers=h, timeout=20)
        r2 = s.get(U, params=P, headers=h, timeout=20)   # 같은 세션으로 한 번 더
        return f"{t:16s} warm={warm!s:5s} extra={bool(extra)!s:5s} {w}-> {r.status_code} {kind(r)} / again {r2.status_code}"
    except Exception as e:
        return f"{t:16s} warm={warm} ERR {type(e).__name__}: {str(e)[:80]}"
X = {"Origin": "https://cgv.co.kr", "Accept": "application/json, text/plain, */*", "Accept-Language": "ko-KR,ko;q=0.9", "Sec-Fetch-Site": "same-origin", "Sec-Fetch-Mode": "cors", "Sec-Fetch-Dest": "empty"}
for rnd in range(3):
    out.append(f"--- round {rnd+1}")
    for t in ["safari", "safari18_0", "safari17_0", "chrome", "chrome136", "firefox135"]:
        for warm in (False, True):
            out.append(one(t, warm)); time.sleep(1.5)
    out.append(one("safari", False, X)); out.append(one("chrome", False, X))
    time.sleep(20)
fn = f"diag_{os.environ.get('GITHUB_RUN_ID','local')}.txt"
open(fn, "w", encoding="utf-8").write("\n".join(out) + "\n"); print("\n".join(out))
