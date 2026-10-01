#!/usr/bin/env python3
"""
CGV 용산아이파크몰 IMAX(용아맥) · 오디세이 예매 오픈 알리미
- 용아맥에 오디세이 회차가 새 날짜에 처음 열리면 폰으로 푸시 알림
- 첫 실행 때 이미 열려 있는 날짜는 기준선으로만 저장 (알림 X)
- 표준 라이브러리만 사용 (pip 설치 불필요)
- API 구조 참고: github.com/YCYEOM/movie-alert, github.com/0w0i0n0g0/cgv-open-push

사용:
  python3 endgame_alert.py --once     # 1회 확인 (GitHub Actions / cron 용)
  python3 endgame_alert.py --loop 60  # 60초마다 계속 확인 (내 컴퓨터에서 켜두기)
  python3 endgame_alert.py --test     # 알림이 폰에 오는지 테스트

알림 채널 (환경변수, 하나 이상):
  NTFY_TOPIC        ntfy 앱에서 구독할 토픽 이름 (가장 간단, 계정 불필요)
  TELEGRAM_TOKEN + TELEGRAM_CHAT_ID
  DISCORD_WEBHOOK_URL
"""
import argparse, json, os, sys, time, urllib.request, urllib.error
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))

SITE_NO = "0013"            # CGV 용산아이파크몰
SITE_NAME = "CGV 용산아이파크몰"
MOV_NO = "30001323"         # 오디세이 (CGV 영화 코드)
MOV_KEYWORD = "오디세이"
MOVIE_LABEL = "오디세이 용아맥"
# 특정 날짜만 보려면 {"20261010": "10/10(토)"} 처럼. None이면 새로 열리는 모든 날짜.
TARGET_DATES = None
# 관 필터 (IMAX관만). 비워두면 모든 관.
HALL_FILTER = ["IMAX"]

BASE = "https://cgv.co.kr/api/v1/booking"
HEADERS = {
    # CGV(Cloudflare)는 전체 Chrome UA + Referer 가 없으면 403
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
    "Referer": "https://cgv.co.kr/cnm/movieBook/cinema",
    "Origin": "https://cgv.co.kr",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ko-KR,ko;q=0.9",
}
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")


def log(msg):
    print(f"[{datetime.now(KST):%Y-%m-%d %H:%M:%S} KST] {msg}", flush=True)


try:
    # CGV(Cloudflare)는 TLS 지문으로 봇을 막음 → 크롬 TLS 지문 흉내 (pip install curl_cffi)
    from curl_cffi import requests as _cffi
    _session = _cffi.Session(impersonate="chrome")
except ImportError:
    _session = None


class HTTPBlocked(Exception):
    def __init__(self, code):
        super().__init__(f"HTTP {code}")
        self.code = code


