import json, sys, time, re
from curl_cffi import requests
U = "https://cgv.co.kr/api/v1/booking/searchSiteScnscYmdListByMov"
P = {"coCd": "A420", "siteNo": "0013", "movNo": "30001323"}
out = []
try:
    out.append("runner_ip " + requests.get("https://api.ipify.org", timeout=10).text)
except Exception as e:
    out.append(f"ip err {e}")
import curl_cffi; out.append("curl_cffi " + curl_cffi.__version__)
targets = ["chrome", "chrome124", "chrome131", "chrome136", "safari", "safari18_0", "firefox", "firefox135", "edge101", "chrome131_android", "safari18_0_ios"]
for t in targets:
    for ref in (True, False):
        try:
            s = requests.Session(impersonate=t)
            h = {"Referer": "https://cgv.co.kr/cnm/movieBook/cinema"} if ref else {}
            r = s.get(U, params=P, headers=h, timeout=20)
            body = r.text
            m = re.search(r"CLIENT_IP</dt>\s*<dd>([^<]+)", body)
            kind = "JSON" if body.lstrip().startswith("{") else ("CGV차단페이지" if "비정상적으로" in body else ("CF-challenge" if "challenge" in body.lower() or "just a moment" in body.lower() else body[:80].replace("\n", " ")))
            out.append(f"{t:20s} ref={ref!s:5s} -> {r.status_code} {kind} cf-ray={r.headers.get('cf-ray','')} mitig={r.headers.get('cf-mitigated','')} server={r.headers.get('server','')} ip={m.group(1) if m else ''}")
        except Exception as e:
            out.append(f"{t:20s} ref={ref} -> ERR {type(e).__name__}: {str(e)[:100]}")
        time.sleep(2)
# 홈페이지 먼저 방문해 쿠키를 받은 뒤 API 호출
try:
    s = requests.Session(impersonate="chrome")
    r0 = s.get("https://cgv.co.kr/", timeout=20)
    r1 = s.get(U, params=P, headers={"Referer": "https://cgv.co.kr/cnm/movieBook/cinema"}, timeout=20)
    out.append(f"warmup home={r0.status_code} cookies={list(s.cookies.keys())} api={r1.status_code}")
except Exception as e:
    out.append(f"warmup ERR {e}")
open("diag.txt", "w", encoding="utf-8").write("\n".join(out) + "\n")
print("\n".join(out))
