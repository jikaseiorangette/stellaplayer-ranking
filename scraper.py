"""
ステラプレイヤー ランキングスクレイパー
GraphQL APIから直接取得
"""

import json, os, re
from datetime import datetime, timezone, timedelta
from playwright.sync_api import sync_playwright

JST = timezone(timedelta(hours=9))

# GraphQLクエリ（ブラウザのPayloadから確認したもの）
GQL_QUERY = """
query rankingPageRank($rankType: RankType!, $topCategory: TopCategory, $take: Int) {
  GIRLS: ranking(rankType: $rankType, topCategory: GIRLS, take: $take) {
    id
    rank
    product {
      id
      name
      circle
      cv
      releaseDate
      thumbnailUrl
      tags
      url
    }
  }
  BL: ranking(rankType: $rankType, topCategory: BL, take: $take) {
    id
    rank
    product {
      id
      name
      circle
      cv
      releaseDate
      thumbnailUrl
      tags
      url
    }
  }
}
"""

def load_prev(path="data/ranking.json"):
    prev = {}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
            for cat, items in d.get("categories", {}).items():
                prev[cat] = {}
                for it in items:
                    if it.get("title"):
                        prev[cat][it["title"]] = it.get("rank")
        except Exception:
            pass
    return prev

def extract_items(raw_list, prev_cat):
    items = []
    for entry in (raw_list or []):
        p = entry.get("product") or {}
        title = p.get("name", "")
        # Unicode エスケープを解決
        if title.startswith("\\u") or "\\u" in title:
            try:
                title = title.encode().decode("unicode_escape")
            except Exception:
                pass
        circle = p.get("circle") or p.get("maker") or ""
        cv_raw = p.get("cv") or ""
        cv = cv_raw if isinstance(cv_raw, str) else "、".join(cv_raw)
        img = p.get("thumbnailUrl") or p.get("image") or ""
        release = str(p.get("releaseDate") or "")[:10]
        tags_raw = p.get("tags") or []
        tags = tags_raw if isinstance(tags_raw, list) else []
        link = p.get("url") or ""
        rank = entry.get("rank") or 0

        if title:
            items.append({
                "rank": rank,
                "title": title,
                "circle": circle,
                "cv": cv,
                "img": img,
                "release_date": release,
                "tags": [str(t) for t in tags][:8],
                "link": link,
                "prev_rank": prev_cat.get(title),
            })
    return items

def scrape_via_playwright(prev):
    """Playwrightでページを開き、GraphQLレスポンスをインターセプト"""
    results = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ))

        captured = {}

        def handle_response(response):
            try:
                if "graphql" in response.url and response.status == 200:
                    body = response.json()
                    data = body.get("data", {})
                    for cat in ["GIRLS", "BL", "GENERAL"]:
                        if cat in data and data[cat]:
                            captured[cat] = data[cat]
                            print(f"  📦 {cat}: {len(data[cat])}件 キャプチャ")
            except Exception:
                pass

        page = context.new_page()
        page.on("response", handle_response)

        print("GIRLSページを開いています...")
        page.goto(
            "https://www.stellaplayer.jp/ranking/GIRLS?rank_type=DAILY",
            wait_until="networkidle",
            timeout=60000
        )
        page.wait_for_timeout(3000)

        if "BL" not in captured:
            print("BLページを開いています...")
            page.goto(
                "https://www.stellaplayer.jp/ranking/BL?rank_type=DAILY",
                wait_until="networkidle",
                timeout=60000
            )
            page.wait_for_timeout(3000)

        browser.close()

    for cat, raw in captured.items():
        prev_cat = prev.get(cat, {})
        results[cat] = extract_items(raw, prev_cat)
        print(f"  → {cat}: {len(results[cat])}件")

    return results

def main():
    now = datetime.now(JST).strftime("%Y/%m/%d %H:%M")
    prev = load_prev()

    print("スクレイピング開始...")
    categories = scrape_via_playwright(prev)

    output = {"updated": now, "categories": categories}

    os.makedirs("data", exist_ok=True)
    with open("data/ranking.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    total = sum(len(v) for v in categories.values())
    print(f"\n✅ 保存完了: data/ranking.json ({now}) 合計{total}件")

if __name__ == "__main__":
    main()
