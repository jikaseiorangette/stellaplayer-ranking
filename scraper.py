"""
ステラプレイヤー ランキングスクレイパー
GraphQLレスポンスをインターセプトして全フィールド取得
"""

import json, os, re
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

def extract_items(raw_list, prev_cat):
    items = []
    for entry in (raw_list or []):
        p = entry.get("product") or {}

        # タイトル
        title = ""
        for key in ["name","title","workTitle","productName"]:
            if p.get(key):
                title = p[key]; break

        # サークル
        circle = ""
        for key in ["circle","maker","brand","label","makerName"]:
            if p.get(key):
                val = p[key]
                circle = val.get("name","") if isinstance(val,dict) else str(val)
                if circle: break

        # 声優
        cv = ""
        for key in ["cv","cast","voice","voiceActor","castName"]:
            if p.get(key):
                val = p[key]
                if isinstance(val, list):
                    cv = "、".join([v.get("name",str(v)) if isinstance(v,dict) else str(v) for v in val])
                elif isinstance(val, dict):
                    cv = val.get("name","")
                else:
                    cv = str(val)
                if cv: break

        # サムネイル
        img = ""
        for key in ["thumbnailUrl","thumbnail","image","imageUrl","coverUrl","img","jacket"]:
            if p.get(key):
                val = p[key]
                img = val.get("url","") if isinstance(val,dict) else str(val)
                if img: break

        # 発売日
        release = ""
        for key in ["releaseDate","release_date","date","publishedAt","releasedAt"]:
            if p.get(key):
                release = str(p[key])[:10]; break

        # タグ
        tags = []
        for key in ["tags","genres","genre","keywords","keyword"]:
            if p.get(key):
                val = p[key]
                if isinstance(val, list):
                    tags = [v.get("name",str(v)) if isinstance(v,dict) else str(v) for v in val]
                elif isinstance(val, str):
                    tags = [t.strip() for t in val.split(",")]
                if tags: break

        # リンク
        link = ""
        for key in ["url","link","productUrl","detailUrl"]:
            if p.get(key):
                link = str(p[key])
                if not link.startswith("http"):
                    link = "https://www.stellaplayer.jp" + link
                break

        rank = int(entry.get("rank") or 0)

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
                "history": [],
            })

    # デバッグ：最初の1件を詳細出力
    if raw_list:
        print(f"  サンプルデータ: {json.dumps(raw_list[0], ensure_ascii=False)[:500]}")

    return items

def scrape(prev):
    results = {}
    captured = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ))

        def handle_response(response):
            try:
                if "graphql" in response.url and response.status == 200:
                    body = response.json()
                    data = body.get("data", {})
                    print(f"  GraphQL応答キー: {list(data.keys())}")
                    for cat in ["GIRLS", "BL", "GENERAL", "girls", "bl"]:
                        if cat in data and data[cat]:
                            key = cat.upper()
                            if key not in captured:
                                captured[key] = data[cat]
                                print(f"  📦 {key}: {len(data[cat])}件")
            except Exception as e:
                print(f"  handle_response error: {e}")

        page = context.new_page()
        page.on("response", handle_response)

        # DAILY（24時間）ランキングを取得
        for cat_url, cat_key in [
            ("https://www.stellaplayer.jp/ranking/GIRLS?rank_type=DAILY", "GIRLS"),
            ("https://www.stellaplayer.jp/ranking/BL?rank_type=DAILY", "BL"),
        ]:
            print(f"\n{cat_key}ページを開いています...")
            try:
                page.goto(cat_url, wait_until="networkidle", timeout=60000)
                page.wait_for_timeout(4000)
                # ランキング切替ボタンをクリック（24時間）
                try:
                    btn = page.query_selector("button:has-text('24時間'), [data-value='DAILY'], button:has-text('DAILY')")
                    if btn:
                        btn.click()
                        page.wait_for_timeout(2000)
                        print(f"  24時間ボタンをクリック")
                except:
                    pass
            except Exception as e:
                print(f"  ERROR: {e}")

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
    categories = scrape(prev)

    output = {"updated": now, "categories": categories}

    os.makedirs("data", exist_ok=True)
    with open("data/ranking.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    total = sum(len(v) for v in categories.values())
    print(f"\n✅ 保存完了: data/ranking.json ({now}) 合計{total}件")

    # データ確認
    for cat, items in categories.items():
        print(f"\n=== {cat} TOP3 ===")
        for it in items[:3]:
            print(f"  rank={it['rank']} title={it['title'][:30]} cv={it['cv']} img={it['img'][:50] if it['img'] else 'なし'}")

if __name__ == "__main__":
    main()
