@echo off
REM Usage: double-click this, or run from terminal:
REM   upload_my_topic.bat "your topic here" public
REM If you omit the privacy argument, it defaults to private (recommended).

if "%~1"=="" (
    echo Usage: upload_my_topic.bat "your topic here" [public/unlisted/private]
    pause
    exit /b
)

set TOPIC=%~1
set PRIVACY=%~2
if "%PRIVACY%"=="" set PRIVACY=private

call venv\Scripts\activate.bat
python main.py --topic "%TOPIC%" --privacy %PRIVACY%

pause
