"""진짜 브라우저(Playwright Chromium)로 CGV에 들어가 오디세이 용산 일정 전체를 조회해 snapshot_<run>.txt 로 저장."""
import asyncio, json, os, sys
SITE, MOV = "0013", "30001323"
async def main():
    from playwright.async_api import async_playwright
    out = []
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        ctx = await b.new_context(locale="ko-KR", timezone_id="Asia/Seoul",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")
        await ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        page = await ctx.new_page()
        r = await page.goto("https://cgv.co.kr/cnm/movieBook/cinema", wait_until="domcontentloaded", timeout=45000)
        out.append(f"page {r.status if r else '?'}")
        js = "async (u)=>{const r=await fetch(u); const t=await r.text(); return [r.status, t]}"
        async def get(u, tries=4):
            for i in range(tries):
                st, t = await page.evaluate(js, u)
                if st == 200 and t.strip().startswith("{"):
                    return json.loads(t).get("data") or []
                await page.wait_for_timeout(12000)
            return None
        dates = await get(f"/api/v1/booking/searchSiteScnscYmdListByMov?coCd=A420&siteNo={SITE}&movNo={MOV}")
        if dates is None:
            out.append("DATES BLOCKED"); print("\n".join(out)); return out
        ds = [d["scnYmd"] for d in dates]
        out.append("dates " + ",".join(ds))
        for y in ds:
            await page.wait_for_timeout(12000)
            rows = await get(f"/api/v1/booking/searchMovScnInfo?coCd=A420&siteNo={SITE}&scnYmd={y}&rtctlScopCd=01", tries=3)
            if rows is None:
                out.append(f"{y} BLOCKED"); continue
            o = [r for r in rows if "오디세이" in (r.get("prodNm") or "")]
            out.append(f"{y} " + " · ".join(f"{r['scnsrtTm'][:2]}:{r['scnsrtTm'][2:]} {r.get('expoScnsNm','').split(' ')[0]} {r.get('frSeatCnt')}/{r.get('stcnt')}" for r in o))
        await b.close()
    return out
out = asyncio.run(main())
fn = f"snapshot_{os.environ.get('GITHUB_RUN_ID','local')}.txt"
open(fn, "w", encoding="utf-8").write("\n".join(out) + "\n"); print("\n".join(out))
