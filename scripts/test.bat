@echo off
chcp 65001 >nul
REM Run all tests
REM Prerequisite: Python 3.11+, pytest installed

echo Running tests...
python -m pytest tests/ -v
echo Tests completed.
