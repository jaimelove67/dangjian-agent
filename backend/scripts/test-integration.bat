@echo off
REM 前后端联调快速测试脚本 (Windows)

echo 🚀 开始前后端联调测试...
echo.

REM 测试后端健康检查
echo 1️⃣ 测试后端健康检查...
curl -s http://localhost:8000/api/v1/health
if %errorlevel% equ 0 (
    echo ✅ 后端服务正常运行
) else (
    echo ❌ 后端服务未启动或无法访问
    echo    请先启动后端: uvicorn app.main:app --reload --port 8000
    exit /b 1
)
echo.

REM 测试登录接口
echo 2️⃣ 测试登录接口...
curl -s -X POST http://localhost:8000/api/v1/auth/login ^
  -H "Content-Type: application/json" ^
  -d "{\"username\":\"admin\",\"password\":\"admin123\"}"
echo.

echo.
echo ✨ 基础测试完成！
echo.
echo 📌 前端访问地址: http://localhost:5666
echo 📌 后端API文档: http://localhost:8000/docs
echo.
pause
