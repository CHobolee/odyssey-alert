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
    # CGV(Cloudflare)는 TLS/브라우저 지문으로 봇을 막음 → 브라우저 지문 흉내 (pip install curl_cffi)
    from curl_cffi import requests as _cffi
except ImportError:
    _cffi = None

# 2026-10-04 GitHub 러너 진단 결과:
#  - CGV(Cloudflare) 차단은 "연결(세션)마다" 확률적으로 결정됨 (chrome/safari 지문은 약 40~60% 통과)
#  - 한 번 통과한 연결은 계속 통과, 막힌 연결은 계속 막힘 → 막히면 새 연결로 다시 시도
#  - chrome136, firefox 지문은 항상 막힘. 홈페이지를 먼저 여는 것은 도움 안 됨
PROFILES = ["chrome", "safari", "safari18_0", "safari17_0"]
MAX_TRIES = 2
MIN_GAP = 12          # CGV는 같은 IP의 연달은 요청을 막음(속도 제한) → 모든 요청 사이 최소 간격(초)
_last_req = [0.0]


def _throttle():
    wait = _last_req[0] + MIN_GAP - time.time()
    if wait > 0:
        time.sleep(wait)
    _last_req[0] = time.time()
_prof = {"i": 0, "session": None, "name": None}


class HTTPBlocked(Exception):
    def __init__(self, code):
        super().__init__(f"HTTP {code}")
        self.code = code


