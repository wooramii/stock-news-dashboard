"""
fetch_news.py
─────────────
1. RSS 피드에서 국내/해외 주식 뉴스 수집
2. Claude API로 요약 + 관련 종목 추출
3. data/news/YYYY/MM/DD.json 저장
4. data/news/index.json 업데이트
"""

import os, json, re, time, hashlib
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
import feedparser

# ── 설정 ──────────────────────────────────────────────
KST = timezone(timedelta(hours=9))
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
TARGET_DATE = os.environ.get("TARGET_DATE", "").strip()   # YYYY-MM-DD or ""
MARKET_ONLY = os.environ.get("MARKET_ONLY", "").lower() == "true"
DATA_DIR = Path("data/news")
MARKET_FILE = Path("data/market.json")
STOCKS_FILE = Path("data/stocks.json")

# 한 번에 처리할 최대 뉴스 수 (Claude API 비용 절감)
MAX_NEWS_PER_RUN = 20

# ── RSS 피드 목록 ──────────────────────────────────────
RSS_FEEDS = [
    {"url": "https://www.hankyung.com/feed/finance", "market": "kr", "source": "한국경제"},
    {"url": "https://www.mk.co.kr/rss/50200011/", "market": "kr", "source": "매일경제"},
    {"url": "https://feeds.bloomberg.com/markets/news.rss", "market": "us", "source": "Bloomberg"},
    {"url": "https://www.cnbc.com/id/10000664/device/rss/rss.html", "market": "us", "source": "CNBC"},
    {"url": "https://www.nasdaq.com/feed/rssoutbound?category=Markets", "market": "us", "source": "Nasdaq"},
]

# 화면에서 상세 조회를 지원하는 종목. Yahoo Finance의 공개 차트 응답을
# 매일 저장해 브라우저에 오래된 하드코딩 가격을 남기지 않는다.
MARKET_SYMBOLS = {
    "005930": {"name": "삼성전자", "market": "KOSPI", "symbol": "005930.KS"},
    "000660": {"name": "SK하이닉스", "market": "KOSPI", "symbol": "000660.KS"},
    "006800": {"name": "미래에셋증권", "market": "KOSPI", "symbol": "006800.KS"},
    "064350": {"name": "현대로템", "market": "KOSPI", "symbol": "064350.KS"},
    "015760": {"name": "한국전력", "market": "KOSPI", "symbol": "015760.KS"},
    "012450": {"name": "한화에어로스페이스", "market": "KOSPI", "symbol": "012450.KS"},
    "108380": {"name": "대양전기공업", "market": "KOSDAQ", "symbol": "108380.KQ"},
    "KOSPI": {"name": "코스피", "market": "INDEX", "symbol": "^KS11"},
    "KOSDAQ": {"name": "코스닥", "market": "INDEX", "symbol": "^KQ11"},
    "KOSPI200": {"name": "코스피200", "market": "INDEX", "symbol": "^KS200"},
    "SP500": {"name": "S&P 500", "market": "INDEX", "symbol": "^GSPC"},
    "NASDAQ": {"name": "나스닥", "market": "INDEX", "symbol": "^IXIC"},
    "DOW": {"name": "다우", "market": "INDEX", "symbol": "^DJI"},
    "NIKKEI": {"name": "닛케이225", "market": "INDEX", "symbol": "^N225"},
    "HANGSENG": {"name": "항셍", "market": "INDEX", "symbol": "^HSI"},
    "SHANGHAI": {"name": "상하이종합", "market": "INDEX", "symbol": "000001.SS"},
    "A0158S0": {"name": "엘리스그룹", "market": "KOSDAQ", "symbol": "0158S0.KQ"},
    "035720": {"name": "카카오", "market": "KOSPI", "symbol": "035720.KS"},
    "005380": {"name": "현대차", "market": "KOSPI", "symbol": "005380.KS"},
    "373220": {"name": "LG에너지솔루션", "market": "KOSPI", "symbol": "373220.KS"},
    "006400": {"name": "삼성SDI", "market": "KOSPI", "symbol": "006400.KS"},
    "035420": {"name": "NAVER", "market": "KOSPI", "symbol": "035420.KS"},
    "051910": {"name": "LG화학", "market": "KOSPI", "symbol": "051910.KS"},
    "AAPL": {"name": "Apple", "market": "NASDAQ", "symbol": "AAPL"},
    "NVDA": {"name": "NVIDIA", "market": "NASDAQ", "symbol": "NVDA"},
    "MSFT": {"name": "Microsoft", "market": "NASDAQ", "symbol": "MSFT"},
    "META": {"name": "Meta", "market": "NASDAQ", "symbol": "META"},
    "GOOGL": {"name": "Alphabet", "market": "NASDAQ", "symbol": "GOOGL"},
    "AMZN": {"name": "Amazon", "market": "NASDAQ", "symbol": "AMZN"},
    "TSLA": {"name": "Tesla", "market": "NASDAQ", "symbol": "TSLA"},
    "SKHY": {"name": "SK하이닉스 ADR", "market": "NASDAQ", "symbol": "SKHY"},
}

