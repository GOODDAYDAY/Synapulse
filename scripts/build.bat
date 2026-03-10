@echo off
chcp 65001 >nul
REM Build check — verify all Python files compile without syntax errors
REM Prerequisite: Python 3.11+

echo Checking Python syntax...
python -m py_compile apps/bot/main.py
python -m py_compile apps/bot/core/handler.py
python -m py_compile apps/bot/core/mention.py
python -m py_compile apps/bot/core/reminder.py
python -m py_compile apps/bot/core/loader.py
python -m py_compile apps/bot/memory/database.py
python -m py_compile apps/bot/tool/memo/handler.py
python -m py_compile apps/bot/tool/reminder/handler.py
python -m py_compile apps/bot/tool/task/handler.py
python -m py_compile apps/bot/tool/brave_search/handler.py
python -m py_compile apps/bot/tool/local_files/handler.py
python -m py_compile apps/bot/config/settings.py
python -m py_compile apps/bot/config/prompts.py
echo Build check passed.
