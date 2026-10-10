#!/bin/bash
# 安装所有后端依赖

echo "📦 安装后端依赖..."
cd "$(dirname "$0")/.."

pip install -r requirements.txt

echo "✅ 依赖安装完成！"
