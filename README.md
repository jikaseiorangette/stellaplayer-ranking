# ステラプレイヤー ランキング分析

毎日自動でステラプレイヤーのランキングを取得し、静的サイトとして表示します。

## 仕組み

```
GitHub Actions (毎日 23:30 JST)
  └─ scraper.py 実行
       └─ data/ranking.json に保存 & コミット
            └─ index.html が読み込んで表示
```

---

## セットアップ手順

### 1. このリポジトリをGitHubにプッシュ

```bash
cd stellaplayer-ranking
git init
git add .
git commit -m "first commit"
git branch -M main
git remote add origin https://github.com/あなたのユーザー名/stellaplayer-ranking.git
git push -u origin main
```

### 2. GitHub Pages を有効化

GitHubリポジトリ → Settings → Pages →  
Source: **Deploy from a branch** → Branch: **main** / **/ (root)** → Save

数分後に `https://あなたのユーザー名.github.io/stellaplayer-ranking/` で公開されます。

### 3. Actions の書き込み権限を付与

GitHubリポジトリ → Settings → Actions → General →  
Workflow permissions: **Read and write permissions** にチェック → Save

### 4. 初回データ取得（手動実行）

GitHubリポジトリ → Actions → **Daily Ranking Scrape** → **Run workflow**

成功すると `data/ranking.json` が生成され、サイトにランキングが表示されます。

以降は毎日 23:30 JST に自動実行されます。

---

## ローカルでテスト実行

```bash
pip install -r requirements.txt
playwright install chromium
python scraper.py
# → data/ranking.json が生成される
```

ブラウザで `index.html` を開いて確認（ローカルはCORSのためサーバー経由推奨）:

```bash
python -m http.server 8000
# → http://localhost:8000 を開く
```
