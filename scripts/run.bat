@echo off
chcp 65001 >nul
REM Start the Synapulse bot
REM Prerequisite: Python 3.11+, .env configured

echo Starting Synapulse...
python -m apps.bot.main
