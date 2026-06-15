"""
ステラプレイヤー ランキングスクレイパー
毎日GitHub Actionsで自動実行 → data/ranking.json に保存
"""

import json
import re
from datetime import datetime, timezone, timedelta
from playwright.sync_api import sync_playwright

JST = timezone(timedelta(hours=9))

URLS = {
    "GIRLS": "https://www.stellaplayer.jp/ranking/GIRLS?rank_type=DAILY",
    "BL":    "https://www.stellaplayer.jp/ranking/BL?rank_type=DAILY",
}

def scrape_ranking(page, url: str) -> list[dict]:
    page.goto(url, wait_until="networkidle", timeout=60000)
    # ランキングカードが描画されるまで待機
    page.wait_for_selector("[class*='RankingItem'], [class*='ranking-item'], li[class*='rank']", timeout=20000)

    items = []
    # 各ランキングアイテムを取得（セレクタはページ構造に合わせて調整）
    cards = page.query_selector_all("[class*='RankingItem'], li[class*='RankingListItem']")

    for card in cards:
        try:
            rank_el   = card.query_selector("[class*='rank-num'], [class*='RankNum'], [class*='number']")
            title_el  = card.query_selector("[class*='title'], [class*='Title'], h2, h3")
            circle_el = card.query_selector("[class*='circle'], [class*='Circle'], [class*='label']")
            cv_el     = card.query_selector("[class*='cast'], [class*='Cast'], [class*='cv']")
            img_el    = card.query_selector("img")
            link_el   = card.query_selector("a")
            tags_els  = card.query_selector_all("[class*='tag'], [class*='Tag']")

            rank  = rank_el.inner_text().strip()  if rank_el  else ""
            title = title_el.inner_text().strip() if title_el else ""
            circle= circle_el.inner_text().strip()if circle_el else ""
            cv    = cv_el.inner_text().strip()    if cv_el    else ""
            img   = img_el.get_attribute("src")   if img_el   else ""
            link  = link_el.get_attribute("href") if link_el  else ""
            tags  = [t.inner_text().strip() for t in tags_els if t.inner_text().strip()]

            if title:
                items.append({
                    "rank":   rank,
                    "title":  title,
                    "circle": circle,
                    "cv":     cv,
                    "img":    img,
                    "link":   f"https://www.stellaplayer.jp{link}" if link.startswith("/") else link,
                    "tags":   tags,
                })
        except Exception as e:
            print(f"  card parse error: {e}")
            continue

    return items


def main():
    now = datetime.now(JST).strftime("%Y/%m/%d %H:%M")
    output = {"updated": now, "categories": {}}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
        )

        for category, url in URLS.items():
            print(f"Scraping {category}...")
            try:
                items = scrape_ranking(page, url)
                output["categories"][category] = items
                print(f"  → {len(items)} items")
            except Exception as e:
                print(f"  ERROR: {e}")
                output["categories"][category] = []

        browser.close()

    import os
    os.makedirs("data", exist_ok=True)
    with open("data/ranking.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Saved to data/ranking.json ({now})")


if __name__ == "__main__":
    main()
