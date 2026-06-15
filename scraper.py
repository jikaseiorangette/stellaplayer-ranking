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

def extract_cv_from_title(title):
    """タイトルから（CV：xxx）を抽出"""
    m = re.search(r'[（(]CV[：:]\s*([^）)]+)[）)]', title)
    return m.group(1).strip() if m else ""

def extract_items(raw_list, prev_cat):
    items = []
    for entry in (raw_list or []):
        p = entry.get("product") or {}

        # タイトル
        title_raw = p.get("name") or p.get("title") or ""

        # 声優：タイトルの（CV：xxx）から抽出
        cv = extract_cv_from_title(title_raw)

        # タイトルからCV表記を除去
        title = re.sub(r'\s*[（(]CV[：:][^）)]+[）)]\s*', '', title_raw).strip()

        # サークル
        circle = ""
        maker = p.get("maker") or p.get("circle") or p.get("brand") or {}
        if isinstance(maker, dict):
            circle = maker.get("name", "")
        elif isinstance(maker, str):
            circle = maker

        # サムネイル: converted_featured_images の 800x800_png を優先
        img = ""
        cfi = p.get("converted_featured_images") or {}
        if isinstance(cfi, dict):
            img = (cfi.get("800x800_png") or cfi.get("200x200_png") or
                   cfi.get("main") or next(iter(cfi.values()), ""))
        if not img:
            for key in ["thumbnailUrl","thumbnail","image","imageUrl","coverUrl","jacket"]:
                if p.get(key):
                    val = p[key]
                    img = val.get("url","") if isinstance(val,dict) else str(val)
                    if img: break

        # 発売日
        release = ""
        rs = p.get("release_schedule") or p.get("releaseDate") or p.get("publish_starts_at") or ""
        if rs:
            release = str(rs)[:10].replace(" ","T").split("T")[0]

        # タグ
        tags = []
        for key in ["tags","genres","genre","keywords"]:
            if p.get(key):
                val = p[key]
                if isinstance(val, list):
                    tags = [v.get("name",str(v)) if isinstance(v,dict) else str(v) for v in val]
                elif isinstance(val, str):
                    tags = [t.strip() for t in val.split(",")]
                if tags: break

        # リンク
        link = p.get("url") or p.get("link") or ""
        if link and not link.startswith("http"):
            link = "https://www.stellaplayer.jp" + link

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

    items.sort(key=lambda x: x["rank"])
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
                    # GIRLS/BL/GENERAL が含まれる応答を優先キャプチャ
                    for cat in ["GIRLS", "BL", "GENERAL"]:
                        if cat in data and data[cat] and cat not in captured:
                            captured[cat] = data[cat]
                            print(f"  📦 {cat}: {len(data[cat])}件キャプチャ")
            except Exception:
                pass

        page = context.new_page()
        page.on("response", handle_response)

        for cat_url, cat_key in [
            ("https://www.stellaplayer.jp/ranking/GIRLS?rank_type=DAILY", "GIRLS"),
            ("https://www.stellaplayer.jp/ranking/BL?rank_type=DAILY", "BL"),
        ]:
            if cat_key in captured:
                continue
            print(f"\n{cat_key}ページを開いています...")
            try:
                page.goto(cat_url, wait_until="networkidle", timeout=60000)
                page.wait_for_timeout(3000)
            except Exception as e:
                print(f"  ERROR: {e}")

        browser.close()

    for cat, raw in captured.items():
        prev_cat = prev.get(cat, {})
        results[cat] = extract_items(raw, prev_cat)
        print(f"  → {cat}: {len(results[cat])}件")
        for it in results[cat][:3]:
            print(f"    rank={it['rank']} title={it['title'][:25]} cv={it['cv']} circle={it['circle']} img={'あり' if it['img'] else 'なし'} date={it['release_date']}")

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