def get_json(path, params):
    url = f"{BASE}/{path}"
    if _cffi is not None:
        last, tried = 0, []
        for _ in range(MAX_TRIES):
            if _prof["session"] is None:
                _prof["name"] = PROFILES[_prof["i"] % len(PROFILES)]
                _prof["i"] += 1
                _prof["session"] = _cffi.Session(impersonate=_prof["name"])
            _throttle()
            try:
                r = _prof["session"].get(url, params=params, headers={"Referer": HEADERS["Referer"]}, timeout=20)
                last = r.status_code
                if r.status_code == 200:
                    if tried:
                        log(f"새 연결({_prof['name']})로 통과 — 앞서 막힌 연결: {', '.join(tried)}")
                    return r.json()
            except Exception as e:
                last = 0
                log(f"요청 오류({_prof['name']}): {str(e)[:80]}")
            tried.append(f"{_prof['name']}={last}")
            _prof["session"] = None      # 막힌 연결은 버림
            if last == 429:
                raise HTTPBlocked(429)
        log(f"연결 {MAX_TRIES}개 모두 막힘: {', '.join(tried)}")
        raise HTTPBlocked(last or 403)
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    req = urllib.request.Request(f"{url}?{qs}", headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise HTTPBlocked(e.code)


def probe_runner(n=5, need=2):
    """이 서버(IP)가 CGV에 통과되는지 측정. 요청은 MIN_GAP 간격으로."""
    if _cffi is None:
        return True
    url = f"{BASE}/searchSiteScnscYmdListByMov"
    seq = ""
    for i in range(n):
        _throttle()
        try:
            r = _cffi.Session(impersonate=PROFILES[i % 2]).get(
                url, params={"coCd": "A420", "siteNo": SITE_NO, "movNo": MOV_NO or "30001323"},
                headers={"Referer": HEADERS["Referer"]}, timeout=15)
            seq += "O" if r.status_code == 200 else "x"
        except Exception:
            seq += "E"
        if seq.count("O") >= need:
            break
    ok = seq.count("O") >= need
    log(f"서버 품질 측정: {seq} → {'좋은 서버, 감시 시작' if ok else '나쁜 서버, 교대'}")
    return ok


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
        log(f"취소표 확인 OK: {label(ymd)} {t[:2]}:{t[2:]} 잔여 {free}")
        _seat_base[key] = free
        if prev is not None and free > prev:
            notify(f"🎟 취소표! {label(ymd)} {t[:2]}:{t[2:]} 용아맥 (잔여 {free})",
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


def _already_sent(title):
    """다른 서버가 같은 알림을 이미 보냈는지 ntfy 기록(최근 6시간)에서 확인."""
    topic = os.environ.get("NTFY_TOPIC")
    if not topic:
        return False
    try:
        import random
        time.sleep(random.uniform(0, 4))      # 동시에 발견했을 때 겹치지 않게
        with urllib.request.urlopen(f"https://ntfy.sh/{topic}/json?poll=1&since=6h", timeout=10) as r:
            for line in r.read().decode("utf-8").splitlines():
                try:
                    if json.loads(line).get("title") == title:
                        return True
                except Exception:
                    pass
    except Exception:
        pass
    return False


def notify(title, text, url="https://cgv.co.kr/cnm/movieBook/cinema", dedupe=True):
    if dedupe and _already_sent(title):
        log(f"다른 서버가 이미 보낸 알림이라 생략: {title}")
        return
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


_tick = [0]


def check_once():
    state = load_state()
    first_run = "baseline_done" not in state
    today = datetime.now(KST).strftime("%Y%m%d")
    _tick[0] += 1
    # 회차·좌석 조회(searchMovScnInfo)는 GitHub에서 날짜 목록 조회 직후엔 거의 항상 막힘.
    # 그래서 3번에 한 번은 취소표 확인을 "먼저" 해서 통과 기회를 줌.
    cancel_first = bool(CANCEL_WATCH) and _tick[0] % 3 == 0
    if cancel_first:
        try:
            cancel_watch_tick()
        except HTTPBlocked:
            log("취소표 확인 막힘 (먼저 시도)")
    dates = sorted(d for d in open_dates() if d >= today)
    if TARGET_DATES:
        dates = [d for d in dates if d in TARGET_DATES]
    for ymd in dates:
        if ymd in state["notified"] or time.time() < _recheck_after.get(ymd, 0):
            continue
        try:
            shows = endgame_showings(ymd)
        except HTTPBlocked:
            shows = None          # 회차 조회가 막힘 → 날짜가 열린 사실만이라도 바로 알림
        if shows is not None and not shows:
            _recheck_after[ymd] = time.time() + RECHECK_SEC
            continue
        if first_run:
            log(f"{label(ymd)}: 이미 열려 있음 → 기준선 저장")
        elif shows is None:
            notify(f"🚨 {MOVIE_LABEL} {label(ymd)} 예매 오픈!",
                   f"{SITE_NAME}에 오디세이 {label(ymd)} 일정이 새로 열렸어요.\n"
                   "(회차·좌석 정보는 조회가 막혀 확인 못 함 — 지금 바로 예매 화면을 확인하세요)\n"
                   "명당: H·I열 중앙(약 14~31번)")
        else:
            lines = [f'{s["time"]} {s["hall"]} (잔여 {s["seats"]})' for s in shows]
            notify(f"🚨 {MOVIE_LABEL} {label(ymd)} 예매 오픈!",
                   f"{SITE_NAME}\n" + "\n".join(lines) + "\n명당: H·I열 중앙(약 14~31번)")
        state["notified"][ymd] = datetime.now(KST).isoformat(timespec="seconds")
        save_state(state)
    if CANCEL_WATCH and not cancel_first:
        try:
            cancel_watch_tick()
        except HTTPBlocked:
            log("취소표 확인 막힘")
    if first_run:
        state["baseline_done"] = datetime.now(KST).isoformat(timespec="seconds")
        save_state(state)
        log("기준선 저장 완료. 이제부터 새로 열리는 날짜만 알립니다.")
    else:
        log(f"확인 완료 (오디세이 상영일 {len(dates)}일)")
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--loop", type=int, metavar="SEC")
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--minutes", type=int, default=0, help="--loop를 이 시간(분) 뒤 종료")
    a = ap.parse_args()

    if a.test:
        notify("✅ 알림 테스트", f"{SITE_NAME} 오디세이 용아맥 감시 알림이 정상 작동합니다.", dedupe=False)
        return
    if a.loop:
        # GitHub 서버(IP)마다, 시간마다 CGV 통과율이 크게 달라짐 → 여러 서버(SLOT)가 동시에
        # 엇갈린 시각에 확인. 이 서버가 10분 동안 한 번도 통과 못 하면 새 서버로 교대.
        slot = int(os.environ.get("SLOT") or 1)
        slots = int(os.environ.get("SLOTS") or 1)
        successes = blocked = 0
        last_ok = time.time()
        end = time.time() + a.minutes * 60 if a.minutes else None
        while end is None or time.time() < end:
            # 매 분의 (slot-1)*60/slots 초에 맞춰 확인 → 서버들이 분 안에서 고르게 퍼짐
            now = time.time()
            target = (now // 60) * 60 + (slot - 1) * 60 / slots
            if target <= now + 1:
                target += 60
            time.sleep(target - now)
            try:
                if check_once():
                    return
                successes += 1
                last_ok = time.time()
            except HTTPBlocked as e:
                blocked += 1
                log(f"이번 회차 막힘 (HTTP {e.code}) — 성공 {successes} / 막힘 {blocked}")
                if time.time() - last_ok > 10 * 60:
                    log("10분 동안 통과 0회 → 새 서버로 교대")
                    sys.exit(3 if successes == 0 else 0)
            except Exception as e:
                log(f"오류: {e}")
    else:
        try:
            check_once()
        except HTTPBlocked as e:
            log(f"HTTP {e.code}")
            sys.exit(1)


if __name__ == "__main__":
    main()
