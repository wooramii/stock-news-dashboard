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
DATA_DIR = Path("data/news")

# 한 번에 처리할 최대 뉴스 수 (Claude API 비용 절감)
MAX_NEWS_PER_RUN = 20

# ── RSS 피드 목록 ──────────────────────────────────────
RSS_FEEDS = [
    {"url": "https://www.hankyung.com/feed/finance", "market": "kr", "source": "한국경제"},
    {"url": "https://www.mk.co.kr/rss/50200011/", "market": "kr", "source": "매일경제"},
    {"url": "https://feeds.bloomberg.com/markets/news.rss", "market": "us", "source": "Bloomberg"},
]

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

    return unique[:MAX_NEWS_PER_RUN]

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
    merged = existing + new_items

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

# ── 메인 ──────────────────────────────────────────────
def main():
    dt = target_dt()
    print(f"\n{'='*50}")
    print(f"  뉴스 수집 시작: {dt.strftime('%Y-%m-%d %H:%M KST')}")
    print(f"{'='*50}")

    print("\n1) RSS 수집 중...")
    items = fetch_rss_items(dt)
    print(f"   수집된 뉴스: {len(items)}건")

    if not items:
        print("   수집된 뉴스가 없습니다. 종료.")
        return

    print("\n2) Claude API로 요약 중...")
    items = summarize_with_claude(items)

    print("\n3) 파일 저장 중...")
    date_key, count = save_news(dt, items)
    update_index(date_key, count)

    print(f"\n완료! {date_key}: {count}건 저장됨\n")

if __name__ == "__main__":
    main()
