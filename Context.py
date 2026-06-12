"""
コンテキスト収集プログラム (修正版)
特定キーワードの最新情報を自動収集してMarkdown形式で保存
"""

# Task Scheduler等の制限環境でもパッケージを確実に読み込む
import sys, os
_base = r"C:\Users\hisas\AppData\Roaming\Python\Python314\site-packages"
for _p in [_base,
           os.path.join(_base, "win32"),
           os.path.join(_base, "win32", "lib"),
           os.path.join(_base, "Pythonwin")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Windowsコンソール(CP932)でUnicode文字が含まれるタイトルをprintするとクラッシュする問題を回避
import io as _io
if hasattr(sys.stdout, 'buffer'):
    sys.stdout = _io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'buffer'):
    sys.stderr = _io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
import threading
import time
from typing import List, Dict, Set, Optional
import queue
import winshell
from win32com.client import Dispatch
import pystray
from PIL import Image, ImageDraw
import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)  # verify=False の警告を抑制
from bs4 import BeautifulSoup
import urllib.parse
import markdown
import re
from collections import defaultdict
from difflib import SequenceMatcher
import sqlite3
from flask import Flask, render_template, request, jsonify, redirect, url_for

class Config:
    """設定管理クラス"""
    def __init__(self):
        self.config_file = Path("config.json")
        self.default_config = {
            "keywords": [],
            "check_interval_hours": 24,
            "language": "ja",
            "initial_days": 14,
            "auto_start": False,
            "last_check": {},
            "gemini_api_key": "",  # Gemini API キー
            "ai_enabled": False  # AI機能を有効にするか
        }
        self.config = self.load_config()
    
    def load_config(self) -> dict:
        """設定を読み込む"""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    return {**self.default_config, **json.load(f)}
            except:
                return self.default_config.copy()
        return self.default_config.copy()
    
    def save_config(self):
        """設定を保存する"""
        with open(self.config_file, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, ensure_ascii=False, indent=2)

class ContentCollector:
    """コンテンツ収集クラス"""
    def __init__(self, output_dir: Path):
        self.session = requests.Session()
        self.session.verify = False  # Windows環境のSSL証明書エラー回避
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'ja,en-US;q=0.9,en;q=0.8',
        })
        self.collected_urls = set()
        self.output_dir = output_dir
        self.historical_urls = set()  # 過去に収集したURL

    def load_historical_urls(self, keyword: str, lookback_days: int = 7):
        """過去N日分の収集データから既存URLを読み込む"""
        self.historical_urls.clear()

        try:
            # キーワードのファイル名を安全化
            from pathlib import Path
            safe_keyword = self._sanitize_filename(keyword)

            # 過去N日分のファイルをチェック
            today = datetime.now().date()
            for i in range(lookback_days):
                check_date = today - timedelta(days=i)
                filename = f"{safe_keyword}-{check_date.strftime('%Y-%m-%d')}.md"
                filepath = self.output_dir / filename

                if filepath.exists():
                    try:
                        with open(filepath, 'r', encoding='utf-8') as f:
                            for line in f:
                                # URLの行を抽出（- **URL**: で始まる行）
                                if line.strip().startswith('- **URL**:'):
                                    url = line.split(':', 1)[-1].strip()
                                    # DuckDuckGoのリダイレクトURLから実URLを抽出
                                    if 'duckduckgo.com/l/?uddg=' in url:
                                        try:
                                            import re
                                            match = re.search(r'uddg=([^&]+)', url)
                                            if match:
                                                url = urllib.parse.unquote(match.group(1))
                                        except:
                                            pass
                                    self.historical_urls.add(url)
                    except Exception as e:
                        print(f"[DEBUG] ファイル読み込みエラー ({filename}): {e}")

            print(f"[DEBUG] 過去{lookback_days}日分の既存URL数: {len(self.historical_urls)}件")

        except Exception as e:
            print(f"[DEBUG] 履歴URL読み込みエラー: {e}")

    def _sanitize_filename(self, filename: str) -> str:
        """ファイル名として使用できない文字を除去"""
        invalid_chars = ['\\', '/', ':', '*', '?', '"', '<', '>', '|']
        for char in invalid_chars:
            filename = filename.replace(char, '_')
        return filename.strip('. ')

    def _is_duplicate_url(self, url: str) -> bool:
        """URLが重複しているかチェック"""
        # DuckDuckGoのリダイレクトURLから実URLを抽出
        clean_url = url
        if 'duckduckgo.com/l/?uddg=' in url:
            try:
                import re
                match = re.search(r'uddg=([^&]+)', url)
                if match:
                    clean_url = urllib.parse.unquote(match.group(1))
            except:
                pass

        return clean_url in self.historical_urls

    def _extract_date_from_text(self, text: str) -> str:
        """テキストから日付を抽出"""
        import re
        from datetime import timedelta

        try:
            # "X days ago" パターン
            match = re.search(r'(\d+)\s*(day|days|hour|hours)\s*ago', text, re.IGNORECASE)
            if match:
                amount = int(match.group(1))
                unit = match.group(2).lower()
                if 'day' in unit:
                    date = datetime.now() - timedelta(days=amount)
                else:  # hours
                    date = datetime.now() - timedelta(hours=amount)
                return date.strftime('%Y-%m-%d')

            # "Dec 27, 2025" パターン
            match = re.search(r'([A-Z][a-z]{2})\s+(\d{1,2}),?\s+(\d{4})', text)
            if match:
                month_str = match.group(1)
                day = match.group(2)
                year = match.group(3)
                date_obj = datetime.strptime(f"{month_str} {day} {year}", '%b %d %Y')
                return date_obj.strftime('%Y-%m-%d')

            # "2025-12-27" パターン
            match = re.search(r'(\d{4})-(\d{2})-(\d{2})', text)
            if match:
                return match.group(0)

            # "27/12/2025" パターン
            match = re.search(r'(\d{1,2})/(\d{1,2})/(\d{4})', text)
            if match:
                day, month, year = match.groups()
                return f"{year}-{month.zfill(2)}-{day.zfill(2)}"

        except Exception as e:
            print(f"[DEBUG] 日付抽出エラー: {e}")

        return None
    
    def search_duckduckgo(self, keyword: str, days: int = 1, lang: str = "ja") -> List[Dict]:
        """DuckDuckGo検索（HTMLスクレイピング）"""
        results = []
        try:
            # DuckDuckGoのHTML検索
            params = {
                'q': keyword,
                'kl': 'jp-jp' if lang == 'ja' else 'us-en',
                't': 'h_',
                'ia': 'web'
            }
            
            # 日付フィルタは手動で確認
            url = f"https://duckduckgo.com/html/?{urllib.parse.urlencode(params)}"
            
            print(f"[DEBUG] DuckDuckGo検索URL: {url}")
            
            response = self.session.get(url, timeout=10)
            print(f"[DEBUG] ステータスコード: {response.status_code}")
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # 検索結果を解析
            for result in soup.find_all('div', class_='result'):
                try:
                    title_elem = result.find('a', class_='result__a')
                    snippet_elem = result.find('a', class_='result__snippet')

                    if title_elem:
                        title = title_elem.get_text()
                        link = title_elem.get('href', '')
                        snippet = snippet_elem.get_text() if snippet_elem else ""

                        # 日付情報を抽出（result__url内のテキストから）
                        date_str = None
                        date_elem = result.find('span', class_='result__url')
                        if date_elem:
                            # 日付パターンを探す（例: "3 days ago", "Dec 27, 2025" など）
                            date_text = date_elem.get_text()
                            date_str = self._extract_date_from_text(date_text)

                        # 日付が取得できなければ今日の日付
                        if not date_str:
                            date_str = datetime.now().strftime('%Y-%m-%d')

                        # 重複チェック（今回の収集内 + 過去の収集履歴）
                        if link and link not in self.collected_urls and not self._is_duplicate_url(link):
                            results.append({
                                'title': title,
                                'url': link,
                                'snippet': snippet,
                                'source': 'DuckDuckGo',
                                'date': date_str
                            })
                            self.collected_urls.add(link)
                            print(f"[DEBUG] 見つかった: {title[:50]}... (日付: {date_str})")
                        elif self._is_duplicate_url(link):
                            print(f"[DEBUG] スキップ（既存URL）: {title[:50]}...")
                except Exception as e:
                    print(f"[DEBUG] パースエラー: {e}")
                    continue
            
            print(f"[DEBUG] DuckDuckGo結果数: {len(results)}")
            time.sleep(2)
            
        except Exception as e:
            print(f"DuckDuckGo検索エラー: {e}")
            import traceback
            traceback.print_exc()
        
        return results
    
    def search_google_news(self, keyword: str, days: int = 1, lang: str = "ja") -> List[Dict]:
        """Googleニュース検索（RSS経由）"""
        results = []
        try:
            # Google NewsのRSSフィード
            params = {
                'q': keyword,
                'hl': lang,
                'gl': 'JP' if lang == 'ja' else 'US',
                'ceid': f'JP:{lang}' if lang == 'ja' else 'US:en'
            }
            
            url = f"https://news.google.com/rss/search?{urllib.parse.urlencode(params)}"
            
            print(f"[DEBUG] GoogleニュースRSS URL: {url}")
            
            response = self.session.get(url, timeout=10)
            print(f"[DEBUG] ステータスコード: {response.status_code}")
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'xml')
            
            items = soup.find_all('item')
            print(f"[DEBUG] 見つかったitem数: {len(items)}")
            
            for item in items[:20]:  # 最大20件
                try:
                    title = item.find('title').get_text() if item.find('title') else ""
                    link = item.find('link').get_text() if item.find('link') else ""
                    pub_date = item.find('pubDate').get_text() if item.find('pubDate') else ""

                    # 日付をパース
                    try:
                        date_obj = datetime.strptime(pub_date, '%a, %d %b %Y %H:%M:%S %Z')
                        date = date_obj.strftime('%Y-%m-%d')
                    except:
                        date_obj = None
                        date = datetime.now().strftime('%Y-%m-%d')

                    # 日付フィルタリング（過去N日以内の記事のみ）
                    if date_obj:
                        days_old = (datetime.now() - date_obj).days
                        if days_old > days or days_old < 0:  # 古すぎるか未来の日付
                            print(f"[DEBUG] スキップ（日付範囲外: {date}, {days_old}日前）: {title[:30]}...")
                            continue

                    # 重複チェック（今回の収集内 + 過去の収集履歴）
                    if link and link not in self.collected_urls and not self._is_duplicate_url(link):
                        results.append({
                            'title': title,
                            'url': link,
                            'snippet': '',
                            'source': 'Google News RSS',
                            'date': date
                        })
                        self.collected_urls.add(link)
                        print(f"[DEBUG] ニュース: {title[:30]}... (日付: {date})")
                    elif self._is_duplicate_url(link):
                        print(f"[DEBUG] スキップ（既存URL）: {title[:30]}...")
                except Exception as e:
                    print(f"[DEBUG] RSSパースエラー: {e}")
                    continue
            
            print(f"[DEBUG] ニュース結果数: {len(results)}")
            time.sleep(2)
            
        except Exception as e:
            print(f"GoogleニュースRSS検索エラー: {e}")
            import traceback
            traceback.print_exc()
        
        return results
    
    def search_reddit(self, keyword: str, days: int = 1) -> List[Dict]:
        """Reddit検索"""
        results = []
        try:
            # 期間指定
            if days == 1:
                time_filter = 'day'
            elif days <= 7:
                time_filter = 'week'
            else:
                time_filter = 'month'
            
            url = f"https://www.reddit.com/search.json"
            params = {
                'q': keyword,
                't': time_filter,
                'sort': 'relevance',
                'limit': 25
            }
            
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            
            for post in data.get('data', {}).get('children', []):
                try:
                    post_data = post['data']
                    title = post_data.get('title', '')
                    permalink = f"https://www.reddit.com{post_data.get('permalink', '')}"
                    selftext = post_data.get('selftext', '')
                    created = datetime.fromtimestamp(post_data.get('created_utc', 0))

                    # 重複チェック（今回の収集内 + 過去の収集履歴）
                    if permalink not in self.collected_urls and not self._is_duplicate_url(permalink):
                        results.append({
                            'title': title,
                            'url': permalink,
                            'snippet': selftext[:200] if selftext else '',
                            'source': f"Reddit - r/{post_data.get('subreddit', 'unknown')}",
                            'date': created.strftime('%Y-%m-%d')
                        })
                        self.collected_urls.add(permalink)
                except:
                    continue
            
            time.sleep(2)
            
        except Exception as e:
            print(f"Reddit検索エラー: {e}")
        
        return results
    
    def collect_all(self, keyword: str, days: int = 1, languages: List[str] = ['ja']) -> List[Dict]:
        """すべてのソースから収集"""
        all_results = []
        self.collected_urls.clear()

        # 過去7日分の既存URLを読み込み（重複排除用）
        self.load_historical_urls(keyword, lookback_days=7)

        for lang in languages:
            # DuckDuckGo検索（ボット検知によりブロック中のためスキップ）
            # results = self.search_duckduckgo(keyword, days, lang)
            # all_results.extend(results)

            # Googleニュース（RSS）
            results = self.search_google_news(keyword, days, lang)
            all_results.extend(results)
        
        # Reddit (英語のみ)
        if 'en' in languages:
            results = self.search_reddit(keyword, days)
            all_results.extend(results)
        
        return all_results

