@echo off
REM ============================================================
REM  POS exe LOAD TEST - one click
REM  Edit MODE / CUSTOMERS / ITEMS below, then double-click.
REM ============================================================
setlocal
set MODE=online
set CUSTOMERS=4
set ITEMS=30

cd /d "%~dp0"
set PY="%~dp0..\venv\Scripts\python.exe"
if not exist %PY% set PY=python

echo Running POS load test:  mode=%MODE%  customers=%CUSTOMERS%  items/sale=%ITEMS%
echo (do not touch the mouse/keyboard while it runs)
%PY% "%~dp0load_test.py" --mode %MODE% --customers %CUSTOMERS% --items %ITEMS%

echo.
echo Done. Press any key to close.
pause >nul
