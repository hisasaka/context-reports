# コンテキスト収集システム - 技術仕様書

## 目次
1. [システムアーキテクチャ](#システムアーキテクチャ)
2. [モジュール構成](#モジュール構成)
3. [データベース設計](#データベース設計)
4. [API仕様](#api仕様)
5. [開発環境](#開発環境)

---

## システムアーキテクチャ

### 概要

本システムは、Pythonで実装されたニュース記事収集・管理・AI下書き生成システムです。

### システム構成図

```
┌─────────────────────────────────────────────────────────┐
│                    コンテキスト収集システム                │
├─────────────────────────────────────────────────────────┤
│                                                           │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐        │
│  │ DuckDuckGo │  │Google News │  │  Reddit    │        │
│  │   検索     │  │   RSS      │  │   API      │        │
│  └─────┬──────┘  └─────┬──────┘  └─────┬──────┘        │
│        │                │                │               │
│        └────────────────┼────────────────┘               │
│                         ↓                                │
│              ┌──────────────────────┐                    │
│              │  ContentCollector    │                    │
│              │  ・記事収集          │                    │
│              │  ・重複排除          │                    │
│              │  ・データ整形        │                    │
│              └──────────┬───────────┘                    │
│                         ↓                                │
│         ┌───────────────┴──────────────┐                 │
│         ↓                              ↓                 │
│  ┌──────────────┐            ┌─────────────────┐        │
│  │ Markdown生成 │            │ データベース保存│        │
│  │  outputs/    │            │ database.sqlite │        │
│  └──────┬───────┘            └────────┬────────┘        │
│         ↓                             ↓                  │
│  ┌──────────────┐            ┌─────────────────┐        │
│  │ HTML統合変換 │            │   Flask Web UI  │        │
│  │  reports/    │            │  (localhost:5000)│        │
│  └──────────────┘            └────────┬────────┘        │
│                                       ↓                  │
│                              ┌─────────────────┐         │
│                              │  Gemini API     │         │
│                              │  AI下書き生成   │         │
│                              └─────────────────┘         │
└─────────────────────────────────────────────────────────┘
```

---

## モジュール構成

### 1. Config（設定管理）

**ファイル**: Context.py (31-60行目)

**責務**:
- config.jsonの読み書き
- デフォルト設定の管理
- 設定値のバリデーション

**主要メソッド**:
```python
load_config() -> dict       # 設定ファイルを読み込み
save_config()               # 設定ファイルを保存
```

**設定項目**:
| フィールド | 型 | 説明 |
|-----------|-----|------|
| keywords | List[str] | 収集キーワードリスト |
| check_interval_hours | int | 収集間隔（時間） |
| language | str | 収集言語（ja/en/ja,en） |
| initial_days | int | 初回収集の過去日数 |
| auto_start | bool | 自動起動フラグ |
| last_check | Dict[str, str] | キーワード別最終チェック日時 |
| gemini_api_key | str | Gemini APIキー |
| ai_enabled | bool | AI機能有効化フラグ |

---

### 2. ContentCollector（コンテンツ収集）

**ファイル**: Context.py (62-399行目)

**責務**:
- 複数ソースからの記事収集
- 重複記事の検出・排除
- 日付フィルタリング

**主要メソッド**:
```python
search_duckduckgo(keyword, days, lang) -> List[Dict]
    # DuckDuckGo HTML検索

search_google_news(keyword, days, lang) -> List[Dict]
    # Google News RSS検索

search_reddit(keyword, days) -> List[Dict]
    # Reddit JSON API検索

collect_all(keyword, days, languages) -> List[Dict]
    # 全ソースから収集して統合

load_historical_urls(keyword, lookback_days)
    # 過去N日分の既存URLを読み込み（重複排除用）
```

**記事データ構造**:
```python
{
    'title': str,           # 記事タイトル
    'url': str,             # 記事URL
    'snippet': str,         # 記事要約
    'source': str,          # ソース名（DuckDuckGo/Google News/Reddit）
    'date': str             # 公開日（YYYY-MM-DD形式）
}
```

**重複排除ロジック**:
1. セッション内重複: `collected_urls` セットで管理
2. 履歴重複: 過去7日分のMarkdownファイルからURLを抽出
3. DuckDuckGoリダイレクトURL: `uddg=`パラメータから実URLを抽出

---

### 3. MarkdownGenerator（Markdown生成）

**ファイル**: Context.py (401-436行目)

**責務**:
- 収集結果をMarkdown形式で整形
- ソース別に分類して出力

**主要メソッド**:
```python
generate(keyword, results, collection_date) -> str
    # Markdownドキュメント生成
```

**出力形式**:
```markdown
# {キーワード} - 収集結果

**収集日時**: {日時}
**収集件数**: {件数}件

---

## {ソース名} ({件数}件)

### 1. {記事タイトル}

- **URL**: {URL}
- **日付**: {日付}
- **概要**: {スニペット}

---
```

---

### 4. HTMLConverter（HTML変換・統合）

**ファイル**: Context.py (438-905行目)

**責務**:
- Markdownファイルの解析
- 同一日付のレポート統合
- URL・タイトル重複排除
- HTML生成

**主要メソッド**:
```python
convert_markdown_to_html(input_dir, output_dir, today_only, log_func)
    # Markdown → HTML変換（メインエントリポイント）

parse_markdown_report(lines) -> Dict
    # Markdownレポートをパース

merge_reports_by_date(files_by_date, log_func) -> Dict[str, Dict]
    # 同じ日付のレポートを統合

normalize_url(url) -> str
    # URLを正規化（重複判定用）

calculate_title_similarity(title1, title2) -> float
    # タイトルの類似度を計算（0.0〜1.0）
```

**重複排除アルゴリズム**:

1. **URL重複**: 正規化したURLで完全一致
   ```python
   normalized_url = url.rstrip('/').lower()
   if '?' in url:
       normalized_url = normalized_url.split('?')[0]
   ```

2. **タイトル類似度**: SequenceMatcher（類似度 ≥ 0.80）
   - 小文字化
   - 記号・空白の統一
   - 括弧類の削除
   - サイト名の除去

3. **重複時の処理**:
   - キーワード情報を統合
   - 最初に見つかった記事を保持

---

### 5. ArticleDB（データベース管理）

**ファイル**: Context.py (907-1067行目)

**責務**:
- SQLiteデータベースの管理
- 記事のCRUD操作
- 検索機能

**主要メソッド**:
```python
initialize_db()
    # データベース初期化・テーブル作成

add_article(url, title, snippet, content, ...) -> int
    # 記事追加（重複時は既存IDを返す）

get_article(article_id) -> Optional[Dict]
    # 記事取得

get_all_articles(status, limit) -> List[Dict]
    # 記事一覧取得

update_article(article_id, **kwargs)
    # 記事更新

delete_article(article_id)
    # 記事削除

search_articles(keyword) -> List[Dict]
    # キーワード検索
```

---

### 6. AIGenerator（AI下書き生成）

**ファイル**: Context.py (1070-1155行目)

**責務**:
- Gemini APIとの通信
- プロンプト生成
- 下書き生成

**主要メソッド**:
```python
__init__(api_key)
    # Gemini API初期化

generate_draft(article_data) -> str
    # 記事データから下書き生成

_build_prompt(article_data) -> str
    # プロンプト構築
```

**使用モデル**: `gemini-2.0-flash-exp`

**プロンプト構成**:
```
あなたはニュース記事を深く分析し、独自の視点で解説・感想を書くライターです。

以下の記事について、NOTE用の下書きを作成してください：

**記事タイトル**: {title}
**URL**: {url}
**記事内容**: {content[:3000]}

---

以下の構成で、深い分析と個人的な意見を含む文章を書いてください：

1. 記事の要点（2-3文）
2. 深掘り分析（背景、文脈、影響）
3. 個人的な見解（独自の視点や批判的考察）
4. 今後の展望

出力形式:
- Markdown形式
- 見出しは ## を使用
- 参考リンクとして元記事URLを文末に記載
- 文体：です・ます調
- 文字数：800-1200字程度
```

---

### 7. Flask Web UI（Webインターフェース）

**ファイル**: Context.py (1158-1284行目)

**責務**:
- Webベースの記事管理UI
- REST API提供
- AI下書き生成インターフェース

**エンドポイント**:

| メソッド | パス | 説明 |
|---------|------|------|
| GET | `/` | 記事一覧ページ |
| GET | `/article/<id>` | 記事詳細・編集ページ |
| GET | `/api/article/<id>` | 記事取得API |
| PUT | `/api/article/<id>` | 記事更新API |
| DELETE | `/api/article/<id>` | 記事削除API |
| GET | `/api/search?q=<keyword>` | 記事検索API |
| POST | `/api/generate-draft/<id>` | AI下書き生成API |
| GET | `/status/<status>` | ステータス別記事一覧 |

**ポート**: 5000

---

### 8. ContextCollectorApp（メインアプリケーション）

**ファイル**: Context.py (1286-1813行目)

**責務**:
- アプリケーション全体の制御
- システムトレイアイコン管理
- 定期収集スケジューリング
- 設定UI提供

**主要メソッド**:
```python
__init__()
    # 初期化（DB、Flask、AI Generator）

collect_data()
    # データ収集処理

check_and_collect(is_startup)
    # 定期チェック＆収集

should_collect(keyword) -> bool
    # 収集が必要かを判定

run()
    # アプリケーション起動
```

**起動フロー**:
```
1. Config読み込み
2. データベース初期化
3. AI Generator初期化（ai_enabled=trueの場合）
4. Flask Webサーバー起動（別スレッド）
5. システムトレイアイコン作成
6. 起動時チェック実行
7. 定期チェックスレッド開始（1時間ごと）
8. トレイアイコン実行（メインループ）
```

**自動終了ロジック**:
- 起動時に収集不要（全て本日収集済み）の場合は自動終了
- `auto_exit_after_startup`フラグで制御

---

## データベース設計

### テーブル: articles

| カラム名 | 型 | 制約 | 説明 |
|---------|-----|------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 記事ID |
| url | TEXT | NOT NULL UNIQUE | 記事URL（一意） |
| normalized_url | TEXT | | 正規化URL（重複判定用） |
| title | TEXT | NOT NULL | 記事タイトル |
| snippet | TEXT | | スニペット（要約） |
| content | TEXT | | 本文 |
| author | TEXT | | 著者 |
| published_date | TEXT | | 公開日 |
| source | TEXT | | ソース名 |
| keywords | TEXT | | 関連キーワード（CSV） |
| status | TEXT | DEFAULT 'new' | ステータス |
| tags | TEXT | | タグ（CSV） |
| user_notes | TEXT | | ユーザーメモ |
| generated_draft | TEXT | | AI生成下書き |
| created_at | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | 作成日時 |
| updated_at | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | 更新日時 |

**インデックス**:
- `idx_url`: url（重複チェック高速化）
- `idx_status`: status（ステータス別取得高速化）
- `idx_created_at`: created_at DESC（新着順ソート高速化）

**ステータス値**:
- `new`: 新規収集（未確認）
- `edited`: ユーザーが編集済み
- `draft_generated`: AI下書き生成済み
- `published`: 投稿済み

---

## API仕様

### 1. 記事取得API

**エンドポイント**: `GET /api/article/<article_id>`

**レスポンス**:
```json
{
  "id": 123,
  "url": "https://example.com/article",
  "title": "記事タイトル",
  "snippet": "記事の要約...",
  "content": "本文...",
  "source": "DuckDuckGo",
  "keywords": "AI,人工知能",
  "status": "new",
  "published_date": "2026-01-16",
  "generated_draft": null,
  "created_at": "2026-01-16T22:42:31.123866",
  "updated_at": "2026-01-16T22:42:31.123866"
}
```

---

### 2. 記事更新API

**エンドポイント**: `PUT /api/article/<article_id>`

**リクエストボディ**:
```json
{
  "title": "更新後のタイトル",
  "content": "更新後の本文",
  "user_notes": "メモ",
  "tags": "AI,機械学習",
  "status": "edited"
}
```

**更新可能フィールド**:
- title
- snippet
- content
- user_notes
- tags
- status

**レスポンス**:
```json
{
  "success": true
}
```

---

### 3. AI下書き生成API

**エンドポイント**: `POST /api/generate-draft/<article_id>`

**処理フロー**:
1. 記事データをDBから取得
2. AIGenerator.generate_draft()を呼び出し
3. 生成された下書きをDBに保存
4. ステータスを`draft_generated`に更新

**レスポンス**:
```json
{
  "success": true,
  "draft": "## 記事の要点\n\n..."
}
```

**エラーレスポンス**:
```json
{
  "error": "AI APIキーが設定されていません。"
}
```

---

### 4. 検索API

**エンドポイント**: `GET /api/search?q=<keyword>`

**検索対象フィールド**:
- title
- content
- tags
- keywords

**レスポンス**:
```json
[
  {
    "id": 123,
    "title": "...",
    "url": "...",
    ...
  },
  ...
]
```

---

## 開発環境

### 必要なソフトウェア

| ソフトウェア | バージョン | 用途 |
|-------------|-----------|------|
| Python | 3.8以上 | メイン言語 |
| pip | 最新 | パッケージ管理 |

### 依存パッケージ

```
Flask==2.3.3
google-generativeai==0.3.2
requests==2.31.0
beautifulsoup4==4.12.2
lxml==4.9.3
markdown==3.4.4
pystray==0.19.4
Pillow==10.0.1
pywin32==306
winshell==0.6
```

### インストール方法

```bash
cd C:\Users\hisas\KAIHATU\コンテキスト
pip install -r requirements.txt
```

---

## ファイル構成

```
C:\Users\hisas\KAIHATU\コンテキスト\
├── Context.py                    # メインプログラム（1813行）
├── config.json                   # 設定ファイル
├── database.sqlite               # SQLiteデータベース
├── run_collection.bat            # 自動収集用バッチ
├── start_webui.bat               # Web UI起動用バッチ
├── USER_MANUAL.md                # ユーザーマニュアル
├── TECHNICAL_SPEC.md             # 技術仕様書（本文書）
├── outputs/                      # Markdown出力
│   └── {keyword}-{date}.md
├── reports/                      # HTML統合レポート
│   └── レポート-{date}.html
└── templates/                    # Flaskテンプレート（別途作成が必要）
    ├── article_list.html
    └── article_editor.html
```

---

## パフォーマンス

### 処理時間目安

| 処理 | 時間 | 備考 |
|------|------|------|
| キーワード1件の収集 | 5-10秒 | ソース数・結果数に依存 |
| 全キーワード収集（48件） | 4-8分 | ネットワーク速度に依存 |
| HTML変換 | 5-10秒 | ファイル数に依存 |
| AI下書き生成 | 3-10秒 | Gemini APIのレスポンス速度 |

### リソース使用量

| リソース | 使用量 |
|---------|--------|
| メモリ | 100-200MB |
| ディスク（1日分） | 1-5MB（Markdown + HTML） |
| ディスク（データベース） | 成長率 約1MB/日 |

---

## セキュリティ考慮事項

### 1. APIキーの管理
- config.jsonに平文保存（注意: 機密情報）
- ファイルパーミッションの設定推奨
- Gitリポジトリからの除外必須

### 2. SQL Injection対策
- プレースホルダー使用（sqlite3のパラメータバインディング）
- ユーザー入力の直接SQL埋め込みなし

### 3. XSS対策
- HTMLエスケープ処理
- Flaskテンプレートの自動エスケープ機能

---

## 今後の拡張案

### 1. UI改善
- Reactベースのモダンなフロントエンド
- リアルタイム更新（WebSocket）
- 記事のカテゴリ分類

### 2. 機能追加
- 複数のAIモデル対応（Claude、GPT-4など）
- スケジュール収集の細かい設定
- 記事の自動タグ付け
- 画像の自動ダウンロード

### 3. パフォーマンス改善
- 並列収集処理
- キャッシュ機構
- データベースインデックスの最適化

---

**作成日**: 2026-01-16
**バージョン**: 1.0
**作成者**: Claude AI