class MarkdownGenerator:
    """Markdown生成クラス"""

    @staticmethod
    def generate(keyword: str, results: List[Dict], collection_date: str) -> str:
        """Markdownドキュメントを生成"""
        md = f"# {keyword} - 収集結果\n\n"
        md += f"**収集日時**: {collection_date}\n\n"
        md += f"**収集件数**: {len(results)}件\n\n"
        md += "---\n\n"

        # ソース別に分類
        by_source = {}
        for result in results:
            source = result['source']
            if source not in by_source:
                by_source[source] = []
            by_source[source].append(result)

        # ソースごとに出力
        for source, items in by_source.items():
            md += f"## {source} ({len(items)}件)\n\n"

            for i, item in enumerate(items, 1):
                md += f"### {i}. {item['title']}\n\n"
                md += f"- **URL**: {item['url']}\n"
                md += f"- **日付**: {item['date']}\n"

                if item['snippet']:
                    md += f"- **概要**: {item['snippet']}\n"

                md += "\n"

            md += "---\n\n"

        return md

class HTMLConverter:
    """HTML変換クラス"""

    # タイトル類似度の閾値
    TITLE_SIMILARITY_THRESHOLD = 0.80

    @staticmethod
    def load_markdown_content(filepath: Path) -> List[str]:
        """指定されたMarkdownファイルを読み込み、行のリストとして返す"""
        if not filepath.exists():
            raise FileNotFoundError(f"ファイルが見つかりません: {filepath}")
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.readlines()

    @staticmethod
    def parse_markdown_report(lines: List[str]) -> Dict:
        """Markdownレポートの内容を解析し、構造化されたデータ（辞書）として返す"""
        data = {
            "title": "",
            "collection_date_time": "",
            "total_count": 0,
            "results_by_source": []
        }

        current_source = None
        current_item = None

        # 1. ヘッダー情報の抽出
        for line in lines:
            if line.startswith('# '):
                data['title'] = line.strip('# ').strip()
            elif line.startswith('**収集日時**:'):
                data['collection_date_time'] = line.split(':', 1)[-1].strip()
            elif line.startswith('**収集件数**:'):
                match = re.search(r'\d+', line)
                data['total_count'] = int(match.group(0)) if match else 0
            elif line.startswith('---'):
                break

        # 2. 検索結果の抽出
        for line in lines:
            stripped_line = line.strip()

            # ソースの開始 (##)
            source_match = re.match(r'## (.+?) \(\d+件\)', stripped_line)
            if source_match:
                # 最後のアイテムを保存
                if current_item and current_source:
                    current_source['items'].append(current_item)
                    current_item = None

                source_name = source_match.group(1)
                current_source = {"name": source_name, "items": []}
                data['results_by_source'].append(current_source)
                continue

            # アイテムの開始 (###)
            item_match = re.match(r'### \d+\. (.+)', stripped_line)
            if item_match and current_source:
                # 前のアイテムを保存
                if current_item:
                    current_source['items'].append(current_item)

                title = item_match.group(1).strip()
                current_item = {"title": title, "url": "", "date": "", "snippet": ""}
                continue

            # アイテムの詳細
            if current_item:
                if stripped_line.startswith('- **URL**:'):
                    current_item['url'] = stripped_line.split(':', 1)[-1].strip()
                elif stripped_line.startswith('- **日付**:'):
                    current_item['date'] = stripped_line.split(':', 1)[-1].strip()
                elif stripped_line.startswith('- **概要**:'):
                    snippet = stripped_line.split(':', 1)[-1].strip()
                    current_item['snippet'] = snippet

        # 最後のアイテムを保存
        if current_item and current_source:
            current_source['items'].append(current_item)

        return data

    @staticmethod
    def normalize_url(url: str) -> str:
        """URLを正規化して重複判定しやすくする"""
        # DuckDuckGoのプレフィックスを削除
        if url.startswith('//duckduckgo.com/l/?uddg='):
            try:
                parsed_url = re.search(r'uddg=(.+?)&', url).group(1)
                decoded_url = urllib.parse.unquote(parsed_url)
                url = decoded_url
            except:
                pass
        # プロトコルが欠落している場合は追加
        if url.startswith('//'):
            url = 'https:' + url
        # 末尾のスラッシュを削除して統一
        return url.rstrip('/')

    @staticmethod
    def normalize_title(title: str) -> str:
        """タイトルを正規化して比較しやすくする"""
        # 小文字化
        title = title.lower()
        # 記号・空白の統一
        title = re.sub(r'\s+', ' ', title)  # 複数空白を1つに
        title = re.sub(r'[【】［］\[\]「」『』（）()〈〉《》]', '', title)  # 括弧類を削除
        # サイト名などの末尾情報を削除（" - サイト名" や " | サイト名" など）
        title = re.sub(r'\s*[-|:：]\s*[^-|:：]+$', '', title)
        return title.strip()

    @staticmethod
    def calculate_title_similarity(title1: str, title2: str) -> float:
        """2つのタイトルの類似度を計算（0.0〜1.0）"""
        normalized1 = HTMLConverter.normalize_title(title1)
        normalized2 = HTMLConverter.normalize_title(title2)
        return SequenceMatcher(None, normalized1, normalized2).ratio()

    @staticmethod
    def find_similar_article(new_item: Dict, existing_articles: Dict) -> str:
        """既存記事の中から類似したタイトルの記事を探す。見つかった場合はそのURLを返す"""
        new_title = new_item['title']

        for url, article in existing_articles.items():
            similarity = HTMLConverter.calculate_title_similarity(new_title, article['title'])
            if similarity >= HTMLConverter.TITLE_SIMILARITY_THRESHOLD:
                return url

        return None

    # キーワードセクションのアクセントカラー（最大20キーワードまで循環）
    KEYWORD_COLORS = [
        "#0078d4", "#107c10", "#d83b01", "#5c2d91", "#008272",
        "#004b50", "#ca5010", "#0099bc", "#8764b8", "#038387",
        "#c43e1c", "#00b294", "#6b69d6", "#bf0077", "#498205",
        "#7a7574", "#69797e", "#767676", "#0063b1", "#e81123"
    ]

    @staticmethod
    def generate_html(report_data: Dict, stock_data: Optional[List] = None) -> str:
        """構造化データからHTMLレポートを生成する"""

        sources = report_data['results_by_source']

        # --- 目次（TOC）生成 ---
        toc_items = ""
        for idx, source in enumerate(sources):
            color = HTMLConverter.KEYWORD_COLORS[idx % len(HTMLConverter.KEYWORD_COLORS)]
            anchor = f"kw_{idx}"
            toc_items += (
                f'<li>'
                f'<a href="#{anchor}" style="color:{color};">'
                f'{source["name"]}'
                f'</a>'
                f'<span class="toc-count">{len(source["items"])}件</span>'
                f'</li>\n'
            )

        toc_html = f"""
        <nav class="toc">
            <div class="toc-title">📋 キーワード一覧 ({len(sources)}件)</div>
            <ul class="toc-list">
{toc_items}            </ul>
        </nav>"""

        # --- 記事セクション生成 ---
        results_html = ""
        for idx, source in enumerate(sources):
            color = HTMLConverter.KEYWORD_COLORS[idx % len(HTMLConverter.KEYWORD_COLORS)]
            anchor = f"kw_{idx}"

            results_html += f'<section class="source-section" id="{anchor}">\n'
            results_html += (
                f'  <h2 class="source-title" style="border-left-color:{color};">'
                f'<span class="kw-badge" style="background:{color};">🔑</span>'
                f' {source["name"]}'
                f' <span class="source-count">({len(source["items"])}件)</span>'
                f'</h2>\n'
            )
            results_html += f'  <div class="result-list">\n'

            # このキーワードセクションの銘柄データ
            section_stocks = stock_data[idx] if (stock_data and idx < len(stock_data)) else []

            for i, item in enumerate(source['items'], 1):
                url = HTMLConverter.normalize_url(item['url'])

                # 関連キーワード（複数キーワードに属する場合）
                related_kws = item.get('keywords', [])
                related_html = ""
                if len(related_kws) > 1:
                    tags = "".join(
                        f'<span class="kw-tag">{kw}</span>'
                        for kw in related_kws
                    )
                    related_html = f'      <p class="item-meta item-related">関連キーワード: {tags}</p>\n'

                # 関連上場企業（stock_data がある場合）
                item_stocks = section_stocks[i - 1] if (i - 1) < len(section_stocks) else []
                stocks_html = ""
                if item_stocks:
                    stocks_inner = "".join(
                        f'<a href="https://kabutan.jp/stock/?code={c["code"]}" '
                        f'target="_blank" class="stock-link">{c["code"]}</a>'
                        f'<span class="stock-company">{c["name"]}</span>'
                        for c in item_stocks
                    )
                    stocks_html = f'      <div class="related-stocks">📈 関連銘柄: {stocks_inner}</div>\n'

                results_html += f'    <div class="result-item">\n'
                results_html += (
                    f'      <h3 class="item-title">'
                    f'{i}. <a href="{url}" target="_blank">{item["title"]}</a>'
                    f'</h3>\n'
                )
                results_html += f'      <p class="item-meta"><strong>日付:</strong> {item["date"]}</p>\n'
                results_html += related_html
                results_html += f'      <p class="item-url"><strong>URL:</strong> <a href="{url}" target="_blank">{url}</a></p>\n'
                if item['snippet']:
                    snippet_html = markdown.markdown(item['snippet']).replace('<p>', '').replace('</p>', '').strip()
                    results_html += f'      <div class="item-snippet"><strong>概要:</strong> {snippet_html}</div>\n'
                results_html += stocks_html
                results_html += f'    </div>\n'

            results_html += f'  </div>\n'
            results_html += f'  <div class="back-to-top"><a href="#top">▲ キーワード一覧へ戻る</a></div>\n'
            results_html += f'</section>\n'

        html_template = f"""<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{report_data['title']} - 収集レポート</title>
    <style>
        * {{ box-sizing: border-box; }}
        body {{
            font-family: 'Segoe UI', 'Yu Gothic UI', Tahoma, Geneva, Verdana, sans-serif;
            margin: 0;
            padding: 0;
            background-color: #f4f7f9;
            color: #333;
        }}
        .container {{
            max-width: 1000px;
            margin: 30px auto;
            padding: 20px;
            background-color: #fff;
            box-shadow: 0 4px 12px rgba(0,0,0,0.1);
            border-radius: 8px;
        }}
        header {{
            border-bottom: 3px solid #0078d4;
            padding-bottom: 10px;
            margin-bottom: 20px;
        }}
        header h1 {{
            color: #0078d4;
            font-size: 2em;
            margin: 0;
        }}
        .summary {{
            background-color: #e9f7ff;
            padding: 12px 15px;
            border-radius: 6px;
            margin-bottom: 20px;
            border-left: 5px solid #0078d4;
        }}
        .summary p {{
            margin: 4px 0;
            font-size: 1em;
        }}
        /* 目次 */
        .toc {{
            background: #f8f9fa;
            border: 1px solid #dee2e6;
            border-radius: 8px;
            padding: 14px 18px;
            margin-bottom: 28px;
        }}
        .toc-title {{
            font-weight: 700;
            font-size: 1em;
            margin-bottom: 8px;
            color: #444;
        }}
        .toc-list {{
            margin: 0;
            padding: 0;
            list-style: none;
            display: flex;
            flex-wrap: wrap;
            gap: 6px;
        }}
        .toc-list li {{
            display: flex;
            align-items: center;
            gap: 4px;
        }}
        .toc-list a {{
            text-decoration: none;
            font-weight: 600;
            font-size: 0.9em;
            padding: 3px 8px;
            border-radius: 4px;
            background: #fff;
            border: 1px solid currentColor;
            transition: opacity 0.15s;
        }}
        .toc-list a:hover {{ opacity: 0.75; }}
        .toc-count {{
            font-size: 0.78em;
            color: #888;
            white-space: nowrap;
        }}
        /* キーワードセクション */
        .source-section {{
            margin-bottom: 36px;
            padding: 16px;
            border: 1px solid #e0e0e0;
            border-radius: 8px;
            background-color: #fff;
        }}
        .source-title {{
            display: flex;
            align-items: center;
            gap: 8px;
            color: #222;
            border-left: 5px solid #0078d4;
            padding: 6px 10px;
            margin: 0 0 16px 0;
            font-size: 1.35em;
            background: #fafafa;
            border-radius: 0 4px 4px 0;
        }}
        .kw-badge {{
            font-size: 0.85em;
        }}
        .source-count {{
            font-size: 0.75em;
            font-weight: 400;
            color: #666;
        }}
        .result-item {{
            margin-bottom: 16px;
            padding: 13px 15px;
            border: 1px solid #eee;
            border-radius: 5px;
            background-color: #fafafa;
            transition: border-color 0.15s;
        }}
        .result-item:hover {{ border-color: #bbb; }}
        .item-title {{
            font-size: 1.1em;
            color: #2c3e50;
            margin: 0 0 8px 0;
        }}
        .item-title a {{
            text-decoration: none;
            color: #005a99;
        }}
        .item-title a:hover {{ text-decoration: underline; }}
        .item-meta, .item-url {{
            font-size: 0.88em;
            color: #555;
            margin: 3px 0;
        }}
        .item-url a {{
            color: #0078d4;
            word-break: break-all;
        }}
        .item-related {{ color: #666; }}
        .kw-tag {{
            display: inline-block;
            background: #e8f0fe;
            color: #1a73e8;
            border-radius: 3px;
            padding: 1px 6px;
            font-size: 0.82em;
            margin: 0 2px;
        }}
        .item-snippet {{
            margin-top: 8px;
            padding-top: 6px;
            border-top: 1px dotted #ccc;
            font-style: italic;
            font-size: 0.92em;
            line-height: 1.4;
            color: #555;
        }}
        .related-stocks {{
            margin-top: 8px;
            padding-top: 6px;
            border-top: 1px dotted #ccc;
            font-size: 0.86em;
            color: #444;
        }}
        .stock-link {{
            display: inline-block;
            background: #fff3e0;
            color: #e65100;
            border: 1px solid #ffb74d;
            border-radius: 3px;
            padding: 1px 6px;
            font-size: 0.9em;
            text-decoration: none;
            font-weight: 700;
            margin-right: 2px;
            transition: background 0.15s;
        }}
        .stock-link:hover {{ background: #ffe0b2; }}
        .stock-company {{
            color: #555;
            margin-right: 10px;
        }}
        .back-to-top {{
            text-align: right;
            font-size: 0.82em;
            margin-top: 10px;
        }}
        .back-to-top a {{
            color: #888;
            text-decoration: none;
        }}
        .back-to-top a:hover {{ color: #0078d4; }}
        footer {{
            text-align: center;
            font-size: 0.8em;
            color: #999;
            margin-top: 20px;
            padding-top: 12px;
            border-top: 1px solid #eee;
        }}
        @media (max-width: 640px) {{
            .container {{ margin: 10px; padding: 14px; }}
            header h1 {{ font-size: 1.4em; }}
            .source-title {{ font-size: 1.1em; }}
        }}
    </style>
</head>
<body>
    <div class="container" id="top">
        <header>
            <h1>{report_data['title']} - 収集レポート</h1>
        </header>

        <div class="summary">
            <p><strong>収集日時:</strong> {report_data['collection_date_time']}</p>
            <p><strong>総件数:</strong> {report_data['total_count']}件 / キーワード数: {len(sources)}件</p>
        </div>

        {toc_html}

        {results_html}

        <footer>
            レポート生成日時: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        </footer>
    </div>
</body>
</html>"""
        return html_template

    @staticmethod
    def extract_date_from_filename(filename: str) -> str:
        """ファイル名から日付部分を抽出 (例: キーワード名-2025-12-29.md -> 2025-12-29)"""
        match = re.search(r'(\d{4}-\d{2}-\d{2})\.md$', filename)
        return match.group(1) if match else ""

    @staticmethod
    def merge_reports_by_date(files_by_date: Dict[str, List[Path]], log_func=None) -> Dict[str, Dict]:
        """同じ日付の複数のMarkdownファイルを統合し、URL重複を除外する"""
        merged_data = {}

        def log(msg):
            if log_func:
                log_func(msg)
            else:
                print(msg)

        for date_str, file_list in files_by_date.items():
            log(f"  [{date_str}] {len(file_list)}個のキーワードレポートを統合中...")

            # URL単位で記事を管理（重複排除用）
            articles_by_url = {}  # {normalized_url: article_with_keywords}

            # 統合データの初期化
            merged_report = {
                "title": f"統合レポート - {date_str}",
                "collection_date_time": date_str,
                "total_count": 0,
                "results_by_source": [],
                "keywords_count": len(file_list)
            }

            # キーワード別のデータを統合
            keyword_items = defaultdict(list)  # {keyword: [items]}
            keyword_order = []  # キーワードの登場順を保持

            for filepath in file_list:
                # キーワード名を抽出（ファイル名から日付部分を除く）
                keyword = filepath.stem.rsplit('-', 3)[0]  # "キーワード-2025-12-29" -> "キーワード"

                log(f"    - 処理中: {filepath.name} (キーワード: {keyword})")

                try:
                    lines = HTMLConverter.load_markdown_content(filepath)
                    report_data = HTMLConverter.parse_markdown_report(lines)

                    if not report_data['title']:
                        log(f"      -> スキップ: タイトルが見つかりません。")
                        continue

                    # 各ソースの記事を処理
                    for source in report_data['results_by_source']:
                        for item in source['items']:
                            normalized_url = HTMLConverter.normalize_url(item['url'])

                            # URL重複チェック
                            if normalized_url in articles_by_url:
                                # 既存の記事にキーワードを追加（関連キーワード表示用）
                                if 'keywords' not in articles_by_url[normalized_url]:
                                    articles_by_url[normalized_url]['keywords'] = []
                                if keyword not in articles_by_url[normalized_url]['keywords']:
                                    articles_by_url[normalized_url]['keywords'].append(keyword)
                                log(f"      -> 重複排除: {item['title'][:40]}... (URL重複)")
                            else:
                                # タイトル類似度チェック
                                similar_url = HTMLConverter.find_similar_article(item, articles_by_url)
                                if similar_url:
                                    # 類似記事が見つかった場合、そちらにキーワードを追加
                                    if 'keywords' not in articles_by_url[similar_url]:
                                        articles_by_url[similar_url]['keywords'] = []
                                    if keyword not in articles_by_url[similar_url]['keywords']:
                                        articles_by_url[similar_url]['keywords'].append(keyword)
                                    similarity = HTMLConverter.calculate_title_similarity(item['title'], articles_by_url[similar_url]['title'])
                                    log(f"      -> 重複排除: {item['title'][:40]}... (タイトル類似度: {similarity:.2f})")
                                else:
                                    # 新規記事として追加（キーワード別セクションへ）
                                    item['keywords'] = [keyword]
                                    item['url'] = normalized_url  # 正規化したURLで上書き
                                    articles_by_url[normalized_url] = item
                                    if keyword not in keyword_order:
                                        keyword_order.append(keyword)
                                    keyword_items[keyword].append(item)

                except Exception as e:
                    log(f"      -> エラー: {e}")
                    continue

            # キーワード別データを整形（登場順を維持）
            for kw in keyword_order:
                items = keyword_items[kw]
                merged_report['results_by_source'].append({
                    "name": kw,
                    "items": items
                })
                merged_report['total_count'] += len(items)

            log(f"    統合完了: 総記事数 {merged_report['total_count']}件 (重複除外後)")
            merged_data[date_str] = merged_report

        return merged_data

    @staticmethod
    def convert_markdown_to_html(input_dir: Path, output_dir: Path, today_only=True, log_func=None, stock_resolver=None):
        """MarkdownファイルをHTMLに変換する

        Args:
            input_dir: Markdownファイルのディレクトリ
            output_dir: HTMLファイルの出力ディレクトリ
            today_only: Trueの場合、本日のファイルのみ処理
            log_func: ログ出力関数
            stock_resolver: StockResolver インスタンス（Noneの場合は銘柄表示なし）
        """
        def log(msg):
            if log_func:
                log_func(msg)
            else:
                print(msg)

        log("=== HTML変換を開始します ===")

        # 1. 出力ディレクトリの作成
        output_dir.mkdir(exist_ok=True)

        # 2. Markdownファイルの一覧取得
        today_str = datetime.now().strftime('%Y-%m-%d')

        if today_only:
            # 本日のファイルのみ取得
            md_files = sorted(input_dir.glob(f"*-{today_str}.md"))
            log(f"処理モード: 本日分のみ ({today_str})")
        else:
            # 全ファイル取得
            md_files = sorted(input_dir.glob("*.md"))
            log(f"処理モード: 全ファイル")

        if not md_files:
            if today_only:
                log(f"本日 ({today_str}) のMarkdownファイルが見つかりません。")
            else:
                log(f"エラー: `{input_dir.name}` フォルダにMarkdownファイルが見つかりません。")
            return

        log(f"対象ファイル数: {len(md_files)}件")

        # 3. 日付ごとにファイルをグループ化
        files_by_date = defaultdict(list)
        for filepath in md_files:
            date_str = HTMLConverter.extract_date_from_filename(filepath.name)
            if date_str:
                files_by_date[date_str].append(filepath)
            else:
                log(f"  警告: 日付を抽出できませんでした - {filepath.name}")

        if not files_by_date:
            log("エラー: 有効な日付形式のファイルが見つかりませんでした。")
            return

        log(f"収集日数: {len(files_by_date)}日分")
        log("")

        # 4. 日付ごとにレポートを統合
        merged_reports = HTMLConverter.merge_reports_by_date(files_by_date, log_func)

        log("")
        log("=== HTML生成中 ===")

        # 5. 統合レポートをHTMLに変換
        for date_str, report_data in sorted(merged_reports.items()):
            try:
                log(f"  [{date_str}] HTML生成中...")

                # 銘柄解決（stock_resolver が設定されている場合）
                stock_data = None
                if stock_resolver is not None:
                    log(f"  [{date_str}] 関連銘柄を検索中...")
                    stock_data = []
                    for section in report_data['results_by_source']:
                        keyword = section['name']
                        companies = stock_resolver.resolve_for_keyword(keyword, section['items'])
                        stock_data.append(companies)
                        log(f"    [{keyword}] 銘柄取得完了")

                html_content = HTMLConverter.generate_html(report_data, stock_data)

                output_filename = f"レポート-{date_str}.html"
                output_filepath = output_dir / output_filename

                with open(output_filepath, 'w', encoding='utf-8') as f:
                    f.write(html_content)

                log(f"    -> 完了: {output_filepath.name}")

            except Exception as e:
                log(f"    -> エラー: {e}")
                continue

        log("")
        log("--------------------------------------------------")
        log(f"[完了] すべてのHTMLレポートの生成が完了しました。")
        log(f"保存先ディレクトリ: {output_dir.absolute()}")
        log("--------------------------------------------------")

