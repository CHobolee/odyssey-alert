# 오디세이 용아맥 예매 오픈 알리미

CGV 용산아이파크몰 IMAX관(용아맥)에 《오디세이》 회차가 새 날짜로 열리면 ntfy로 폰에 푸시 알림을 보냅니다.

- GitHub Actions가 5분마다 실행되고, 한 번 돌 때마다 60초 간격으로 4번 확인합니다.
- 첫 실행 때 이미 열려 있던 날짜는 기준선으로만 저장합니다(`state.json`).
- 알림 채널은 저장소 Secrets의 `NTFY_TOPIC`에 넣습니다.
- 알림 테스트: Actions → odyssey-alert → Run workflow → "알림 테스트만 보내기" 체크

API 구조 참고: [YCYEOM/movie-alert](https://github.com/YCYEOM/movie-alert), [0w0i0n0g0/cgv-open-push](https://github.com/0w0i0n0g0/cgv-open-push)
