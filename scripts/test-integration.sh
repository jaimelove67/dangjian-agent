#!/bin/bash
# 前后端联调快速测试脚本

echo "🚀 开始前后端联调测试..."
echo ""

# 测试后端健康检查
echo "1️⃣ 测试后端健康检查..."
HEALTH_RESPONSE=$(curl -s http://localhost:8000/api/v1/health)
if [ $? -eq 0 ]; then
    echo "✅ 后端服务正常运行"
    echo "   响应: $HEALTH_RESPONSE"
else
    echo "❌ 后端服务未启动或无法访问"
    echo "   请先启动后端: uvicorn app.main:app --reload --port 8000"
    exit 1
fi
echo ""

# 测试登录接口
echo "2️⃣ 测试登录接口..."
LOGIN_RESPONSE=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}')
echo "   响应: $LOGIN_RESPONSE"
echo ""

# 提取 access_token（如果登录成功）
ACCESS_TOKEN=$(echo $LOGIN_RESPONSE | grep -o '"access_token":"[^"]*"' | sed 's/"access_token":"\(.*\)"/\1/')
if [ ! -z "$ACCESS_TOKEN" ]; then
    echo "✅ 登录成功，获取到 token"

    # 测试获取用户信息
    echo ""
    echo "3️⃣ 测试获取用户信息..."
    USER_INFO=$(curl -s http://localhost:8000/api/v1/user/info \
      -H "Authorization: Bearer $ACCESS_TOKEN")
    echo "   响应: $USER_INFO"

    # 测试获取权限码
    echo ""
    echo "4️⃣ 测试获取权限码..."
    CODES=$(curl -s http://localhost:8000/api/v1/auth/codes \
      -H "Authorization: Bearer $ACCESS_TOKEN")
    echo "   响应: $CODES"
else
    echo "⚠️  登录失败或用户不存在"
    echo "   请先创建测试用户，或检查用户名密码"
fi

echo ""
echo "✨ 测试完成！"
echo ""
echo "📌 前端访问地址: http://localhost:5666"
echo "📌 后端API文档: http://localhost:8000/docs"
