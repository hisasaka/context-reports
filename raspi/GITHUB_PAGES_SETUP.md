# GitHub Pages セットアップ手順

コンテキスト収集レポートをGitHub Pagesで公開し、スマホから閲覧できるようにする手順です。

---

## 事前準備

### 1. GitHubリポジトリの作成

1. GitHub (https://github.com) にログイン
2. 右上の「+」→「New repository」
3. 設定:
   - Repository name: `context-reports`
   - Visibility: **Private**（推奨）または Public
   - 他の設定はデフォルトのまま（READMEの追加は不要）
4. 「Create repository」をクリック

### 2. GitHub認証の設定（Pi上で実行）

#### 方法A: Personal Access Token（HTTPS方式・簡単）

1. GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)
2. 「Generate new token (classic)」
3. スコープ: `repo` にチェック
4. 有効期限: お好みで（No expiration も可能）
5. トークンを控えておく

リモートURLにトークンを埋め込む:
```bash
git remote set-url origin https://<TOKEN>@github.com/<username>/context-reports.git
```

#### 方法B: SSH鍵（SSH方式）

```bash
# Pi上で鍵を生成
ssh-keygen -t ed25519 -C "context-bot@pi"
# → /home/hisasaka0513/.ssh/id_ed25519 に保存

# 公開鍵を表示
cat ~/.ssh/id_ed25519.pub
```

1. GitHub → Settings → SSH and GPG keys → New SSH key
2. 表示された公開鍵を貼り付けて保存

---

## セットアップ実行

Pi にSSH接続して実行:

```bash
cd /home/hisasaka0513/context

# セットアップスクリプトを実行
bash setup_github_pages.sh https://github.com/<username>/context-reports.git
# SSH方式の場合:
# bash setup_github_pages.sh git@github.com:<username>/context-reports.git
```

---

## GitHub Pages の有効化

1. GitHub でリポジトリ (`context-reports`) を開く
2. **Settings** タブ → サイドバーの **Pages**
3. Source: **Deploy from a branch**
4. Branch: **main** / Folder: **/docs**
5. **Save** をクリック

数分後にサイトが利用可能になります:
```
https://<username>.github.io/context-reports/
```

---

## 初回デプロイ

```bash
cd /home/hisasaka0513/context

# 既存レポートを全てデプロイ
python3 publish_to_github.py
```

サイトにアクセスして確認:
- PC: `https://<username>.github.io/context-reports/`
- スマホ: 同じURLをブラウザで開く（ブックマーク推奨）

---

## cron 設定（自動デプロイ）

```bash
crontab -e
```

既存の行を以下に変更:
```
0 8 * * * cd /home/hisasaka0513/context && /usr/bin/python3 context_collector.py >> cron.log 2>&1 && /usr/bin/python3 publish_to_github.py >> deploy.log 2>&1
```

これにより、毎朝8時に:
1. ニュースを収集
2. 自動でGitHub Pagesにデプロイ

---

## スクリプトのオプション

```bash
# 通常デプロイ（コピー＋インデックス生成＋push）
python3 publish_to_github.py

# ローカルのみ（git push しない、テスト用）
python3 publish_to_github.py --local

# ドライラン（何が起きるかだけ表示）
python3 publish_to_github.py --dry-run

# 詳細ログ
python3 publish_to_github.py --verbose
```

---

## トラブルシューティング

### プッシュが失敗する
```bash
# 認証を確認
git remote -v

# トークンが正しいか確認（HTTPS方式の場合）
git remote set-url origin https://<新しいTOKEN>@github.com/<username>/context-reports.git
```

### サイトが表示されない
- GitHub Pages の設定を確認（Settings > Pages）
- ブランチとフォルダが正しいか確認（main / /docs）
- デプロイ完了まで数分かかることがあります

### レポートが更新されない
```bash
# deploy.log を確認
cat deploy.log

# 手動で再デプロイ
python3 publish_to_github.py --verbose
```