def get_json(path, params):
    url = f"{BASE}/{path}"
    if _session is not None:
        r = _session.get(url, params=params, headers={"Referer": HEADERS["Referer"]}, timeout=20)
        if r.status_code != 200:
            raise HTTPBlocked(r.status_code)
        return r.json()
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    req = urllib.request.Request(f"{url}?{qs}", headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise HTTPBlocked(e.code)


def open_dates():
    """용산에서 이 영화가 상영되는 날짜 목록 (요청 1건). 영화 코드가 없으면 극장 전체 날짜."""
    if MOV_NO:
        d = get_json("searchSiteScnscYmdListByMov", {"coCd": "A420", "siteNo": SITE_NO, "movNo": MOV_NO})
    else:
        d = get_json("searchSiteScnscYmdListBySite", {"coCd": "A420", "siteNo": SITE_NO})
    return {x["scnYmd"] for x in (d.get("data") or [])}


# 취소표 감시: 이 회차들의 잔여석이 늘면(=취소표) 알림. {"YYYYMMDD": ["HHMM", ...]}
CANCEL_WATCH = {
    "20261009": ["1800", "2130"],
    "20261010": ["1800", "2130"],
    "20261011": ["1800", "2130"],
}
_seat_base = {}      # (ymd, hhmm) -> 마지막으로 본 잔여석
_cancel_idx = [0]


def cancel_watch_tick():
    """1분에 날짜 1개씩 돌아가며 확인 (요청 1건)."""
    today = datetime.now(KST).strftime("%Y%m%d")
    dates = [d for d in sorted(CANCEL_WATCH) if d >= today]
    if not dates:
        return
    ymd = dates[_cancel_idx[0] % len(dates)]
    _cancel_idx[0] += 1
    time.sleep(1.5)
    d = get_json("searchMovScnInfo", {"coCd": "A420", "siteNo": SITE_NO, "scnYmd": ymd, "rtctlScopCd": "01"})
    for r in d.get("data") or []:
        t = r.get("scnsrtTm") or ""
        if t not in CANCEL_WATCH[ymd] or MOV_KEYWORD not in (r.get("prodNm") or ""):
            continue
        if HALL_FILTER and not any(k in (r.get("expoScnsNm") or "") for k in HALL_FILTER):
            continue
        try:
            free = int(r.get("frSeatCnt"))
        except (TypeError, ValueError):
            continue
        key = (ymd, t)
        prev = _seat_base.get(key)
        _seat_base[key] = free
        if prev is not None and free > prev:
            notify(f"🎟 취소표! {label(ymd)} {t[:2]}:{t[2:]} 용아맥",
                   f"잔여석 {prev} → {free} (+{free - prev})\n지금 예매 화면에서 H·I열 중앙(14~31번) 확인하세요!")


# IMAX 회차 없이 일반관만 잡힌 날짜는 매분 다시 조회하지 않고 10분마다만 재확인 (요청 수 절약)
_recheck_after = {}
RECHECK_SEC = 600


def endgame_showings(ymd):
    d = get_json("searchMovScnInfo",
                 {"coCd": "A420", "siteNo": SITE_NO, "scnYmd": ymd, "rtctlScopCd": "01"})
    out = []
    for r in d.get("data") or []:
        if not ((MOV_NO and r.get("movNo") == MOV_NO) or MOV_KEYWORD in (r.get("prodNm") or "")):
            continue
        hall = r.get("expoScnsNm") or r.get("scnsNm") or ""
        if HALL_FILTER and not any(k.lower() in (hall + r.get("prodNm", "")).lower() for k in HALL_FILTER):
            continue
        t = r.get("scnsrtTm") or ""
        out.append({
            "time": f"{t[:2]}:{t[2:]}" if len(t) == 4 else t,
            "hall": hall,
            "prod": r.get("prodNm", ""),
            "seats": f'{r.get("frSeatCnt", "?")}/{r.get("stcnt", "?")}',
        })
    return sorted(out, key=lambda x: x["time"])


# ---------------- 알림 ----------------
def _post(url, body, headers=None):
    req = urllib.request.Request(url, data=body, headers=headers or {}, method="POST")
    urllib.request.urlopen(req, timeout=15).read()


def notify(title, text, url="https://cgv.co.kr/cnm/movieBook/cinema"):
    sent = False
    topic = os.environ.get("NTFY_TOPIC")
    if topic:
        # 한글 제목은 헤더에 못 넣으므로 RFC 2047 인코딩
        import base64
        t = "=?UTF-8?B?" + base64.b64encode(title.encode()).decode() + "?="
        _post(f"https://ntfy.sh/{topic}", text.encode("utf-8"),
              {"Title": t, "Priority": "urgent", "Tags": "rotating_light,movie_camera", "Click": url})
        sent = True
    tok, chat = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if tok and chat:
        _post(f"https://api.telegram.org/bot{tok}/sendMessage",
              json.dumps({"chat_id": chat, "text": f"{title}\n\n{text}\n{url}"}).encode(),
              {"Content-Type": "application/json"})
        sent = True
    hook = os.environ.get("DISCORD_WEBHOOK_URL")
    if hook:
        _post(hook, json.dumps({"content": f"@everyone **{title}**\n{text}\n{url}"}).encode(),
              {"Content-Type": "application/json", "User-Agent": "odyssey-alert"})
        sent = True
    if not sent:
        log("⚠️ 알림 채널이 설정되지 않았습니다 (NTFY_TOPIC 등)")
    log(f"알림: {title} | {text}")


# ---------------- 상태 ----------------
def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"notified": {}}


