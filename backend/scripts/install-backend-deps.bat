@echo off
REM 安装所有后端依赖

echo 📦 安装后端依赖...
cd %~dp0..

python -m pip install -r requirements.txt

echo ✅ 依赖安装完成！
pause
