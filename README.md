# 📈 주식 뉴스 대시보드

매일 오전 8시에 국내외 주식 뉴스를 균형 수집·요약하고, 국내 장중에는 실제 지연 시세와 기간별 차트를 갱신하는 대시보드입니다.

- 코스피·코스닥 전체 상장종목을 종목명 또는 종목코드로 검색
- 관심종목 추가·개별 삭제
- 코스피·코스닥·코스피200과 미국·아시아 주요 지수 표시

---

## 🚀 GitHub 설정 (최초 1회)

### 1단계 — 저장소 만들기

1. GitHub에서 새 저장소 생성: `stock-news-dashboard`
2. **Public** 으로 설정 (GitHub Pages 무료 사용)
3. 이 폴더의 모든 파일을 업로드

```
stock-news-dashboard/
├── index.html
├── README.md
├── scripts/
│   └── fetch_news.py
├── requirements.txt
├── data/
│   └── news/
│       └── index.json
└── .github/
    └── workflows/
        └── fetch-news.yml
```

### 2단계 — Anthropic API 키 등록

1. [console.anthropic.com](https://console.anthropic.com) 에서 API 키 발급
2. GitHub 저장소 → Settings → Secrets and variables → Actions
3. **New repository secret** 클릭
4. Name: `ANTHROPIC_API_KEY` / Value: 발급받은 키 입력

### 3단계 — GitHub Pages 활성화

1. 저장소 → Settings → Pages
2. Source: **GitHub Actions** 선택
3. 첫 워크플로 성공 후 `https://[내아이디].github.io/stock-news-dashboard` 접속

### 4단계 — 첫 수동 실행 (테스트)

1. 저장소 → Actions 탭
2. **매일 뉴스 자동 수집** 클릭
3. **Run workflow** 버튼 클릭
4. 초록 체크 확인 후 사이트 새로고침

---

## ⏰ 자동 실행 시간

| 설정 | 실행 시간 |
|------|----------|
| 뉴스 | 매일 오전 8:00 KST |
| 지연 시세 | 평일 09:00~15:50 KST, 약 10분 간격 |

> 예약 실행은 GitHub 서버 상황에 따라 늦게 시작될 수 있습니다. 시세 출처는 Yahoo Finance이며 체결 실시간 데이터가 아닙니다.

---

## 💰 비용

| 항목 | 비용 |
|------|------|
| GitHub Actions | GitHub 계정의 현재 사용 한도 적용 |
| GitHub Pages | GitHub 계정 및 저장소 정책 적용 |
| Claude Haiku API | 사용량에 따라 과금되므로 Anthropic 콘솔에서 확인 |

---

## 📂 데이터 구조

```
data/news/
├── index.json          ← 날짜별 뉴스 수 목록 (달력 점 표시용)
└── 2026/
    └── 10/
        ├── 20.json     ← 해당 날짜 뉴스 배열
        └── 21.json
```

`data/market.json`에는 지원 종목과 주요 지수의 최신 지연 시세 및 일봉·주봉·월봉 데이터가 저장됩니다. `data/stocks.json`에는 KRX KIND에서 매일 갱신한 코스피·코스닥 검색 목록이 저장됩니다.

### DD.json 형식

```json
[
  {
    "id": "a1b2c3d4e5",
    "market": "kr",
    "source": "한국경제",
    "title": "뉴스 제목",
    "summary": "Claude가 요약한 내용",
    "link": "https://원문링크",
    "time": "08:32",
    "stocks": [
      { "code": "005930", "name": "삼성전자", "market": "kr", "chg": 2.35 }
    ]
  }
]
```

---

## 🛠 뉴스 수동 추가 방법

자동 수집이 놓친 뉴스는 직접 추가할 수 있습니다.

1. `data/news/YYYY/MM/DD.json` 파일 열기
2. 위 형식에 맞게 항목 추가
3. `data/news/index.json`의 해당 날짜 숫자 업데이트
4. 커밋 & 푸시

---

## 🔧 RSS 피드 추가/변경

`scripts/fetch_news.py`의 `RSS_FEEDS` 리스트를 수정하세요.

```python
RSS_FEEDS = [
    {"url": "https://피드주소.xml", "market": "kr", "source": "출처명"},
    ...
]
```

---

## ❓ 자주 묻는 문제

**뉴스가 안 보여요**
- Actions 탭에서 워크플로 실행 로그 확인
- `ANTHROPIC_API_KEY` secret이 등록되어 있는지 확인

**달력에 점이 안 찍혀요**
- `data/news/index.json` 파일이 있는지 확인
- GitHub Pages 캐시 문제 → 브라우저 강력 새로고침 (Ctrl+Shift+R)

**차트가 안 나와요**
- Actions에서 시세 수집 단계가 성공했고 `data/market.json`이 생성됐는지 확인
- 브라우저 강력 새로고침 (`Ctrl+Shift+R`)
