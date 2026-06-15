"""
ステラプレイヤー ランキングスクレイパー
毎日GitHub Actionsで自動実行 → data/ranking.json に保存
"""

import json, os, re
from datetime import datetime, timezone, timedelta
from playwright.sync_api import sync_playwright

JST = timezone(timedelta(hours=9))

TARGETS = {
    "GIRLS": "https://www.stellaplayer.jp/ranking/GIRLS?rank_type=DAILY",
    "BL":    "https://www.stellaplayer.jp/ranking/BL?rank_type=DAILY",
}

def load_prev(path="data/ranking.json"):
    """前回データを読み込んで {category: {rank: prev_rank}} のマップを返す"""
    prev = {}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
            for cat, items in d.get("categories", {}).items():
                prev[cat] = {}
                for it in items:
                    if it.get("title") and it.get("rank"):
                        prev[cat][it["title"]] = it["rank"]
        except Exception:
            pass
    return prev

def scrape(page, url):
    page.goto(url, wait_until="networkidle", timeout=60000)

    # ランキングリストが出るまで待つ（セレクタは複数候補）
    try:
        page.wait_for_selector("li[class*='Ranking'], div[class*='RankingItem'], ul[class*='ranking'] li", timeout=20000)
    except Exception:
        pass

    items = []

    # ① JSON-LD や Next.js の __NEXT_DATA__ からデータ取得を試みる
    next_data = page.evaluate("""
        () => {
            const el = document.getElementById('__NEXT_DATA__');
            return el ? el.textContent : null;
        }
    """)

    if next_data:
        try:
            nd = json.loads(next_data)
            # props.pageProps 配下を再帰的に探す
            def find_list(obj, depth=0):
                if depth > 8: return None
                if isinstance(obj, list) and len(obj) > 0:
                    first = obj[0]
                    if isinstance(first, dict) and ("title" in first or "name" in first or "rank" in first):
                        return obj
                if isinstance(obj, dict):
                    for v in obj.values():
                        r = find_list(v, depth+1)
                        if r: return r
                return None

            lst = find_list(nd.get("props", {}).get("pageProps", {}))
            if lst:
                for i, it in enumerate(lst):
                    title = it.get("title") or it.get("name") or it.get("workTitle") or ""
                    circle = it.get("circle") or it.get("maker") or it.get("brand") or ""
                    cv = it.get("cast") or it.get("cv") or it.get("voice") or ""
                    img = it.get("image") or it.get("img") or it.get("thumbnail") or ""
                    rank = it.get("rank") or it.get("ranking") or i+1
                    release = it.get("releaseDate") or it.get("release_date") or it.get("date") or ""
                    tags = it.get("tags") or it.get("genres") or it.get("keyword") or []
                    if isinstance(tags, str): tags = [t.strip() for t in tags.split(",")]

                    if title:
                        items.append({
                            "rank": int(rank) if rank else i+1,
                            "title": title,
                            "circle": circle,
                            "cv": cv if isinstance(cv, str) else ", ".join(cv),
                            "img": img,
                            "release_date": str(release)[:10],
                            "tags": [str(t) for t in tags][:8],
                            "link": ""
                        })
                print(f"  __NEXT_DATA__ から {len(items)} 件取得")
                return items
        except Exception as e:
            print(f"  __NEXT_DATA__ parse error: {e}")

    # ② DOMスクレイピングにフォールバック
    print("  DOM スクレイピングを試みます...")

    # ページ内の全テキストを取得してデバッグ
    cards = page.query_selector_all("li[class*='Ranking'], div[class*='RankingItem'], article[class*='rank'], [class*='ranking-item']")
    print(f"  カード要素数: {len(cards)}")

    for i, card in enumerate(cards):
        try:
            rank_el   = card.query_selector("[class*='num'], [class*='Num'], [class*='number'], [class*='rank']")
            title_el  = card.query_selector("[class*='title'], [class*='Title'], h2, h3, p[class*='name']")
            circle_el = card.query_selector("[class*='circle'], [class*='Circle'], [class*='maker'], [class*='brand']")
            cv_el     = card.query_selector("[class*='cast'], [class*='Cast'], [class*='cv'], [class*='voice']")
            img_el    = card.query_selector("img")
            link_el   = card.query_selector("a")
            tag_els   = card.query_selector_all("[class*='tag'], [class*='Tag'], [class*='genre'], [class*='keyword']")
            date_el   = card.query_selector("[class*='date'], [class*='Date'], time")

            title  = title_el.inner_text().strip()  if title_el  else ""
            circle = circle_el.inner_text().strip() if circle_el else ""
            cv     = cv_el.inner_text().strip()     if cv_el     else ""
            img    = img_el.get_attribute("src")    if img_el    else ""
            link   = link_el.get_attribute("href")  if link_el   else ""
            date   = date_el.inner_text().strip()   if date_el   else ""
            tags   = [t.inner_text().strip() for t in tag_els if t.inner_text().strip()]

            # ランク番号取得
            rank_text = rank_el.inner_text().strip() if rank_el else str(i+1)
            rank_num  = int(re.search(r'\d+', rank_text).group()) if re.search(r'\d+', rank_text) else i+1

            if title:
                items.append({
                    "rank": rank_num,
                    "title": title,
                    "circle": circle,
                    "cv": cv,
                    "img": img,
                    "release_date": date[:10] if date else "",
                    "tags": tags[:8],
                    "link": f"https://www.stellaplayer.jp{link}" if link.startswith("/") else link,
                })
        except Exception as e:
            print(f"  card[{i}] error: {e}")

    return items


def main():
    now = datetime.now(JST).strftime("%Y/%m/%d %H:%M")
    prev = load_prev()
    output = {"updated": now, "categories": {}}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ))

        for cat, url in TARGETS.items():
            print(f"\n=== {cat} ===")
            try:
                items = scrape(page, url)

                # prev_rank を付与
                prev_cat = prev.get(cat, {})
                for it in items:
                    it["prev_rank"] = prev_cat.get(it["title"])

                output["categories"][cat] = items
                print(f"  → {len(items)} 件")
            except Exception as e:
                print(f"  ERROR: {e}")
                output["categories"][cat] = []

        browser.close()

    os.makedirs("data", exist_ok=True)
    with open("data/ranking.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 保存完了: data/ranking.json ({now})")


if __name__ == "__main__":
    main()
