@echo off
setlocal
set "PYTHONUTF8=1"
pushd "%~dp0"
if errorlevel 1 goto folder_error
if not exist "start_quote_bridge.py" goto files_missing
if not exist "windows_worker.py" goto files_missing

where py.exe >nul 2>nul
if errorlevel 1 goto try_python
py -3 -c "import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>nul
if errorlevel 1 goto try_python
py -3 -u start_quote_bridge.py
goto worker_finished

:try_python
where python.exe >nul 2>nul
if errorlevel 1 goto python_missing
python -c "import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>nul
if errorlevel 1 goto python_missing
python -u start_quote_bridge.py

:worker_finished
if not errorlevel 1 goto finish
echo.
echo [ERROR] The bridge stopped. See the message above before closing this window.
goto finish

:files_missing
echo [ERROR] Extract all files from the ZIP before opening Start_Quote_Bridge.cmd.
goto finish

:python_missing
echo [ERROR] Python 3.11 or later was not found. Install Python for Windows, then reopen this file.
goto finish

:folder_error
echo [ERROR] Could not open the bridge folder.
echo.
pause
exit /b 1

:finish
popd
echo.
pause
