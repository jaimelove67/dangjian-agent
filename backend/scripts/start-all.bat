@echo off
setlocal
pushd "%~dp0..\.."
node scripts\dev.mjs all %*
set "DANGJIAN_EXIT_CODE=%ERRORLEVEL%"
popd
exit /b %DANGJIAN_EXIT_CODE%
