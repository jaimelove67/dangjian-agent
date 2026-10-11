> 历史归档：本文保留生成时的结论与环境信息。当前功能见[项目状态](../../STATUS.md)，测试见[测试指南](../../TESTING.md)。

# PR #21 合并冲突解决指南

## 问题描述

PR #21 (Day3+4-DevB 检索模块 + 问答API) 存在合并冲突，无法自动合并到master分支。

## 冲突原因

PR #21包含大量新增文件（检索和问答模块），可能与master分支上的其他提交存在冲突，特别是：
- `app/main.py` 的路由注册部分
- 可能的依赖冲突

## 解决方案

### 方案1: 在GitHub Web界面解决（推荐）

1. 访问 https://github.com/jaimelove67/dangjian-agent/pull/21
2. 点击 "Resolve conflicts" 按钮
3. GitHub会显示冲突的文件
4. 手动编辑解决冲突（通常是保留两边的更改）
5. 标记为已解决
6. 提交解决结果
7. 合并PR

### 方案2: 本地命令行解决

```bash
# 1. 确保本地master是最新的
git checkout master
git pull origin master

# 2. 切换到PR分支
git fetch origin feature/day3-devb-retrieval
git checkout feature/day3-devb-retrieval

# 3. 合并master到PR分支
git merge master

# 4. 解决冲突
# Git会提示哪些文件有冲突，手动编辑这些文件
# 查找 <<<<<<< HEAD 和 >>>>>>> master 标记
# 保留需要的代码，删除冲突标记

# 5. 标记冲突已解决
git add <冲突文件>

# 6. 完成合并
git commit -m "Merge master into feature/day3-devb-retrieval"

# 7. 推送更新
git push origin feature/day3-devb-retrieval

# 8. PR会自动更新，可以合并了
```

### 方案3: 创建新的PR（如果冲突太复杂）

```bash
# 1. 从最新的master创建新分支
git checkout master
git pull origin master
git checkout -b feature/retrieval-qa-v2

# 2. 手动复制PR #21中的所有新文件
# 从 feature/day3-devb-retrieval 分支复制：
# - app/rag/retrieval/*.py
# - app/services/retrieval_service.py
# - app/services/qa_service.py
# - app/schemas/retrieval.py
# - app/schemas/qa.py
# - app/api/v1/qa.py

# 3. 更新 app/main.py
# 添加 QA 路由注册

# 4. 提交并推送
git add .
git commit -m "feat(retrieval,qa): 重新提交检索和问答模块"
git push origin feature/retrieval-qa-v2

# 5. 创建新PR
gh pr create --title "feat(retrieval,qa): Day3+4-DevB 检索与问答（重新提交）" --base master

# 6. 关闭旧PR #21
gh pr close 21 --comment "已通过新PR重新提交以解决冲突"
```

## 预期冲突文件

最可能发生冲突的文件：
- `app/main.py` - 路由注册部分
- 可能有其他文件在master上被修改过

## 冲突解决策略

对于 `app/main.py`：
```python
# 保留所有路由注册
app.include_router(health.router, prefix="/api/v1", tags=["健康检查"])
app.include_router(auth.router, prefix="/api/v1", tags=["鉴权"])
app.include_router(user.router, prefix="/api/v1", tags=["用户"])
app.include_router(knowledge.router, prefix="/api/v1", tags=["知识库"])
app.include_router(qa.router, prefix="/api/v1", tags=["知识问答"])  # 添加这一行
```

## 验证步骤

解决冲突后，验证：
1. 代码能正常运行
2. 所有测试通过
3. API接口可访问

## 当前状态

- ✅ 所有代码已开发完成
- ✅ 所有Issue已关闭
- ⚠️ PR #21需要解决冲突才能合并

## 建议

**最快的解决方案是方案1（GitHub Web界面）**，因为：
- 可视化界面更容易操作
- 自动检测冲突位置
- 不需要本地环境配置

---

**注意**: 由于网络问题，目前无法通过命令行推送到GitHub。建议：
1. 使用GitHub Web界面解决冲突（方案1）
2. 或者在网络恢复后使用命令行（方案2）
