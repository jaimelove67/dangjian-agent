@echo off
setlocal
pushd "%~dp0.."
set "PYTHON_EXE=python"
if exist ".venv\Scripts\python.exe" set "PYTHON_EXE=%CD%\.venv\Scripts\python.exe"
if defined PARTY_PYTHON set "PYTHON_EXE=%PARTY_PYTHON%"
if not exist "frontend\node_modules" (
    echo Run npm ci in frontend before starting.
    popd
    exit /b 1
)
"%PYTHON_EXE%" -c "import uvicorn, fastapi"
if errorlevel 1 (
    echo Install requirements.txt in the selected Python environment first.
    popd
    exit /b 1
)
start "Party Agent Backend" cmd /k ""%PYTHON_EXE%" -m uvicorn app.main:app --host 127.0.0.1 --port 8000"
for /l %%i in (1,1,20) do (
    curl -fsS http://127.0.0.1:8000/api/v1/health/live >nul 2>nul
    if not errorlevel 1 goto backend_ready
    timeout /t 1 /nobreak >nul
)
echo Backend did not start. Check its console.
popd
exit /b 1
:backend_ready
pushd frontend
start "Party Agent Frontend" cmd /k "npm run dev -- --host 127.0.0.1 --port 5666 --strictPort"
popd
echo Frontend: http://127.0.0.1:5666
echo Readiness: http://127.0.0.1:8000/api/v1/health/ready
echo Close the two service consoles to stop them.
popd
endlocal