def save_state(s):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=1)


def label(ymd):
    if TARGET_DATES and ymd in TARGET_DATES:
        return TARGET_DATES[ymd]
    d = datetime.strptime(ymd, "%Y%m%d")
    return f"{d.month}/{d.day}({'월화수목금토일'[d.weekday()]})"


def check_once():
    state = load_state()
    first_run = "baseline_done" not in state
    today = datetime.now(KST).strftime("%Y%m%d")
    dates = sorted(d for d in open_dates() if d >= today)
    if TARGET_DATES:
        dates = [d for d in dates if d in TARGET_DATES]
    for ymd in dates:
        if ymd in state["notified"] or time.time() < _recheck_after.get(ymd, 0):
            continue
        time.sleep(1.5)
        shows = endgame_showings(ymd)
        if not shows:
            _recheck_after[ymd] = time.time() + RECHECK_SEC
            continue
        if first_run:
            log(f"{label(ymd)}: 이미 열려 있음 → 기준선 저장 ({len(shows)}회차)")
        else:
            lines = [f'{s["time"]} {s["hall"]} (잔여 {s["seats"]})' for s in shows]
            notify(f"🚨 {MOVIE_LABEL} {label(ymd)} 예매 오픈!",
                   f"{SITE_NAME}\n" + "\n".join(lines) + "\n명당: H·I열 중앙(약 14~31번)")
        state["notified"][ymd] = datetime.now(KST).isoformat(timespec="seconds")
        save_state(state)
    if CANCEL_WATCH:
        cancel_watch_tick()
    if first_run:
        state["baseline_done"] = datetime.now(KST).isoformat(timespec="seconds")
        save_state(state)
        log("기준선 저장 완료. 이제부터 새로 열리는 날짜만 알립니다.")
    else:
        log(f"확인 완료 (상영일 {len(dates)}일, 새 오픈 없음이면 조용히 대기)")
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--loop", type=int, metavar="SEC")
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--minutes", type=int, default=0, help="--loop를 이 시간(분) 뒤 종료")
    a = ap.parse_args()

    if a.test:
        notify("✅ 알림 테스트", f"{SITE_NAME} 오디세이 용아맥 감시 알림이 정상 작동합니다.")
        return
    if a.loop:
        errors = 0
        successes = 0
        end = time.time() + a.minutes * 60 if a.minutes else None
        while end is None or time.time() < end:
            try:
                if check_once():
                    return
                errors = 0
                successes += 1
            except HTTPBlocked as e:
                errors += 1
                log(f"HTTP {e.code} (연속 {errors}회) — 403이면 IP 차단, 429면 요청 과다")
                if errors >= 5:
                    # 이 서버 IP가 막힌 것. 종료하면 워크플로가 다른 서버로 다음 실행을 켬.
                    log("이 서버가 CGV에 막힌 것 같아 종료 → 다른 서버로 교대")
                    if successes == 0 and int(os.environ.get("BLOCKED_STREAK") or 0) >= 3:
                        notify("⚠️ 오디세이 알리미 오류", "여러 서버에서 연속으로 CGV에 막혔어요. 확인이 필요해요.")
                    sys.exit(3 if successes == 0 else 0)
            except Exception as e:
                errors += 1
                log(f"오류: {e}")
            time.sleep(max(30, a.loop) if errors == 0 else 30)
    else:
        try:
            check_once()
        except HTTPBlocked as e:
            log(f"HTTP {e.code}")
            sys.exit(1)


if __name__ == "__main__":
    main()
