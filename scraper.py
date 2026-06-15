"""
ステラプレイヤー ランキングスクレイパー
- 正確なGraphQLクエリ + genres フィールドで一括取得
"""

import json, os, re, time
from datetime import datetime, timezone, timedelta
from playwright.sync_api import sync_playwright

JST = timezone(timedelta(hours=9))

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

def extract_cv_from_title(title):
    m = re.search(r'[（(]CV[：:]\s*([^）)]+)[）)]', title)
    return m.group(1).strip() if m else ""

def fetch_ranking(page):
    """GraphQL APIを直接呼び出してランキング+ジャンルを一括取得"""
    result = page.evaluate("""
        async () => {
            const res = await fetch('https://api.stellaplayer.jp/graphql', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Origin': 'https://www.stellaplayer.jp',
                    'Referer': 'https://www.stellaplayer.jp/',
                },
                body: JSON.stringify({
                    operationName: 'rankingPageRank',
                    query: `query rankingPageRank($rankType: RankType!, $take: Int!) {
  GIRLS: ranks(filter: {rank_type: $rankType, top_category: GIRLS, take: $take}) {
    id rank product {
      id name release_schedule publish_starts_at
      converted_featured_images is_new is_online_only
      brand { id name }
      genres { id name }
    }
  }
  BL: ranks(filter: {rank_type: $rankType, top_category: BL, take: $take}) {
    id rank product {
      id name release_schedule publish_starts_at
      converted_featured_images is_new is_online_only
      brand { id name }
      genres { id name }
    }
  }
}`,
                    variables: {rankType: 'DAILY', take: 20}
                })
            });
            return res.json();
        }
    """)
    return result

def extract_items(raw_list, prev_cat):
    items = []
    for entry in (raw_list or []):
        p = entry.get("product") or {}

        title_raw = p.get("name") or ""
        cv = extract_cv_from_title(title_raw)
        title = re.sub(r'\s*[（(]CV[：:][^）)]+[）)]\s*', '', title_raw).strip()

        # サークル（brand.name）
        brand = p.get("brand") or {}
        circle = brand.get("name", "") if isinstance(brand, dict) else ""

        # サムネイル
        img = ""
        cfi = p.get("converted_featured_images") or {}
        if isinstance(cfi, dict):
            img = (cfi.get("800x800_png") or cfi.get("200x200_png") or
                   next(iter(cfi.values()), ""))

        # 発売日
        release = ""
        for key in ["release_schedule", "publish_starts_at"]:
            if p.get(key):
                release = str(p[key])[:10].split("T")[0].split(" ")[0]
                break

        # ジャンル（genres フィールド）
        genres_raw = p.get("genres") or []
        tags = [g.get("name", "") for g in genres_raw if isinstance(g, dict) and g.get("name")]

        product_id = str(p.get("id") or "")
        link = f"https://www.stellaplayer.jp/product/{product_id}" if product_id else ""
        rank = int(entry.get("rank") or 0)

        if title:
            items.append({
                "rank": rank,
                "title": title,
                "circle": circle,
                "cv": cv,
                "img": img,
                "release_date": release,
                "tags": tags[:8],
                "link": link,
                "prev_rank": prev_cat.get(title),
                "history": [],
            })

    items.sort(key=lambda x: x["rank"])
    return items

def scrape(prev):
    results = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ))
        page = context.new_page()

        # まずランキングページを開いてCookieセット
        print("ランキングページを開いています...")
        page.goto("https://www.stellaplayer.jp/ranking/GIRLS?rank_type=DAILY",
                  wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(2000)

        # GraphQL API を直接呼び出し
        print("GraphQL APIを呼び出しています...")
        api_result = fetch_ranking(page)

        if api_result and "data" in api_result:
            data = api_result["data"]
            print(f"  取得カテゴリ: {list(data.keys())}")

            for cat in ["GIRLS", "BL"]:
                if cat not in data or not data[cat]:
                    print(f"  {cat}: データなし")
                    continue
                prev_cat = prev.get(cat, {})
                items = extract_items(data[cat], prev_cat)
                results[cat] = items
                print(f"  {cat}: {len(items)}件")
                for it in items[:3]:
                    print(f"    rank={it['rank']} {it['title'][:25]} cv={it['cv']} genres={it['tags'][:3]}")

        elif api_result and "errors" in api_result:
            # genresフィールドがない場合はフォールバック（genresなし）
            print(f"  APIエラー: {api_result['errors'][0].get('message','')}")
            print("  genresなしで再試行...")
            result2 = page.evaluate("""
                async () => {
                    const res = await fetch('https://api.stellaplayer.jp/graphql', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'Origin': 'https://www.stellaplayer.jp',
                            'Referer': 'https://www.stellaplayer.jp/',
                        },
                        body: JSON.stringify({
                            operationName: 'rankingPageRank',
                            query: `query rankingPageRank($rankType: RankType!, $take: Int!) {
  GIRLS: ranks(filter: {rank_type: $rankType, top_category: GIRLS, take: $take}) {
    id rank product {
      id name release_schedule publish_starts_at
      converted_featured_images is_new is_online_only
      brand { id name }
    }
  }
  BL: ranks(filter: {rank_type: $rankType, top_category: BL, take: $take}) {
    id rank product {
      id name release_schedule publish_starts_at
      converted_featured_images is_new is_online_only
      brand { id name }
    }
  }
}`,
                            variables: {rankType: 'DAILY', take: 20}
                        })
                    });
                    return res.json();
                }
            """)
            if result2 and "data" in result2:
                for cat in ["GIRLS", "BL"]:
                    if cat in result2["data"] and result2["data"][cat]:
                        prev_cat = prev.get(cat, {})
                        results[cat] = extract_items(result2["data"][cat], prev_cat)
                        print(f"  {cat}: {len(results[cat])}件（ジャンルなし）")
        else:
            print(f"  予期しないレスポンス: {json.dumps(api_result)[:300]}")

        browser.close()

    return results

def main():
    now = datetime.now(JST).strftime("%Y/%m/%d %H:%M")
    prev = load_prev()

    print("スクレイピング開始...")
    categories = scrape(prev)

    output = {"updated": now, "categories": categories}

    os.makedirs("data", exist_ok=True)
    with open("data/ranking.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    total = sum(len(v) for v in categories.values())
    print(f"\n✅ 保存完了: data/ranking.json ({now}) 合計{total}件")

if __name__ == "__main__":
    main()
