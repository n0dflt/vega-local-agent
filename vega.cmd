@echo off
setlocal
chcp 65001 > nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"

if defined VEGA_PYTHON if exist "%VEGA_PYTHON%" (
    "%VEGA_PYTHON%" .\scripts\vega.py
    exit /b %ERRORLEVEL%
)

if exist "%~dp0.runtime\python.exe" (
    "%~dp0.runtime\python.exe" .\scripts\vega.py
    exit /b %ERRORLEVEL%
)

if defined VIRTUAL_ENV if exist "%VIRTUAL_ENV%\Scripts\python.exe" (
    "%VIRTUAL_ENV%\Scripts\python.exe" .\scripts\vega.py
    exit /b %ERRORLEVEL%
)

if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" .\scripts\vega.py
    exit /b %ERRORLEVEL%
)

for %%I in (py.exe) do if not "%%~$PATH:I"=="" (
    py -3 .\scripts\vega.py
    exit /b %ERRORLEVEL%
)

for %%I in (python.exe) do if not "%%~$PATH:I"=="" (
    python .\scripts\vega.py
    exit /b %ERRORLEVEL%
)

>&2 echo VEGA could not find Python. Set VEGA_PYTHON, activate a virtual environment, or install the Python launcher.
exit /b 1
