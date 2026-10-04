import os, time, json, asyncio
from curl_cffi import requests
Q = "coCd=A420&siteNo=0013&movNo=30001323"
PATH = "/api/v1/booking/searchSiteScnscYmdListByMov?" + Q
REF = {"Referer": "https://cgv.co.kr/cnm/movieBook/cinema"}
out = []
def kind(code, b):
    return f"{code} " + ("JSON" if b.lstrip().startswith("{") else ("CGV차단" if "비정상적으로" in b else b[:50].replace("\n", " ")))
try: out.append("runner_ip " + requests.get("https://api.ipify.org", timeout=10).text)
except Exception as e: out.append(f"ip err {e}")

# (A) 다른 호스트/경로
out.append("--- A. 다른 주소")
for u in ["https://cgv.co.kr" + PATH, "https://www.cgv.co.kr" + PATH, "https://m.cgv.co.kr" + PATH,
          "https://api.cgv.co.kr/cnm/atkt/searchSiteScnscYmdListByMov?" + Q,
          "https://api.cgv.co.kr/cnm/booking/searchSiteScnscYmdListByMov?" + Q,
          "https://api.cgv.co.kr/api/v1/booking/searchSiteScnscYmdListByMov?" + Q,
          "https://api.cgv.co.kr/com/bznsCom/screnMng/checkScrenUrlValid?coCd=A420&pcUrl=%2Fcnm%2FmovieBook%2Fcinema&expoChnlCd=01"]:
    for t in ("chrome", "safari"):
        try:
            r = requests.Session(impersonate=t).get(u, headers={**REF, "Origin": "https://cgv.co.kr"}, timeout=20)
            out.append(f"{t:7s} {u.split('?')[0][8:70]:62s} -> {kind(r.status_code, r.text)}")
        except Exception as e:
            out.append(f"{t:7s} {u[8:60]} ERR {str(e)[:60]}")
        time.sleep(1)

# (B) curl_cffi 새 연결, 8초 간격 24회 → 통과율
out.append("--- B. curl_cffi 새 연결 통과율 (8초 간격)")
seq = ""
for i in range(24):
    t = ("chrome", "safari")[i % 2]
    try:
        r = requests.Session(impersonate=t).get("https://cgv.co.kr" + PATH, headers=REF, timeout=20)
        seq += "O" if r.status_code == 200 else "x"
    except Exception:
        seq += "E"
    time.sleep(8)
out.append(f"chrome/safari 번갈아: {seq}  통과 {seq.count('O')}/24")

# (C) 진짜 브라우저 (Playwright Chromium)
out.append("--- C. Playwright 실제 Chromium")
async def pw():
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        for label, kw in [("headless", {"headless": True}), ("headless+chrome채널", {"headless": True, "channel": "chrome"})]:
            try:
                b = await p.chromium.launch(args=["--disable-blink-features=AutomationControlled"], **kw)
                ctx = await b.new_context(locale="ko-KR", timezone_id="Asia/Seoul",
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")
                await ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
                page = await ctx.new_page()
                resp = await page.goto("https://cgv.co.kr/cnm/movieBook/cinema", wait_until="domcontentloaded", timeout=45000)
                title = await page.title()
                out.append(f"{label}: 페이지 {resp.status if resp else '?'} title={title[:30]!r}")
                seq = ""
                for i in range(12):
                    try:
                        st = await page.evaluate("async (u)=>{const r=await fetch(u); const t=await r.text(); return r.status+(t.trim().startsWith('{')?'J':'B')}", PATH)
                        seq += "O" if st == "200J" else "x"
                    except Exception as e:
                        seq += "E"
                    await page.wait_for_timeout(8000)
                out.append(f"{label}: 페이지 안에서 API 12회 → {seq}  통과 {seq.count('O')}/12")
                await b.close()
            except Exception as e:
                out.append(f"{label}: ERR {type(e).__name__} {str(e)[:150]}")
try: asyncio.run(pw())
except Exception as e: out.append(f"playwright ERR {e}")
fn = f"diag_{os.environ.get('GITHUB_RUN_ID','local')}.txt"
open(fn, "w", encoding="utf-8").write("\n".join(out) + "\n"); print("\n".join(out))