STOCK_ALIASES = {
    "삼성전자": "005930", "삼전": "005930",
    "SK하이닉스": "000660", "하이닉스": "000660", "삼전닉스": "000660",
    "미래에셋증권": "006800", "미래에셋": "006800",
    "현대로템": "064350", "한국전력": "015760",
    "한화에어로스페이스": "012450", "대양전기공업": "108380",
    "엘리스그룹": "A0158S0", "엘리스": "A0158S0",
    "KT&G": "033780",
    "코스피": "KOSPI",
}

# ── 헬퍼 ──────────────────────────────────────────────
def today_kst():
    return datetime.now(KST)

def target_dt():
    """환경변수 TARGET_DATE가 있으면 그 날짜, 없으면 오늘(KST)"""
    if TARGET_DATE:
        return datetime.strptime(TARGET_DATE, "%Y-%m-%d").replace(tzinfo=KST)
    return today_kst()

def news_id(title: str) -> str:
    return hashlib.md5(title.encode()).hexdigest()[:10]

def is_stock_news(title: str, summary: str) -> bool:
    """주식/경제 관련 뉴스인지 간단 필터링"""
    keywords = [
        "주가","증시","코스피","코스닥","상승","하락","주식","실적","매출","영업이익",
        "IPO","상장","공모","배당","목표주가","투자","펀드","ETF","반도체","바이오",
        "stock","market","earnings","revenue","profit","nasdaq","s&p","dow","fed",
        "rate","inflation","gdp","economy","shares","ipo","dividend","analyst"
    ]
    text = (title + " " + summary).lower()
    return any(k in text for k in keywords)

@__import__("functools").lru_cache(maxsize=1)
def load_kr_stock_lookup():
    """상장종목 목록을 종목명과 코드로 조회할 수 있게 준비한다."""
    try:
        data = json.loads(STOCKS_FILE.read_text(encoding="utf-8"))
        stocks = data.get("stocks", [])
    except Exception as e:
        print(f"  [종목 검증 오류] 상장종목 목록을 읽지 못했습니다: {e}")
        return {}, {}

    by_code = {
        str(stock.get("code", "")).strip(): stock
        for stock in stocks
        if str(stock.get("code", "")).strip()
    }
    by_name = {
        re.sub(r"\s+", "", str(stock.get("name", ""))).casefold(): stock
        for stock in stocks
        if str(stock.get("name", "")).strip()
    }
    return by_code, by_name

def validate_related_stocks(stocks: list[dict]) -> list[dict]:
    """국내 종목의 AI 생성 코드와 종목명을 KRX 목록으로 교차 검증한다."""
    by_code, by_name = load_kr_stock_lookup()
    validated = []
    seen = set()

    for stock in stocks:
        if not isinstance(stock, dict):
            continue

        market = str(stock.get("market", "")).lower()
        code = str(stock.get("code", "")).strip().upper()
        name = str(stock.get("name", "")).strip()

        if market == "kr" or re.fullmatch(r"\d{6}", code):
            # 명시적 별칭 또는 정확한 종목명으로 확인된 경우에만 채택한다.
            alias_code = next((
                alias_code for alias, alias_code in sorted(
                    STOCK_ALIASES.items(), key=lambda pair: len(pair[0]), reverse=True
                ) if alias.casefold() in name.casefold()
            ), None)
            listed = by_code.get(alias_code) if alias_code else None
            if listed is None:
                listed = by_name.get(re.sub(r"\s+", "", name).casefold())
            if listed is None:
                code_match = by_code.get(code)
                official_name = re.sub(r"\s+", "", str(code_match.get("name", ""))).casefold() if code_match else ""
                ai_name = re.sub(r"\s+", "", name).casefold()
                listed = code_match if official_name and official_name == ai_name else None
            if listed is None:
                print(f"  [종목 제외] 이름·코드 불일치: {name} ({code})")
                continue
            code = str(listed["code"])
            name = str(listed["name"])
            market = "kr"

        if not code or code in seen:
            continue
        seen.add(code)
        validated.append({
            "code": code,
            "name": name,
            "market": market,
            "chg": float(stock.get("chg", 0.0) or 0.0),
        })

    return validated[:4]