class ArticleDB:
    """記事データベース管理クラス"""

    def __init__(self, db_path: str = "database.sqlite"):
        self.db_path = Path(db_path)

    def _get_connection(self):
        """DB接続を取得"""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row  # 辞書形式で取得
        return conn

    def initialize_db(self):
        """データベース初期化"""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL UNIQUE,
                normalized_url TEXT,
                title TEXT NOT NULL,
                snippet TEXT,
                content TEXT,
                author TEXT,
                published_date TEXT,
                source TEXT,
                keywords TEXT,

                status TEXT DEFAULT 'new',
                tags TEXT,

                user_notes TEXT,
                generated_draft TEXT,

                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # インデックス作成
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_url ON articles(url)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_status ON articles(status)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_created_at ON articles(created_at DESC)')

        conn.commit()
        conn.close()

    def add_article(self, url: str, title: str, snippet: str = None,
                   content: str = None, normalized_url: str = None,
                   source: str = None, keywords: str = None,
                   published_date: str = None) -> int:
        """記事を追加（タイトル類似度による重複チェック付き）"""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            # 1. URL完全一致チェック
            cursor.execute('SELECT id FROM articles WHERE url = ?', (url,))
            existing = cursor.fetchone()
            if existing:
                return existing['id']

            # 2. タイトル類似度チェック（過去7日分の記事を対象）
            seven_days_ago = (datetime.now() - timedelta(days=7)).isoformat()
            cursor.execute('''
                SELECT id, title, keywords FROM articles
                WHERE created_at >= ?
            ''', (seven_days_ago,))

            recent_articles = cursor.fetchall()

            for article in recent_articles:
                similarity = HTMLConverter.calculate_title_similarity(title, article['title'])

                # 類似度が80%以上なら重複と判定
                if similarity >= 0.80:
                    # 既存記事のキーワードに追加
                    existing_keywords = article['keywords'] or ''
                    if keywords and keywords not in existing_keywords:
                        new_keywords = f"{existing_keywords},{keywords}" if existing_keywords else keywords
                        cursor.execute('''
                            UPDATE articles SET keywords = ?, updated_at = ?
                            WHERE id = ?
                        ''', (new_keywords, datetime.now().isoformat(), article['id']))
                        conn.commit()

                    print(f"[DB] 重複記事を統合: {title[:40]}... (類似度: {similarity:.2f})")
                    return article['id']

            # 3. 新規記事として追加
            cursor.execute('''
                INSERT INTO articles (url, normalized_url, title, snippet, content, source, keywords, published_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (url, normalized_url, title, snippet, content, source, keywords, published_date))

            conn.commit()
            article_id = cursor.lastrowid
            return article_id

        except sqlite3.IntegrityError:
            # 念のため、URL重複エラーの場合は既存IDを返す
            cursor.execute('SELECT id FROM articles WHERE url = ?', (url,))
            row = cursor.fetchone()
            return row['id'] if row else None

        finally:
            conn.close()

    def get_article(self, article_id: int) -> Optional[Dict]:
        """記事を取得"""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute('SELECT * FROM articles WHERE id = ?', (article_id,))
        row = cursor.fetchone()
        conn.close()

        return dict(row) if row else None

    def get_all_articles(self, status: str = None, limit: int = 100) -> List[Dict]:
        """記事一覧を取得"""
        conn = self._get_connection()
        cursor = conn.cursor()

        if status:
            cursor.execute('''
                SELECT * FROM articles
                WHERE status = ?
                ORDER BY created_at DESC
                LIMIT ?
            ''', (status, limit))
        else:
            cursor.execute('''
                SELECT * FROM articles
                ORDER BY created_at DESC
                LIMIT ?
            ''', (limit,))

        rows = cursor.fetchall()
        conn.close()

        return [dict(row) for row in rows]

    def update_article(self, article_id: int, **kwargs):
        """記事を更新"""
        conn = self._get_connection()
        cursor = conn.cursor()

        # 更新するフィールドを動的に構築
        fields = []
        values = []
        for key, value in kwargs.items():
            fields.append(f"{key} = ?")
            values.append(value)

        # updated_atも更新
        fields.append("updated_at = ?")
        values.append(datetime.now().isoformat())

        values.append(article_id)

        query = f"UPDATE articles SET {', '.join(fields)} WHERE id = ?"
        cursor.execute(query, values)

        conn.commit()
        conn.close()

    def delete_article(self, article_id: int):
        """記事を削除"""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute('DELETE FROM articles WHERE id = ?', (article_id,))

        conn.commit()
        conn.close()

    def search_articles(self, keyword: str) -> List[Dict]:
        """記事を検索"""
        conn = self._get_connection()
        cursor = conn.cursor()

        search_pattern = f"%{keyword}%"
        cursor.execute('''
            SELECT * FROM articles
            WHERE title LIKE ? OR content LIKE ? OR tags LIKE ? OR keywords LIKE ?
            ORDER BY created_at DESC
        ''', (search_pattern, search_pattern, search_pattern, search_pattern))

        rows = cursor.fetchall()
        conn.close()

        return [dict(row) for row in rows]


class AIGenerator:
    """AI下書き生成クラス（Gemini API）"""

    def __init__(self, api_key: str):
        """
        Args:
            api_key: Gemini API キー
        """
        if not api_key:
            raise ValueError("GEMINI_API_KEY が設定されていません")

        try:
            import google.generativeai as genai
            # transport='rest' でgRPC SSL証明書エラー回避（Windows環境対策）
            genai.configure(api_key=api_key, transport='rest')
            self.model = genai.GenerativeModel('models/gemini-2.0-flash-exp')
        except ImportError:
            raise ImportError("google-generativeai パッケージがインストールされていません。pip install google-generativeai を実行してください。")

    def generate_draft(self, article_data: Dict) -> str:
        """記事データから下書きを生成"""
        prompt = self._build_prompt(article_data)

        try:
            response = self.model.generate_content(prompt)
            draft = response.text
            return draft

        except Exception as e:
            print(f"Gemini API エラー: {e}")
            return f"# エラー\n\n下書きの生成に失敗しました。\n\nエラー内容: {str(e)}"

    def _build_prompt(self, article_data: Dict) -> str:
        """プロンプトを構築"""
        title = article_data.get('title', '不明')
        url = article_data.get('url', '')
        content = article_data.get('content', '')
        snippet = article_data.get('snippet', '')

        # 本文がない場合はスニペットを使用
        article_text = content if content else snippet

        prompt = f"""あなたはニュース記事を深く分析し、独自の視点で解説・感想を書くライターです。

以下の記事について、NOTE用の下書きを作成してください：

**記事タイトル**: {title}
**URL**: {url}
**記事内容**:
{article_text[:3000]}

---

以下の構成で、深い分析と個人的な意見を含む文章を書いてください：

1. **記事の要点** (2-3文で簡潔に)
2. **深掘り分析** (背景、文脈、影響などを掘り下げる)
3. **個人的な見解** (独自の視点や批判的考察)
4. **今後の展望** (この話題がどう発展するか)

**出力形式**:
- Markdown形式で出力
- 見出しは ## を使用
- 参考リンクとして元記事URLを文末に記載
- 文体：です・ます調、読みやすく
- 文字数：800-1200字程度

---

それでは、上記の記事について分析と感想を書いてください。"""

        return prompt


class StockResolver:
    """ニュース記事から関連上場企業を特定するクラス（Gemini API使用）"""

    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("GEMINI_API_KEY が設定されていません")
        try:
            import google.generativeai as genai
            # transport='rest' でgRPC SSL証明書エラー回避（Windows環境対策）
            genai.configure(api_key=api_key, transport='rest')
            self.model = genai.GenerativeModel('models/gemini-2.0-flash-exp')
        except ImportError:
            raise ImportError("google-generativeai パッケージが必要です")

    def resolve_for_keyword(self, keyword: str, items: List[Dict]) -> List[List[Dict]]:
        """キーワードセクション内の全記事について関連上場企業を一括取得。
        Returns: items と同じ長さのリスト。各要素は [{"code": "XXXX", "name": "企業名"}, ...] 。
        API エラー時は空リストのリストを返す。
        """
        if not items:
            return []

        articles_text = ""
        for i, item in enumerate(items, 1):
            title = item.get('title', '')
            snippet = item.get('snippet', '')[:200]
            articles_text += f"{i}. タイトル: {title}"
            if snippet:
                articles_text += f" / 概要: {snippet}"
            articles_text += "\n"

        prompt = f"""以下は「{keyword}」というキーワードで収集したニュース記事です。
各記事に関連する日本の上場企業を証券コードと企業名で教えてください。

記事リスト:
{articles_text}
以下のJSON形式のみで回答してください。関連する上場企業が無い記事は空リストにしてください：
{{
  "1": [{{"code": "6770", "name": "アルプスアルパイン"}}],
  "2": [],
  "3": [{{"code": "4755", "name": "楽天グループ"}}, {{"code": "9984", "name": "ソフトバンクグループ"}}]
}}

注意：
- 証券コードは東京証券取引所上場の4桁数字のみ
- 関連性が明確な企業のみ挙げてください（推測で挙げないでください）
- JSONのみ出力し、説明文やコードブロック記法（```json など）は不要です"""

        try:
            response = self.model.generate_content(prompt)
            raw = response.text.strip()
            # コードブロック記法を除去
            if raw.startswith('```'):
                raw = re.sub(r'^```[^\n]*\n?', '', raw)
                raw = re.sub(r'\n?```$', '', raw.strip())
            parsed = json.loads(raw)
            result = []
            for i in range(1, len(items) + 1):
                companies = parsed.get(str(i), [])
                valid = [
                    c for c in companies
                    if isinstance(c, dict)
                    and c.get('code') and c.get('name')
                    and str(c['code']).isdigit()
                ]
                result.append(valid)
            return result
        except Exception as e:
            print(f"[StockResolver] {keyword}: エラー - {e}")
            return [[] for _ in items]


# Flask アプリケーション
app = Flask(__name__)
app.secret_key = 'context-collector-secret-key'

# グローバル変数（ContextCollectorAppから参照できるように）
db_instance = None
ai_generator = None

@app.route('/')
def index():
    """トップページ - 記事一覧"""
    if db_instance is None:
        return "データベースが初期化されていません", 500
    articles = db_instance.get_all_articles(limit=100)
    return render_template('article_list.html', articles=articles)


@app.route('/article/<int:article_id>')
def article_detail(article_id):
    """記事詳細・編集ページ"""
    if db_instance is None:
        return "データベースが初期化されていません", 500
    article = db_instance.get_article(article_id)
    if not article:
        return "記事が見つかりません", 404
    return render_template('article_editor.html', article=article)


@app.route('/api/article/<int:article_id>', methods=['GET', 'PUT', 'DELETE'])
def api_article(article_id):
    """記事CRUD API"""
    if db_instance is None:
        return jsonify({'error': 'データベースが初期化されていません'}), 500

    if request.method == 'GET':
        article = db_instance.get_article(article_id)
        if not article:
            return jsonify({'error': '記事が見つかりません'}), 404
        return jsonify(article)

    elif request.method == 'PUT':
        data = request.get_json()
        try:
            # 更新可能なフィールドのみ抽出
            update_fields = {}
            allowed_fields = ['title', 'snippet', 'content', 'user_notes', 'tags', 'status']

            for field in allowed_fields:
                if field in data:
                    update_fields[field] = data[field]

            db_instance.update_article(article_id, **update_fields)
            return jsonify({'success': True})

        except Exception as e:
            return jsonify({'error': str(e)}), 500

    elif request.method == 'DELETE':
        try:
            db_instance.delete_article(article_id)
            return jsonify({'success': True})
        except Exception as e:
            return jsonify({'error': str(e)}), 500


@app.route('/api/search')
def api_search():
    """記事検索API"""
    if db_instance is None:
        return jsonify([])
    keyword = request.args.get('q', '')
    if not keyword:
        return jsonify([])
    articles = db_instance.search_articles(keyword)
    return jsonify(articles)


@app.route('/status/<status>')
def articles_by_status(status):
    """ステータス別記事一覧"""
    if db_instance is None:
        return "データベースが初期化されていません", 500
    valid_statuses = ['new', 'edited', 'draft_generated', 'published']
    if status not in valid_statuses:
        return "無効なステータス", 400
    articles = db_instance.get_all_articles(status=status)
    return render_template('article_list.html', articles=articles, current_status=status)


@app.route('/api/generate-draft/<int:article_id>', methods=['POST'])
def api_generate_draft(article_id):
    """AI下書き生成API"""
    # AI APIが利用できない場合
    if ai_generator is None:
        return jsonify({'error': 'AI APIキーが設定されていません。config.jsonファイルを確認してください。'}), 400

    if db_instance is None:
        return jsonify({'error': 'データベースが初期化されていません'}), 500

    article = db_instance.get_article(article_id)
    if not article:
        return jsonify({'error': '記事が見つかりません'}), 404

    try:
        # AI APIで下書き生成
        draft = ai_generator.generate_draft(article)

        # DBに保存
        db_instance.update_article(
            article_id,
            generated_draft=draft,
            status='draft_generated'
        )

        return jsonify({
            'success': True,
            'draft': draft
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


def run_flask_app(port=5000):
    """Flask アプリケーションを起動"""
    app.run(debug=False, host='127.0.0.1', port=port, use_reloader=False)


class ContextCollectorApp:
    """メインアプリケーション"""

    def __init__(self):
        global db_instance, ai_generator
        self.config = Config()
        # 出力ディレクトリ作成
        self.output_dir = Path("outputs")
        self.output_dir.mkdir(exist_ok=True)
        self.reports_dir = Path("reports")
        self.reports_dir.mkdir(exist_ok=True)
        self.collector = ContentCollector(self.output_dir)
        # データベース初期化
        self.db = ArticleDB()
        self.db.initialize_db()
        db_instance = self.db  # Flaskアプリで使用するためグローバル変数に設定

        # AI Generator初期化（API キーが設定されている場合のみ）
        if self.config.config.get('ai_enabled') and self.config.config.get('gemini_api_key'):
            try:
                ai_generator = AIGenerator(api_key=self.config.config['gemini_api_key'])
                print("[OK] Gemini AI 下書き生成機能が有効になりました")
            except Exception as e:
                print(f"[警告] AI Generator初期化エラー: {e}")
                print("AI下書き生成機能は利用できません")
                ai_generator = None
        else:
            ai_generator = None
            print("[INFO] AI下書き生成機能は無効です（config.jsonで設定可能）")

        # Stock Resolver初期化（ai_enabled の場合のみ）
        if self.config.config.get('ai_enabled') and self.config.config.get('gemini_api_key'):
            try:
                self.stock_resolver = StockResolver(api_key=self.config.config['gemini_api_key'])
                print("[OK] 関連銘柄検索機能が有効になりました")
            except Exception as e:
                print(f"[警告] StockResolver初期化エラー: {e}")
                self.stock_resolver = None
        else:
            self.stock_resolver = None

        self.root = None
        self.tray_icon = None
        self.is_collecting = False
        self.command_queue = queue.Queue()
        self.auto_exit_after_startup = False  # 起動時収集後に自動終了するか
        self.flask_port = 5000
        # Flask Webサーバーを別スレッドで起動
        self.flask_thread = threading.Thread(target=run_flask_app, args=(self.flask_port,), daemon=True)
        self.flask_thread.start()
        print(f"Flask Web UI起動: http://127.0.0.1:{self.flask_port}")
    
    def create_tray_icon(self):
        """システムトレイアイコンを作成"""
        # アイコン画像を作成
        image = Image.new('RGB', (64, 64), color='#4A90E2')
        draw = ImageDraw.Draw(image)
        draw.rectangle([16, 16, 48, 48], fill='white')
        draw.text((20, 22), "CC", fill='#4A90E2')
        
        # メニュー作成
        menu = pystray.Menu(
            pystray.MenuItem('Web UIを開く', self.open_web_ui),
            pystray.MenuItem('今すぐ収集', self.collect_now_from_tray),
            pystray.MenuItem('設定画面を開く', self.show_settings_from_tray),
            pystray.MenuItem('終了', self.quit_app)
        )
        
        self.tray_icon = pystray.Icon("context_collector", image, "コンテキスト収集", menu)
    
    def open_web_ui(self, icon=None, item=None):
        """Web UIをブラウザで開く"""
        import webbrowser
        webbrowser.open(f"http://127.0.0.1:{self.flask_port}")

    def show_settings_from_tray(self, icon=None, item=None):
        """トレイから設定画面を表示（コマンドキューに追加）"""
        self.command_queue.put(('show_settings', None))

    def collect_now_from_tray(self, icon=None, item=None):
        """トレイから収集を実行（コマンドキューに追加）"""
        self.command_queue.put(('collect_now', None))
    
    def process_commands(self):
        """コマンドキューを処理"""
        try:
            while True:
                try:
                    command, data = self.command_queue.get_nowait()
                    
                    if command == 'show_settings':
                        self.show_settings()
                    elif command == 'collect_now':
                        self.collect_now()
                    
                except queue.Empty:
                    break
        finally:
            if self.root:
                self.root.after(100, self.process_commands)
    
    def show_settings(self):
        """設定画面を表示"""
        if self.root:
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
    
    def hide_window(self):
        """ウィンドウを非表示"""
        if self.root:
            self.root.withdraw()
    
    def create_settings_ui(self):
        """設定UIを作成"""
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill='both', expand=True, padx=10, pady=10)
        
        # キーワード設定タブ
        keyword_frame = ttk.Frame(notebook)
        notebook.add(keyword_frame, text='キーワード設定')
        
        ttk.Label(keyword_frame, text="監視キーワード:").pack(anchor='w', padx=10, pady=(10, 5))
        
        # キーワードリスト
        list_frame = ttk.Frame(keyword_frame)
        list_frame.pack(fill='both', expand=True, padx=10, pady=5)
        
        scrollbar = ttk.Scrollbar(list_frame)
        scrollbar.pack(side='right', fill='y')
        
        self.keyword_listbox = tk.Listbox(list_frame, yscrollcommand=scrollbar.set)
        self.keyword_listbox.pack(side='left', fill='both', expand=True)
        scrollbar.config(command=self.keyword_listbox.yview)
        
        # キーワード追加・削除
        button_frame = ttk.Frame(keyword_frame)
        button_frame.pack(fill='x', padx=10, pady=5)
        
        self.keyword_entry = ttk.Entry(button_frame)
        self.keyword_entry.pack(side='left', fill='x', expand=True, padx=(0, 5))
        self.keyword_entry.bind('<Return>', lambda e: self.add_keyword())
        
        ttk.Button(button_frame, text="追加", command=self.add_keyword).pack(side='left', padx=2)
        ttk.Button(button_frame, text="削除", command=self.remove_keyword).pack(side='left', padx=2)
        
        # 一般設定タブ
        general_frame = ttk.Frame(notebook)
        notebook.add(general_frame, text='一般設定')
        
        ttk.Label(general_frame, text="収集間隔:").grid(row=0, column=0, sticky='w', padx=10, pady=10)
        self.interval_var = tk.IntVar(value=self.config.config['check_interval_hours'])
        ttk.Spinbox(general_frame, from_=1, to=168, textvariable=self.interval_var, width=10).grid(row=0, column=1, sticky='w', pady=10)
        ttk.Label(general_frame, text="時間").grid(row=0, column=2, sticky='w', pady=10)
        
        ttk.Label(general_frame, text="初回収集期間:").grid(row=1, column=0, sticky='w', padx=10, pady=10)
        self.initial_days_var = tk.IntVar(value=self.config.config['initial_days'])
        ttk.Spinbox(general_frame, from_=1, to=90, textvariable=self.initial_days_var, width=10).grid(row=1, column=1, sticky='w', pady=10)
        ttk.Label(general_frame, text="日").grid(row=1, column=2, sticky='w', pady=10)
        
        ttk.Label(general_frame, text="言語:").grid(row=2, column=0, sticky='w', padx=10, pady=10)
        self.lang_var = tk.StringVar(value=self.config.config['language'])
        lang_combo = ttk.Combobox(general_frame, textvariable=self.lang_var, values=['ja', 'en', 'ja,en'], width=10, state='readonly')
        lang_combo.grid(row=2, column=1, sticky='w', pady=10)
        
        self.autostart_var = tk.BooleanVar(value=self.config.config['auto_start'])
        ttk.Checkbutton(general_frame, text="Windows起動時に自動起動", variable=self.autostart_var, command=self.toggle_autostart).grid(row=3, column=0, columnspan=3, sticky='w', padx=10, pady=10)
        
        # 保存ボタン
        save_btn = ttk.Button(general_frame, text="設定を保存", command=self.save_settings)
        save_btn.grid(row=4, column=0, columnspan=3, pady=20)
        
        # 手動収集ボタン
        collect_btn = ttk.Button(general_frame, text="今すぐ収集", command=self.collect_now)
        collect_btn.grid(row=5, column=0, columnspan=3, pady=5)
        
        # ログタブ
        log_frame = ttk.Frame(notebook)
        notebook.add(log_frame, text='ログ')
        
        self.log_text = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, height=20)
        self.log_text.pack(fill='both', expand=True, padx=10, pady=10)
        
        # キーワードをロード
        self.load_keywords()
    
    def load_keywords(self):
        """キーワードをロード"""
        self.keyword_listbox.delete(0, tk.END)
        for keyword in self.config.config['keywords']:
            self.keyword_listbox.insert(tk.END, keyword)
    
    def add_keyword(self):
        """キーワードを追加"""
        keyword = self.keyword_entry.get().strip()
        if keyword and keyword not in self.config.config['keywords']:
            self.config.config['keywords'].append(keyword)
            self.keyword_listbox.insert(tk.END, keyword)
            self.keyword_entry.delete(0, tk.END)
            self.log(f"キーワードを追加: {keyword}")
    
    def remove_keyword(self):
        """キーワードを削除"""
        selection = self.keyword_listbox.curselection()
        if selection:
            keyword = self.keyword_listbox.get(selection[0])
            self.config.config['keywords'].remove(keyword)
            self.keyword_listbox.delete(selection[0])
            self.log(f"キーワードを削除: {keyword}")
    
    def save_settings(self):
        """設定を保存"""
        self.config.config['check_interval_hours'] = self.interval_var.get()
        self.config.config['initial_days'] = self.initial_days_var.get()
        self.config.config['language'] = self.lang_var.get()
        self.config.config['auto_start'] = self.autostart_var.get()
        self.config.save_config()
        
        self.log("設定を保存しました")
        messagebox.showinfo("保存完了", "設定を保存しました")
    
    def toggle_autostart(self):
        """自動起動の切り替え"""
        if self.autostart_var.get():
            self.enable_autostart()
        else:
            self.disable_autostart()
    
    def enable_autostart(self):
        """自動起動を有効化"""
        try:
            startup_folder = winshell.startup()
            shortcut_path = os.path.join(startup_folder, "ContextCollector.lnk")
            target = sys.executable if getattr(sys, 'frozen', False) else os.path.abspath(__file__)
            
            shell = Dispatch('WScript.Shell')
            shortcut = shell.CreateShortCut(shortcut_path)
            shortcut.Targetpath = target
            shortcut.WorkingDirectory = os.path.dirname(target)
            shortcut.IconLocation = target
            shortcut.save()
            
            self.log("自動起動を有効化しました")
        except Exception as e:
            self.log(f"自動起動の有効化に失敗: {e}")
            messagebox.showerror("エラー", f"自動起動の設定に失敗しました: {e}")
    
    def disable_autostart(self):
        """自動起動を無効化"""
        try:
            startup_folder = winshell.startup()
            shortcut_path = os.path.join(startup_folder, "ContextCollector.lnk")
            
            if os.path.exists(shortcut_path):
                os.remove(shortcut_path)
            
            self.log("自動起動を無効化しました")
        except Exception as e:
            self.log(f"自動起動の無効化に失敗: {e}")
    
    def log(self, message: str):
        """ログを記録"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_message = f"[{timestamp}] {message}\n"
        print(log_message.strip())
        
        if hasattr(self, 'log_text') and self.root:
            try:
                self.log_text.insert(tk.END, log_message)
                self.log_text.see(tk.END)
            except:
                pass
    
    def collect_now(self):
        """今すぐ収集を実行"""
        if self.is_collecting:
            self.log("既に収集中です")
            return
        
        if not self.config.config['keywords']:
            self.log("キーワードが設定されていません")
            if self.root:
                messagebox.showwarning("警告", "キーワードが設定されていません。設定画面から追加してください。")
            return
        
        thread = threading.Thread(target=self.collect_data, daemon=True)
        thread.start()
    
    def sanitize_filename(self, filename: str) -> str:
        """ファイル名/フォルダ名として使用できない文字を除去"""
        # Windowsで使用できない文字を置換
        invalid_chars = ['\\', '/', ':', '*', '?', '"', '<', '>', '|']
        for char in invalid_chars:
            filename = filename.replace(char, '_')
        
        # 前後の空白とピリオドを削除
        filename = filename.strip('. ')
        
        return filename
    
    def should_collect(self, keyword: str) -> bool:
        """収集が必要かどうかを判定（同一日に収集済みならスキップ）"""
        last_check = self.config.config['last_check'].get(keyword)
        
        if last_check is None:
            # 初回は必ず収集
            return True
        
        try:
            last_check_date = datetime.fromisoformat(last_check).date()
            today = datetime.now().date()
            
            # 日付が変わっていれば収集
            return today > last_check_date
        except:
            # パースエラーの場合は収集
            return True
    
    def collect_data(self):
        """データ収集を実行"""
        self.is_collecting = True
        self.log("=== 収集開始 ===")

        try:
            languages = self.config.config['language'].split(',')
            collected_count = 0
            skipped_count = 0

            for keyword in self.config.config['keywords']:
                self.log(f"キーワード「{keyword}」をチェック中...")

                # 収集が必要かチェック
                if not self.should_collect(keyword):
                    self.log(f"  本日は収集済み - スキップ")
                    skipped_count += 1
                    continue

                # 初回か通常収集かを判定
                last_check = self.config.config['last_check'].get(keyword)
                if last_check is None:
                    days = self.config.config['initial_days']
                    self.log(f"  初回収集: 過去{days}日分")
                else:
                    days = 1
                    self.log(f"  通常収集: 過去24時間")

                # データ収集
                results = self.collector.collect_all(keyword, days, languages)
                self.log(f"  収集完了: {len(results)}件")

                # Markdown生成
                if results:
                    # ファイル名として安全な名前に変換
                    safe_keyword = self.sanitize_filename(keyword)
                    today = datetime.now().strftime('%Y-%m-%d')

                    # outputs直下にファイルを保存（キーワード-日付.md）
                    output_file = self.output_dir / f"{safe_keyword}-{today}.md"

                    # 絶対パスを表示
                    abs_path = output_file.absolute()
                    self.log(f"  保存先: {abs_path}")

                    md_content = MarkdownGenerator.generate(
                        keyword,
                        results,
                        datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    )

                    with open(output_file, 'w', encoding='utf-8') as f:
                        f.write(md_content)

                    self.log(f"  保存完了: {output_file.name}")
                    self.log(f"  ファイルサイズ: {output_file.stat().st_size} bytes")

                    # データベースに記事を保存
                    self.log(f"  データベースに保存中...")
                    saved_count = 0
                    for result in results:
                        try:
                            url = result.get('url', '')
                            title = result.get('title', '')
                            snippet = result.get('snippet', '')
                            published_date = result.get('date', '')
                            source = result.get('source', '')

                            # URLの正規化
                            normalized_url = url.lower().strip()
                            if '?' in normalized_url:
                                normalized_url = normalized_url.split('?')[0]

                            # データベースに追加
                            article_id = self.db.add_article(
                                url=url,
                                title=title,
                                snippet=snippet,
                                content='',  # 本文は後で手動で追加
                                normalized_url=normalized_url,
                                source=source,
                                keywords=keyword,
                                published_date=published_date
                            )
                            if article_id:
                                saved_count += 1
                        except Exception as e:
                            self.log(f"    記事保存エラー: {title[:30]}... - {e}")

                    self.log(f"  データベース保存完了: {saved_count}/{len(results)}件")
                    collected_count += 1
                else:
                    self.log(f"  新しい情報はありませんでした")

                # 最終チェック時刻を更新
                self.config.config['last_check'][keyword] = datetime.now().isoformat()
                self.config.save_config()

            self.log(f"=== 収集完了 ===")
            self.log(f"収集: {collected_count}件 / スキップ: {skipped_count}件")

            # HTML変換を実行（本日収集したデータがある場合）
            if collected_count > 0:
                self.log("")
                self.log("=== HTML変換を開始 ===")
                try:
                    HTMLConverter.convert_markdown_to_html(
                        input_dir=self.output_dir,
                        output_dir=self.reports_dir,
                        today_only=True,
                        log_func=self.log,
                        stock_resolver=self.stock_resolver
                    )
                except Exception as e:
                    self.log(f"HTML変換エラー: {e}")
                    import traceback
                    self.log(traceback.format_exc())

            # 通知
            if self.tray_icon:
                if collected_count > 0:
                    self.tray_icon.notify("収集完了", f"{collected_count}件のキーワードを収集しました")
                else:
                    self.tray_icon.notify("収集スキップ", "本日は全て収集済みです")

            # 起動時の自動収集が完了したら終了
            if self.auto_exit_after_startup:
                self.log("起動時の自動収集が完了しました。3秒後にアプリケーションを終了します...")
                time.sleep(3)  # 通知を表示する時間を確保
                self.quit_app()

        except Exception as e:
            self.log(f"エラー: {e}")
            import traceback
            self.log(traceback.format_exc())

            # エラーが発生した場合も自動終了する
            if self.auto_exit_after_startup:
                self.log("エラーが発生しましたが、自動終了します...")
                time.sleep(3)
                self.quit_app()

        finally:
            self.is_collecting = False
    
    def check_and_collect(self, is_startup=False):
        """定期チェックして必要なら収集"""
        # いずれかのキーワードで収集が必要かチェック
        should_run = False
        for keyword in self.config.config['keywords']:
            if self.should_collect(keyword):
                should_run = True
                break

        if should_run:
            self.log("定期チェック: 収集を開始します")
            if is_startup:
                self.auto_exit_after_startup = True
            self.collect_now()
        else:
            self.log("定期チェック: 本日は全て収集済み")
            # 起動時に収集不要な場合も終了
            if is_startup:
                self.log("起動時チェック: 本日は全て収集済みのため終了します...")
                time.sleep(2)
                self.quit_app()
    
    def quit_app(self, icon=None, item=None):
        """アプリケーションを終了"""
        if self.tray_icon:
            self.tray_icon.stop()
        if self.root:
            self.root.quit()
        sys.exit(0)
    
    def run_tkinter(self):
        """Tkinterのメインループを実行"""
        self.root = tk.Tk()
        self.root.title("コンテキスト収集 - 設定")
        self.root.geometry("600x500")
        self.root.protocol("WM_DELETE_WINDOW", self.hide_window)
        self.root.withdraw()  # 最初は非表示
        
        self.create_settings_ui()
        self.process_commands()
        
        self.root.mainloop()
    
    def run(self):
        """アプリケーションを実行"""
        # Tkinterを別スレッドで起動
        tk_thread = threading.Thread(target=self.run_tkinter, daemon=True)
        tk_thread.start()
        
        # Tkinterが起動するまで待機
        time.sleep(1)
        
        # トレイアイコン作成
        self.create_tray_icon()
        
        # 起動時に即座にチェック（日付が変わっていれば収集）
        if self.config.config['keywords']:
            self.log("起動時チェックを実行します...")
            check_thread = threading.Thread(target=lambda: self.check_and_collect(is_startup=True), daemon=True)
            check_thread.start()
        
        # バックグラウンドで定期チェック（1時間ごと）
        def periodic_check():
            while True:
                time.sleep(3600)  # 1時間ごとにチェック
                self.check_and_collect()
        
        check_thread = threading.Thread(target=periodic_check, daemon=True)
        check_thread.start()
        
        # トレイアイコン実行
        self.tray_icon.run()

if __name__ == "__main__":
    app = ContextCollectorApp()
    app.run()
