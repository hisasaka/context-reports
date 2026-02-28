#!/bin/bash
# ==============================================
# GitHub Pages 初期セットアップスクリプト
# ==============================================
# Usage: bash setup_github_pages.sh <github-repo-url>
#
# 例:
#   bash setup_github_pages.sh https://github.com/hisasaka0513/context-reports.git
#   bash setup_github_pages.sh git@github.com:hisasaka0513/context-reports.git

set -e

REPO_URL="${1:?Usage: bash setup_github_pages.sh <github-repo-url>}"
CONTEXT_DIR="/home/hisasaka0513/context"

echo "=== GitHub Pages セットアップ ==="
echo "リポジトリ: $REPO_URL"
echo "作業ディレクトリ: $CONTEXT_DIR"
echo ""

cd "$CONTEXT_DIR"

# git がなければインストール
if ! command -v git &> /dev/null; then
    echo "git をインストール中..."
    sudo apt update && sudo apt install -y git
fi

# git リポジトリを初期化（既にあればスキップ）
if [ ! -d ".git" ]; then
    echo "git リポジトリを初期化中..."
    git init
    git branch -M main
else
    echo "既存の git リポジトリを検出"
fi

# .gitignore を作成
echo ".gitignore を作成中..."
cat > .gitignore << 'GITIGNORE'
# データファイル（サイズが大きい / 再生成可能）
outputs/
database.sqlite
__pycache__/
*.pyc
*.log

# レポート原本（docs/ にコピーして公開）
reports/

# 設定ファイル（APIキーを含む）
config.json

# その他
templates/
*.sqlite
nul
GITIGNORE

# docs/ ディレクトリを作成
mkdir -p docs

# remote を設定
git remote remove origin 2>/dev/null || true
git remote add origin "$REPO_URL"

# git ユーザー設定（未設定の場合のみ）
if [ -z "$(git config user.name)" ]; then
    git config user.name "Context Collector Bot"
    git config user.email "context-bot@localhost"
fi

# 初回コミット
echo "初回コミットを作成中..."
git add .gitignore publish_to_github.py setup_github_pages.sh GITHUB_PAGES_SETUP.md docs/
git commit -m "Initial setup for GitHub Pages" || echo "コミットなし（変更がないか既にコミット済み）"

# プッシュ
echo "GitHub にプッシュ中..."
git push -u origin main

echo ""
echo "========================================="
echo "  セットアップ完了!"
echo "========================================="
echo ""
echo "次のステップ:"
echo ""
echo "1. GitHub で以下の設定を行ってください:"
echo "   リポジトリ > Settings > Pages"
echo "   Source: Deploy from a branch"
echo "   Branch: main"
echo "   Folder: /docs"
echo ""
echo "2. テスト実行:"
echo "   python3 publish_to_github.py"
echo ""
echo "3. crontab を更新:"
echo "   crontab -e"
echo "   以下のように変更:"
echo '   0 8 * * * cd /home/hisasaka0513/context && /usr/bin/python3 context_collector.py >> cron.log 2>&1 && /usr/bin/python3 publish_to_github.py >> deploy.log 2>&1'
echo ""
echo "4. サイトURL (数分後にアクセス可能):"
echo "   https://<username>.github.io/context-reports/"
echo ""