# ── RSS 수집 ───────────────────────────────────────────
def fetch_rss_items(dt: datetime) -> list[dict]:
    """당일 뉴스 항목을 RSS에서 수집"""
    items = []
    date_str = dt.strftime("%Y-%m-%d")

    for feed_cfg in RSS_FEEDS:
        try:
            response = requests.get(
                feed_cfg["url"],
                headers={"User-Agent": "stock-news-dashboard/1.0"},
                timeout=20,
            )
            response.raise_for_status()
            feed = feedparser.parse(response.content)
            for entry in feed.entries[:30]:
                # 발행일 파싱
                pub = None
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    pub = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc).astimezone(KST)
                elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
                    pub = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc).astimezone(KST)

                if pub and pub.strftime("%Y-%m-%d") != date_str:
                    continue

                title   = entry.get("title", "").strip()
                summary = entry.get("summary", entry.get("description", "")).strip()
                link    = entry.get("link", "")

                # HTML 태그 제거
                summary = re.sub(r"<[^>]+>", "", summary)[:400]

                if not title or not is_stock_news(title, summary):
                    continue

                items.append({
                    "id":      news_id(title),
                    "market":  feed_cfg["market"],
                    "source":  feed_cfg["source"],
                    "title":   title,
                    "raw_summary": summary,
                    "link":    link,
                    "time":    pub.strftime("%H:%M") if pub else "00:00",
                })
        except Exception as e:
            print(f"  [RSS 오류] {feed_cfg['source']}: {e}")

    # 중복 제거
    seen = set()
    unique = []
    for item in items:
        if item["id"] not in seen:
            seen.add(item["id"])
            unique.append(item)

    # 국내 기사만 먼저 20건을 채워 해외 기사가 잘리던 문제를 막는다.
    kr = [item for item in unique if item["market"] == "kr"]
    us = [item for item in unique if item["market"] == "us"]
    selected = kr[:10] + us[:10]
    if len(selected) < MAX_NEWS_PER_RUN:
        selected_ids = {item["id"] for item in selected}
        selected += [item for item in unique if item["id"] not in selected_ids][:(MAX_NEWS_PER_RUN-len(selected))]
    return selected

# ── Claude API 요약 ────────────────────────────────────
def summarize_with_claude(items: list[dict]) -> list[dict]:
    """Claude API로 뉴스 요약 + 관련 종목 추출"""
    if not ANTHROPIC_API_KEY:
        print("  [경고] ANTHROPIC_API_KEY 없음 → 요약 건너뜀")
        for item in items:
            item["summary"] = item.get("raw_summary", "")[:150]
            item["stocks"] = []
        return items

    results = []
    for item in items:
        prompt = f"""다음 뉴스를 분석해서 JSON으로 답하세요. 반드시 JSON만 출력하고 다른 말은 하지 마세요.

제목: {item['title']}
원문: {item.get('raw_summary', '')}

출력 형식:
{{
  "summary": "2~3문장으로 핵심만 요약 (한국어)",
  "stocks": [
    {{"code": "종목코드", "name": "종목명", "market": "kr 또는 us", "chg": 0.0}}
  ]
}}

규칙:
- summary는 반드시 한국어로 작성
- stocks는 뉴스에서 직접 언급된 종목만 포함 (최대 4개)
- 한국 종목은 6자리 숫자 코드 (예: 005930), 미국은 티커 (예: AAPL)
- chg는 뉴스에 등락률이 언급되면 숫자로, 없으면 0.0
- stocks가 없으면 빈 배열 []
"""
        try:
            resp = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 400,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=20,
            )
            resp.raise_for_status()
            content = resp.json()["content"][0]["text"].strip()

            # JSON 파싱
            m = re.search(r"\{.*\}", content, re.DOTALL)
            if m:
                parsed = json.loads(m.group())
                item["summary"] = parsed.get("summary", item.get("raw_summary","")[:150])
                item["stocks"]  = parsed.get("stocks", [])
            else:
                raise ValueError("JSON 없음")

        except Exception as e:
            print(f"  [Claude 오류] {item['title'][:40]}... → {e}")
            item["summary"] = item.get("raw_summary", "")[:150]
            item["stocks"]  = []

        item["stocks"] = validate_related_stocks(item.get("stocks", []))

        # API 과부하 방지
        time.sleep(0.5)
        results.append(item)

    return results

