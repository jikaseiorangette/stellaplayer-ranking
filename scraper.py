"""
ステラプレイヤー ランキングスクレイパー
- 毎日23:30 JST に自動実行
- ランキング取得 + 履歴蓄積 + 新着CSV自動更新
"""

import json, os, re, csv
from datetime import datetime, timezone, timedelta
from playwright.sync_api import sync_playwright

JST = timezone(timedelta(hours=9))

# ===== ユーティリティ =====

def load_prev_ranking(path="data/ranking.json"):
    """前回のランキングを読んでtitle→rankのマップを返す"""
    prev = {}
    if not os.path.exists(path):
        return prev
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

def load_history(path="data/history.json"):
    """ランク履歴を読み込む {cat: {product_id: [{date, rank}]}}"""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_history(history, path="data/history.json"):
    """履歴を保存（30日分のみ保持）"""
    cutoff = (datetime.now(JST) - timedelta(days=30)).strftime("%Y-%m-%d")
    for cat in history:
        for pid in history[cat]:
            history[cat][pid] = [
                h for h in history[cat][pid]
                if h.get("date","") >= cutoff
            ]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

def load_products_csv(path="data/products.csv"):
    """CSVをidキーの辞書で返す"""
    products = {}
    if not os.path.exists(path):
        print(f"  CSV未発見: {path}")
        return products
    with open(path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pid = str(row.get("id","")).strip()
            if pid:
                products[pid] = row
    print(f"  CSV読み込み: {len(products)}件")
    return products

def update_products_csv(new_items, path="data/products.csv"):
    """
    ①ランキング登場作品をCSVに追記
    ②ランキング登場＝配信済みなのでPREORDER→ON_SALEに自動更新
    """
    if not os.path.exists(path):
        return
    # ランキング登場作品のIDセット
    ranked_ids = {str(it.get("product_id","")) for it in new_items if it.get("product_id")}

    rows = []
    fieldnames = None
    added = 0
    updated = 0
    existing_ids = set()

    with open(path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        for row in reader:
            pid = str(row.get("id","")).strip()
            existing_ids.add(pid)
            # PREORDERがランキングに登場していたらON_SALEに更新
            if pid in ranked_ids and row.get("販売ステータス") == "PREORDER":
                row["販売ステータス"] = "ON_SALE"
                updated += 1
                print(f"  ステータス更新: {row.get('タイトル','')[:30]} PREORDER→ON_SALE")
            rows.append(row)

    # 新作を追記
    for it in new_items:
        pid = str(it.get("product_id",""))
        if pid and pid not in existing_ids:
            new_row = {k: "" for k in fieldnames}
            new_row["id"] = pid
            new_row["タイトル"] = it.get("title_raw","")
            new_row["ブランド"] = it.get("circle","")
            new_row["CV"] = it.get("cv","")
            new_row["発売日"] = it.get("release_date","")
            new_row["ジャンル"] = " / ".join(it.get("tags",[]))
            new_row["サムネイルURL"] = it.get("img","")
            new_row["販売ステータス"] = "ON_SALE"
            rows.append(new_row)
            existing_ids.add(pid)
            added += 1

    if added > 0 or updated > 0:
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        if added: print(f"  CSV追記: {added}件")
        if updated: print(f"  CSV更新: {updated}件(PREORDER→ON_SALE)")

# ===== スクレイピング =====

def extract_cv_from_title(title):
    m = re.search(r'[（(]CV[：:]\s*([^）)]+)[）)]', title)
    return m.group(1).strip() if m else ""

def fetch_ranking(page):
    return page.evaluate("""
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

def extract_items(raw_list, prev_cat, products_csv, today_str):
    items = []
    for entry in (raw_list or []):
        p = entry.get("product") or {}
        product_id = str(p.get("id") or "")
        csv_row = products_csv.get(product_id, {})

        title_raw = p.get("name") or csv_row.get("タイトル","") or ""
        cv_from_title = extract_cv_from_title(title_raw)
        title = re.sub(r'\s*[（(]CV[：:][^）)]+[）)]\s*', '', title_raw).strip()

        cv = csv_row.get("CV","").strip() or cv_from_title

        circle = csv_row.get("ブランド","").strip()
        if not circle:
            brand = p.get("brand") or {}
            circle = brand.get("name","") if isinstance(brand,dict) else ""

        img = csv_row.get("サムネイルURL","").strip()
        if not img:
            cfi = p.get("converted_featured_images") or {}
            if isinstance(cfi, dict):
                img = cfi.get("800x800_png") or cfi.get("200x200_png") or next(iter(cfi.values()),"")

        release = ""
        csv_date = csv_row.get("発売日","").strip()
        if csv_date:
            release = csv_date[:10]
        else:
            for key in ["release_schedule","publish_starts_at"]:
                if p.get(key):
                    release = str(p[key])[:10].split("T")[0].split(" ")[0]
                    break

        tags = []
        csv_genres = csv_row.get("ジャンル","").strip()
        if csv_genres:
            tags = [g.strip() for g in csv_genres.split("/") if g.strip()]
        else:
            genres_raw = p.get("genres") or []
            tags = [g.get("name","") for g in genres_raw if isinstance(g,dict) and g.get("name")]

        rank = int(entry.get("rank") or 0)
        link = f"https://www.stellaplayer.jp/product/{product_id}" if product_id else ""

        if title:
            items.append({
                "rank": rank,
                "title": title,
                "title_raw": title_raw,
                "circle": circle,
                "cv": cv,
                "img": img,
                "release_date": release,
                "tags": tags[:8],
                "link": link,
                "product_id": product_id,
                "prev_rank": prev_cat.get(title),
                "history": [],
            })

    items.sort(key=lambda x: x["rank"])
    return items

def update_history(history, cat, items, today_str):
    """今日のランクを履歴に追記"""
    if cat not in history:
        history[cat] = {}
    for it in items:
        pid = it.get("product_id","")
        if not pid:
            continue
        if pid not in history[cat]:
            history[cat][pid] = []
        # 同日が既にあれば上書き
        history[cat][pid] = [h for h in history[cat][pid] if h.get("date") != today_str]
        history[cat][pid].append({"date": today_str, "rank": it["rank"]})
        history[cat][pid].sort(key=lambda x: x["date"])
        # 作品のhistoryフィールドにも付与
        it["history"] = history[cat][pid]

# ===== メイン =====

def scrape(prev, products_csv, history, today_str):
    results = {}
    all_raw_items = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ))
        page = context.new_page()

        print("ランキングページを開いています...")
        page.goto("https://www.stellaplayer.jp/ranking/GIRLS?rank_type=DAILY",
                  wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(2000)

        print("GraphQL APIを呼び出しています...")
        api_result = fetch_ranking(page)
        browser.close()

    if not (api_result and "data" in api_result):
        print(f"  APIエラー: {json.dumps(api_result)[:300]}")
        return results

    data = api_result["data"]
    print(f"  取得カテゴリ: {list(data.keys())}")

    for cat in ["GIRLS", "BL"]:
        if cat not in data or not data[cat]:
            continue
        prev_cat = prev.get(cat, {})
        items = extract_items(data[cat], prev_cat, products_csv, today_str)

        # 履歴に今日のデータを追記
        update_history(history, cat, items, today_str)

        results[cat] = items
        all_raw_items.extend(items)
        print(f"  {cat}: {len(items)}件")
        for it in items[:3]:
            print(f"    rank={it['rank']} {it['title'][:25]} cv={it['cv']} tags={it['tags'][:3]} history={len(it['history'])}日分")

    # CSVに新作を追記
    update_products_csv(all_raw_items, "data/products.csv")

    return results

def main():
    now = datetime.now(JST)
    now_str = now.strftime("%Y/%m/%d %H:%M")
    today_str = now.strftime("%Y-%m-%d")

    prev = load_prev_ranking()
    products_csv = load_products_csv("data/products.csv")
    history = load_history()

    print(f"スクレイピング開始... ({today_str})")
    categories = scrape(prev, products_csv, history, today_str)

    # ranking.json 保存
    # 近日配信予定作品をCSVから抽出
    preorders = []
    for pid, row in products_csv.items():
        if row.get("販売ステータス") == "PREORDER":
            title_raw = row.get("タイトル","")
            import re as _re
            cv_m = _re.search(r"[（(]CV[：:]\s*([^）)]+)[）)]", title_raw)
            cv_name = cv_m.group(1).strip() if cv_m else row.get("CV","")
            title = _re.sub(r"\s*[（(]CV[：:][^）)]+[）)]\s*", "", title_raw).strip()
            tags = [g.strip() for g in row.get("ジャンル","").split("/") if g.strip()]
            preorders.append({
                "id": pid,
                "title": title,
                "circle": row.get("ブランド",""),
                "cv": cv_name,
                "release_date": row.get("発売日","")[:10],
                "streaming_date": row.get("配信開始日","")[:10],
                "tags": tags[:8],
                "img": row.get("サムネイルURL",""),
                "link": f"https://www.stellaplayer.jp/product/{pid}",
                "has_bonus": row.get("オリジナル特典","") == "True",
            })
    preorders.sort(key=lambda x: x["release_date"])
    # 2026年発売・配信済み作品数を集計
    count_2026 = sum(
        1 for row in products_csv.values()
        if row.get("販売ステータス") == "ON_SALE"
        and str(row.get("発売日","")).startswith("2026")
    )
    output = {"updated": now_str, "total_products": count_2026, "preorders": preorders, "categories": categories}
    os.makedirs("data", exist_ok=True)
    with open("data/ranking.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # history.json 保存（30日分）
    save_history(history)

    total = sum(len(v) for v in categories.values())
    print(f"\n✅ 保存完了: ranking.json ({now_str}) 合計{total}件")
    print(f"✅ history.json 更新完了")

if __name__ == "__main__":
    main()
