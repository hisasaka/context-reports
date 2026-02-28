#!/usr/bin/env python3
"""
GitHub Pages デプロイスクリプト
収集レポートをGitHub Pagesに自動パブリッシュする

Usage:
    python3 publish_to_github.py           # 通常デプロイ（コピー＋インデックス生成＋push）
    python3 publish_to_github.py --local   # ローカルのみ（git push しない）
    python3 publish_to_github.py --dry-run # 変更なし、何が起きるかだけ表示
"""

import os
import sys
import subprocess
import logging
import re
import argparse
from pathlib import Path
from datetime import datetime

# --- Configuration ---
BASE_DIR = Path(__file__).parent
REPORTS_DIR = BASE_DIR / "reports"
DOCS_DIR = BASE_DIR / "docs"

logger = logging.getLogger(__name__)

# --- レポートのコピー ---

def copy_reports_to_docs(dry_run=False):
    """reports/ のHTMLレポートを docs/ にASCII名でコピー"""
    if not dry_run:
        DOCS_DIR.mkdir(exist_ok=True)

    copied = 0
    pattern = re.compile(r'^レポート-(\d{4}-\d{2}-\d{2})\.html$')

    for report_file in sorted(REPORTS_DIR.glob("レポート-*.html")):
        match = pattern.match(report_file.name)
        if not match:
            continue

        date_str = match.group(1)
        dest_name = f"report-{date_str}.html"
        dest_path = DOCS_DIR / dest_name

        # 同じサイズなら既にコピー済みとしてスキップ
        if dest_path.exists():
            src_size = report_file.stat().st_size
            dst_size = dest_path.stat().st_size
            # ナビリンク注入で若干サイズ変わるので、元ファイルより大きければOK
            if dst_size > src_size:
                continue

        if dry_run:
            logger.info(f"  [DRY-RUN] コピー予定: {report_file.name} -> {dest_name}")
            copied += 1
            continue

        # HTMLを読み込んでナビリンクを注入
        html_content = report_file.read_text(encoding='utf-8')
        html_content = inject_nav_link(html_content)
        dest_path.write_text(html_content, encoding='utf-8')
        copied += 1
        logger.info(f"  コピー: {report_file.name} -> {dest_name}")

    return copied


def inject_nav_link(html_content):
    """レポートHTMLにインデックスへの戻りリンクを追加"""
    # 既に注入済みの場合はスキップ
    if 'レポート一覧に戻る' in html_content:
        return html_content

    nav_html = '''<div style="max-width:1000px;margin:10px auto;padding:0 20px;">
    <a href="index.html" style="color:#0078d4;text-decoration:none;font-size:0.9em;">
        &#8592; レポート一覧に戻る
    </a>
</div>'''

    return html_content.replace('<body>', f'<body>\n{nav_html}', 1)


# --- インデックスページ生成 ---

def generate_index_page(dry_run=False):
    """全レポートの一覧インデックスページを生成"""
    reports = []

    for html_file in sorted(DOCS_DIR.glob("report-*.html"), reverse=True):
        date_str = html_file.stem.replace("report-", "")

        # レポートHTMLから記事件数を抽出
        content = html_file.read_text(encoding='utf-8')
        count_match = re.search(r'総件数:</strong>\s*(\d+)件', content)
        article_count = count_match.group(1) if count_match else "?"

        # 日付表示を整形
        try:
            date_obj = datetime.strptime(date_str, "%Y-%m-%d")
            weekdays = ["月", "火", "水", "木", "金", "土", "日"]
            display_date = date_obj.strftime("%Y年%m月%d日") + f" ({weekdays[date_obj.weekday()]})"
        except ValueError:
            display_date = date_str

        reports.append({
            "filename": html_file.name,
            "date_str": date_str,
            "display_date": display_date,
            "article_count": article_count,
        })

    if dry_run:
        logger.info(f"  [DRY-RUN] インデックス生成予定: {len(reports)}件のレポート")
        return

    index_html = build_index_html(reports)
    (DOCS_DIR / "index.html").write_text(index_html, encoding='utf-8')
    logger.info(f"  インデックス生成: {len(reports)}件のレポート")