# ── 파일 저장 ──────────────────────────────────────────
def save_news(dt: datetime, items: list[dict]):
    y  = dt.strftime("%Y")
    m  = dt.strftime("%m")
    d  = dt.strftime("%d")
    date_key = f"{y}/{m}/{d}"

    # data/news/YYYY/MM/DD.json
    out_dir = DATA_DIR / y / m
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{d}.json"

    # 기존 파일이 있으면 병합 (같은 날 여러 번 실행 시 중복 방지)
    existing = []
    if out_file.exists():
        try:
            existing = json.loads(out_file.read_text(encoding="utf-8"))
        except Exception:
            existing = []

    existing_ids = {n["id"] for n in existing}
    new_items = [n for n in items if n["id"] not in existing_ids]
    merged_by_id = {n["id"]: n for n in existing}
    for n in items:
        merged_by_id[n["id"]] = n
    merged = list(merged_by_id.values())

    # 저장 시 raw_summary 제거 (용량 절감)
    clean = []
    for n in merged:
        n.pop("raw_summary", None)
        clean.append(n)

    out_file.write_text(
        json.dumps(clean, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"  저장: {out_file}  ({len(new_items)}건 추가, 총 {len(clean)}건)")
    return date_key, len(clean)

def update_index(date_key: str, count: int):
    """data/news/index.json — 날짜별 뉴스 수 기록"""
    index_file = DATA_DIR / "index.json"
    index = {}
    if index_file.exists():
        try:
            index = json.loads(index_file.read_text(encoding="utf-8"))
        except Exception:
            index = {}

    index[date_key] = count
    # 최근 365일치만 유지
    if len(index) > 365:
        keys = sorted(index.keys())
        for old_key in keys[:-365]:
            del index[old_key]

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    index_file.write_text(
        json.dumps(index, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"  index.json 업데이트: {date_key} = {count}건")

def update_stock_universe():
    """KRX KIND 상장법인 목록에서 코스피·코스닥 검색용 종목을 갱신한다."""
    try:
        response = requests.get(
            "https://kind.krx.co.kr/corpgeneral/corpList.do",
            params={"method": "download", "searchType": "13"},
            headers={"User-Agent": "Mozilla/5.0 stock-news-dashboard/1.0"},
            timeout=30,
        )
        response.raise_for_status()
        text = response.content.decode("euc-kr", errors="ignore")
        stocks = []
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", text, re.I | re.S)[1:]:
            cells = [
                re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", cell)).strip()
                for cell in re.findall(r"<td[^>]*>(.*?)</td>", row, re.I | re.S)
            ]
            market = {"유가": "KOSPI", "코스피": "KOSPI", "코스닥": "KOSDAQ"}.get(cells[1]) if len(cells) >= 3 else None
            if not market:
                continue
            code = cells[2].upper()
            if re.fullmatch(r"[0-9A-Z]{6}", code):
                stocks.append({"code": code, "name": cells[0], "market": market})
        if len(stocks) < 2000:
            raise ValueError(f"상장종목 수가 비정상적으로 적음: {len(stocks)}")
        stocks.sort(key=lambda item: (item["market"], item["name"]))
        STOCKS_FILE.write_text(json.dumps({
            "updatedAt": today_kst().isoformat(timespec="minutes"),
            "source": "KRX KIND",
            "stocks": stocks,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  저장: {STOCKS_FILE} ({len(stocks)}종목)")
    except Exception as e:
        print(f"  [상장종목 목록 오류] 기존 파일 유지: {e}")

def _last_by_period(timestamps, closes, period):
    grouped = {}
    for ts, close in zip(timestamps, closes):
        if close is None:
            continue
        dt = datetime.fromtimestamp(ts, timezone.utc)
        if period == "weekly":
            iso = dt.isocalendar()
            key = f"{iso.year}-W{iso.week:02d}"
        else:
            key = dt.strftime("%Y-%m")
        grouped[key] = {"date": dt.strftime("%Y-%m-%d"), "close": round(close, 2)}
    return list(grouped.values())

def discover_market_symbols():
    """기존 뉴스 파일의 정상 종목코드를 찾아 시세 수집 대상을 자동 확장한다."""
    symbols = dict(MARKET_SYMBOLS)
    for news_file in DATA_DIR.glob("*/*/*.json"):
        try:
            items = json.loads(news_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        for item in items:
            for stock in item.get("stocks", []):
                name = str(stock.get("name", "")).strip()
                code = str(stock.get("code", "")).strip().upper()
                for alias, canonical_code in STOCK_ALIASES.items():
                    if alias in name:
                        code = canonical_code
                        break
                if not code or code in symbols:
                    continue
                market = str(stock.get("market", "")).lower()
                if market == "kr" and re.fullmatch(r"\d{6}", code):
                    symbols[code] = {
                        "name": name or code,
                        "market": "KR",
                        "candidates": [f"{code}.KS", f"{code}.KQ"],
                    }
                elif market == "us" and re.fullmatch(r"[A-Z.\-]{1,10}", code):
                    symbols[code] = {"name": name or code, "market": "US", "symbol": code}
    return symbols

def fetch_market_data():
    """실제 종가와 2년치 차트 데이터를 data/market.json에 저장한다."""
    stocks = {}
    for code, cfg in discover_market_symbols().items():
        try:
            result = None
            last_error = None
            for symbol in cfg.get("candidates", [cfg.get("symbol")]):
                if not symbol:
                    continue
                try:
                    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
                    response = requests.get(
                        url,
                        params={"range": "2y", "interval": "1d", "events": "div,splits"},
                        headers={"User-Agent": "Mozilla/5.0 stock-news-dashboard/1.0"},
                        timeout=20,
                    )
                    response.raise_for_status()
                    result = response.json()["chart"]["result"][0]
                    break
                except Exception as candidate_error:
                    last_error = candidate_error
            if result is None:
                raise last_error or ValueError("사용 가능한 시세 심볼 없음")
            meta = result["meta"]
            timestamps = result.get("timestamp", [])
            closes = result["indicators"]["quote"][0].get("close", [])
            daily = [
                {"date": datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d"), "close": round(close, 2)}
                for ts, close in zip(timestamps, closes) if close is not None
            ]
            price = meta.get("regularMarketPrice") or (daily[-1]["close"] if daily else None)
            # chartPreviousClose는 range 시작 직전 값일 수 있으므로 전일 종가는
            # 일별 시계열의 바로 이전 거래일 종가를 사용한다.
            prev = daily[-2]["close"] if len(daily) > 1 else meta.get("previousClose")
            chg = round((price - prev) / prev * 100, 2) if price and prev else 0
            stocks[code] = {
                "name": cfg["name"], "market": cfg["market"],
                "price": price, "prevClose": prev, "chg": chg,
                "currency": meta.get("currency", "KRW" if code.isdigit() else "USD"),
                "chart": {
                    "daily": daily[-30:],
                    "weekly": _last_by_period(timestamps, closes, "weekly")[-26:],
                    "monthly": _last_by_period(timestamps, closes, "monthly")[-24:],
                },
            }
            print(f"  시세: {cfg['name']} {price}")
        except Exception as e:
            print(f"  [시세 오류] {cfg['name']}: {e}")

    MARKET_FILE.parent.mkdir(parents=True, exist_ok=True)
    MARKET_FILE.write_text(json.dumps({
        "updatedAt": today_kst().isoformat(timespec="minutes"),
        "source": "Yahoo Finance",
        "stocks": stocks,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  저장: {MARKET_FILE} ({len(stocks)}종목)")

# ── 메인 ──────────────────────────────────────────────
def main():
    dt = target_dt()
    print(f"\n{'='*50}")
    print(f"  뉴스 수집 시작: {dt.strftime('%Y-%m-%d %H:%M KST')}")
    print(f"{'='*50}")

    if MARKET_ONLY:
        print("\n1) 실제 주가·차트 수집 중...")
        fetch_market_data()
        print("   장중 시세 전용 실행: 뉴스 수집은 건너뜁니다.")
        return

    print("\n1) RSS 수집 중...")
    items = fetch_rss_items(dt)
    print(f"   수집된 뉴스: {len(items)}건")

    if not items:
        print("   수집된 뉴스가 없습니다. 시세만 업데이트합니다.")
        update_stock_universe()
        fetch_market_data()
        return

    print("\n2) Claude API로 요약 중...")
    items = summarize_with_claude(items)

    print("\n3) 파일 저장 중...")
    date_key, count = save_news(dt, items)
    update_index(date_key, count)

    print("\n4) 코스피·코스닥 종목 목록 갱신 중...")
    update_stock_universe()

    print("\n5) 실제 주가·차트 수집 중...")
    fetch_market_data()

    print(f"\n완료! {date_key}: {count}건 저장됨\n")

if __name__ == "__main__":
    main()
