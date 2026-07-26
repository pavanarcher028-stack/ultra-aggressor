@echo off
REM ============================================================
REM ULTIMATE AGGRESSOR - Paper Trading Launcher (Local)
REM ============================================================
REM This runs the paper agent 24/7 and auto-restarts if it crashes.
REM Close the window to stop.
REM ============================================================
cd /d "C:\Users\natar\Downloads\backtesting only 1.0"

:MENU
cls
echo ============================================
echo   ULTIMATE AGGRESSOR - PAPER TRADING MENU
echo ============================================
echo   1. Start Paper Agent (silent background)
echo   2. Start Paper Agent + Dashboard (web UI)
echo   3. Start Dashboard only
echo   4. Stop all agents
echo   5. View logs
echo   6. Setup wallet
echo   7. Exit
echo ============================================
set /p choice="Choice [1-7]: "

if "%choice%"=="1" goto START_AGENT
if "%choice%"=="2" goto START_BOTH
if "%choice%"=="3" goto START_DASHBOARD
if "%choice%"=="4" goto STOP_ALL
if "%choice%"=="5" goto VIEW_LOGS
if "%choice%"=="6" goto SETUP
if "%choice%"=="7" goto EXIT
goto MENU

:START_AGENT
cls
echo Starting paper agent in background...
echo Logs will be saved to paper_agent.log
echo.
start /B /MIN pythonw.exe -c ^
"import sys,os,time,json; sys.path.insert(0,'.'); from production_aggressor import ProductionAggressor; ^
agent=ProductionAggressor(paper_mode=True); ^
if agent.setup_wallet(): ^
  agent.start_agent(); ^
  while True: ^
    time.sleep(60); ^
    s=agent.engine.summary(); ^
    with open('paper_status.json','w') as f: json.dump(s,f);"
echo Agent started! 
echo To view status: type 5
pause
goto MENU

:START_BOTH
cls
echo Starting agent + dashboard...
echo Dashboard: http://localhost:8765
echo.
start /B /MIN pythonw.exe -c ^
"import sys; sys.path.insert(0,'.'); from production_aggressor import ProductionAggressor; ^
agent=ProductionAggressor(paper_mode=True); ^
if agent.setup_wallet(): ^
  agent.start_agent(); ^
  import uvicorn; ^
  from production_aggressor import create_prod_dashboard, AGENT_STATE, AGENT_LOCK; ^
  with AGENT_LOCK: AGENT_STATE['agent']=agent; AGENT_STATE['running']=True; ^
  uvicorn.run(create_prod_dashboard(), host='0.0.0.0', port=8765, log_level='warning')"
echo Dashboard started at http://localhost:8765
echo Close this window to stop everything.
pause
goto MENU

:START_DASHBOARD
cls
echo Starting dashboard on http://localhost:8765
python production_aggressor.py --dashboard
pause
goto MENU

:STOP_ALL
cls
echo Stopping all agents...
taskkill /f /im pythonw.exe 2>nul
taskkill /f /im python.exe 2>nul
echo Done.
pause
goto MENU

:VIEW_LOGS
cls
if exist paper_agent.log (
    echo Last 30 lines of paper_agent.log:
    echo ================================
    powershell -command "Get-Content paper_agent.log -Tail 30"
) else (
    echo No log file found.
)
if exist paper_status.json (
    echo.
    echo Current Status:
    powershell -command "Get-Content paper_status.json | ConvertFrom-Json | Format-List"
)
echo.
pause
goto MENU

:SETUP
cls
python production_aggressor.py --setup
pause
goto MENU

:EXIT
exit /b