def build_index_html(reports):
    """ブログ風インデックスHTMLを構築"""

    # レポートカードを生成
    report_items = ""
    for r in reports:
        report_items += f'''
        <a href="{r['filename']}" class="report-card">
            <div class="report-date">{r['display_date']}</div>
            <div class="report-meta">{r['article_count']}件の記事を収集</div>
        </a>'''

    # 日付範囲
    if reports:
        newest = reports[0]['date_str']
        oldest = reports[-1]['date_str']
        date_range = f"{oldest} ～ {newest}"
    else:
        date_range = "-"

    now_str = datetime.now().strftime('%Y-%m-%d %H:%M')

    return f'''<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>コンテキスト収集レポート</title>
    <style>
        * {{ box-sizing: border-box; }}
        body {{
            font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, 'Hiragino Sans', 'Yu Gothic UI', sans-serif;
            margin: 0; padding: 0;
            background-color: #f4f7f9;
            color: #333;
        }}
        .container {{
            max-width: 800px;
            margin: 20px auto;
            padding: 20px;
            background-color: #fff;
            box-shadow: 0 4px 12px rgba(0,0,0,0.1);
            border-radius: 8px;
        }}
        header {{
            border-bottom: 3px solid #0078d4;
            padding-bottom: 12px;
            margin-bottom: 20px;
        }}
        header h1 {{
            color: #0078d4;
            font-size: 1.6em;
            margin: 0 0 4px 0;
        }}
        .header-meta {{
            color: #666;
            font-size: 0.9em;
        }}
        .report-card {{
            display: block;
            text-decoration: none;
            color: inherit;
            padding: 14px 16px;
            margin-bottom: 8px;
            border: 1px solid #e8e8e8;
            border-radius: 6px;
            background-color: #fafafa;
            transition: background-color 0.2s, border-color 0.2s, transform 0.1s;
        }}
        .report-card:hover {{
            background-color: #e9f4ff;
            border-color: #0078d4;
            transform: translateX(4px);
        }}
        .report-card:active {{
            transform: translateX(2px);
            background-color: #d4ecff;
        }}
        .report-date {{
            font-size: 1.05em;
            font-weight: 600;
            color: #005a99;
        }}
        .report-meta {{
            font-size: 0.85em;
            color: #666;
            margin-top: 3px;
        }}
        footer {{
            text-align: center;
            font-size: 0.8em;
            color: #999;
            margin-top: 24px;
            padding-top: 12px;
            border-top: 1px solid #eee;
        }}
        @media (max-width: 600px) {{
            .container {{
                margin: 10px;
                padding: 14px;
            }}
            header h1 {{
                font-size: 1.3em;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>コンテキスト収集レポート</h1>
            <div class="header-meta">
                {len(reports)}件のレポート ({date_range})
            </div>
        </header>
        {report_items}
        <footer>
            最終更新: {now_str}
        </footer>
    </div>
</body>
</html>'''


# --- Git 操作 ---

def git_push():
    """docs/ の変更を GitHub にプッシュ"""

    def run_git(*args):
        result = subprocess.run(
            ["git"] + list(args),
            cwd=str(BASE_DIR),
            capture_output=True, text=True, timeout=120
        )
        if result.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
        return result.stdout.strip()

    # docs/ のみステージング
    run_git("add", "docs/")

    # 変更があるか確認
    status = run_git("diff", "--cached", "--name-only")
    if not status:
        logger.info("  変更なし - プッシュをスキップ")
        return False

    # コミット
    today = datetime.now().strftime("%Y-%m-%d")
    run_git("commit", "-m", f"Update reports: {today}")

    # プッシュ
    run_git("push", "origin", "main")
    logger.info("  GitHub にプッシュ完了")
    return True


# --- メイン ---

def main():
    parser = argparse.ArgumentParser(description='GitHub Pages デプロイスクリプト')
    parser.add_argument('--local', action='store_true', help='ローカルのみ（git push しない）')
    parser.add_argument('--dry-run', action='store_true', help='実際には何もしない')
    parser.add_argument('--verbose', action='store_true', help='詳細ログ')
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format='[%(asctime)s] %(message)s',
        datefmt='%H:%M:%S'
    )

    logger.info("=== GitHub Pages デプロイ開始 ===")

    if not REPORTS_DIR.exists():
        logger.error(f"reports/ ディレクトリが見つかりません: {REPORTS_DIR}")
        sys.exit(1)

    # Step 1: レポートをコピー
    logger.info("レポートを docs/ にコピー中...")
    copied = copy_reports_to_docs(dry_run=args.dry_run)
    logger.info(f"  {copied}件の新規/更新レポートをコピー")

    # Step 2: インデックス生成
    logger.info("インデックスページを生成中...")
    generate_index_page(dry_run=args.dry_run)

    if args.dry_run:
        logger.info("=== DRY-RUN 完了 ===")
        return

    # Step 3: Git push
    if args.local:
        logger.info("--local モード: git push をスキップ")
        logger.info("=== ローカルデプロイ完了 ===")
        return

    logger.info("GitHub にプッシュ中...")
    try:
        pushed = git_push()
        if pushed:
            logger.info("=== デプロイ完了 ===")
        else:
            logger.info("=== 変更なし（スキップ）===")
    except Exception as e:
        logger.error(f"デプロイ失敗: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
