@echo off
REM コンテキスト収集＋GitHub Pagesデプロイ（自動実行用）
cd /d "%~dp0"

set PYTHON=C:\Python314\python.exe
set PYTHONPATH=C:\Users\hisas\AppData\Roaming\Python\Python314\site-packages;C:\Python314\Lib\site-packages
set PYTHONIOENCODING=utf-8

REM ログファイルにタイムスタンプを記録
echo ====================================== >> run_collection.log
echo 実行日時: %date% %time% >> run_collection.log
echo ====================================== >> run_collection.log

REM Step 1: コンテキスト収集
echo [Step 1] Context.py 実行中... >> run_collection.log
"%PYTHON%" "%~dp0Context.py" >> run_collection.log 2>&1
echo 終了コード: %ERRORLEVEL% >> run_collection.log

REM Step 2: GitHub Pages デプロイ
echo [Step 2] publish_to_github.py 実行中... >> run_collection.log
"%PYTHON%" "%~dp0publish_to_github.py" >> run_collection.log 2>&1
echo 終了コード: %ERRORLEVEL% >> run_collection.log

echo. >> run_collection.log

exit
