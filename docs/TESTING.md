# 测试指南

文档更新日期：2026-10-11。测试代码与样本保留在 `tests/`，历史测试报告见[归档](archive/README.md)。本次只执行文档一致性核对，没有重新运行后端、构建或浏览器业务回归；以下测试数字保留原执行日期和被测工作区，不能视为当前新执行结果。

## 执行命令

安装 `requirements-dev.txt`，从项目根目录使用同一 Python 环境执行：

```bash
python -m pytest tests/unit/
python -m pytest tests/integration/
python -m pytest tests/security/
python -m pytest
```

PowerShell 中可在测试进程启动前设置：

```powershell
$env:DASHSCOPE_API_KEY = ''
$env:QWEN_API_KEY = ''
python -m pytest tests/unit tests/security
```

Linux/macOS 使用 `DASHSCOPE_API_KEY= QWEN_API_KEY= python -m pytest tests/unit tests/security`。这些设置不改写 `.env`；真实模型评测另用已授权的环境。

单元与安全回归主要使用合成输入及替代模型。完整回归需要可用的 PostgreSQL；数据库迁移测试检查已迁移的目标库，`test_repaired_storage.py` 还需要连接管理库并创建、清理随机独立测试库的权限。请配置专用测试数据库连接。

自动化回归应在测试进程中将 `DASHSCOPE_API_KEY` 和兼容变量 `QWEN_API_KEY` 覆盖为空，保持本地 `.env` 不变。检查失败数和跳过数；缺少依赖或数据库导致的跳过不能计为验收通过。

## 生成测试产物

```bash
python -c "from pathlib import Path; Path('tmp/test-results').mkdir(parents=True, exist_ok=True)"
python -m pytest --junitxml=tmp/test-results/pytest.xml --cov=app --cov-report=term-missing --cov-report=html:tmp/test-results/coverage --cov-report=json:tmp/test-results/coverage.json
```

日志、覆盖率与机器可读结果统一写入已忽略的 `tmp/test-results/`。有必要保留验收证据时，在本指南记录结果及证据位置。

前端验证在正式工程中执行：

```bash
npm --prefix frontend run typecheck
npm --prefix frontend run build
```

三个浏览器工作流从 `frontend/` 执行：

```bash
node tests/business-workflows.mjs
node tests/study-workflows.mjs
node tests/assessment-workflows.mjs
```

流程使用合成 API 响应；需要可用的 Playwright Chromium，可通过 `PLAYWRIGHT_CHROMIUM_EXECUTABLE` 指定。`frontend/scripts/screenshot-pages.mjs` 使用拦截响应生成设计截图，适合版面检查；真实业务联调需要实际后端、数据库、Redis 与模型调用。

## 业务评测

后端就绪后，通过进程环境变量 `EVALUATION_ACCESS_TOKEN` 提供已有登录令牌，再执行：

```bash
python tests/evaluation/run_evaluation.py --base-url http://127.0.0.1:8000/api/v1 --output tmp/test-results/evaluation.json
```

评测器请求真实检索与问答接口；会产生模型调用。缺令牌、未就绪或调用失败返回阻塞/失败，退出码为 2。默认输出目录 `tests/evaluation/results/` 也已加入忽略规则。

当前 `tests/evaluation/qa_samples.json` 的问答样本为 20 条，其中拒答 6 条、时效 0 条，尚未达到验收要求的 200/30/20。关键词命中不能代替专家答案正确性审查，串行请求延迟不能代替负载性能。

## 已有验证记录

最近记录日期：2026-10-10；被测对象为当时的本地工作区，包含未提交修改。来源为[修复记录](archive/2026-10-10/PROJECT_REPAIR_2026-10-10.md)和[云端联调记录](archive/2026-10-10/MODEL_INTEGRATION_2026-10-10.md)。

| 检查 | 此前记录 | 范围 |
| --- | --- | --- |
| 完整 pytest | 306 通过、0 失败、0 跳过；分支覆盖率合计 78.00% | Python 3.13.9，部分共享依赖不同于锁定版本 |
| 前端构建 | 正式前端与登录测试前端通过 | 类型检查与生产构建 |
| 浏览器联调 | 基础 14 项、云端 9 项通过，页面异常 0 | 正式页面、实际后端与独立测试库；云端阶段使用合成资料 |
| 三个模型 | 聊天、1024 维向量及重排实际调用通过 | 仅覆盖当时配置与合成输入 |
| 静态与配置检查 | 57 个 Python 文件格式/风格、两套 Compose 配置及 Bash 语法通过 | 未执行生产构建或部署 |
| mypy | 前置检查未通过 | SQLAlchemy 插件缺失，未进入业务代码分析 |

完整日志与截图的位置保留在上述归档记录中。真实业务质量与专家复核、负载测试、锁定依赖的干净 Python 3.11 环境、生产镜像和备份恢复仍未验收。

## 最新业务整合回归

2026-10-10 的整合工作区完成以下检查；来源与边界见[整合记录](LOCAL_FIX_AND_SELECTED_INTEGRATION_2026-10-10.md)。

- `python -m pytest tests -o addopts= -q --tb=short`：339 通过、1 跳过，跳过原因是当前环境缺少 `pypdf`。测试进程清空云端密钥，数据库测试使用随机独立 PostgreSQL 库。
- 正式前端类型检查与生产构建通过。
- `node tests/business-workflows.mjs`：在 `frontend/` 中执行，四组浏览器流程通过，覆盖名册、流转参数、软删除与历史会话；API 使用合成响应。
- 开发库升级至 `005`，原六张核心表数据摘要一致；实际 Redis 7 认证读写探针通过。

浏览器脚本可用 `PLAYWRIGHT_CHROMIUM_EXECUTABLE` 指定已有 Chromium，截图默认写入 `tmp/`。最新整合没有重新调用真实云模型，也没有以真实账号进行人工验收。

## 模块5与共用业务回归

2026-10-10 当前工作区完成全项目 `pytest`：409通过、0失败、1跳过，跳过原因为缺少 `pypdf`。模块5包含17项规则及18项真实HTTP/独立数据库测试，覆盖权限、期间、去重、组织转接、源版本、审核、提醒、归档及导出；迁移升级/回滚保留既有文档。结果位于 `tmp/test-results/assessment-regression.xml`。

前端类型与生产构建通过。在 `frontend/` 执行 `node tests/assessment-workflows.mjs` 的7组浏览器流程通过；接口使用合成响应，截图位于 `tmp/test-results/assessment-browser/`。真实学校指标、组织认可的人工台账对照及现有业务库迁移未验收，详见[模块5记录](MODULE5_ASSESSMENT_2026-10-10.md)。

## 中心组学习回归（模块4）

2026-10-10，模块4本地实现、隔离数据库迁移及正式前端验证见[实现与验收记录](MODULE4_STUDY_2026-10-10.md)。测试进程不读取云端密钥，数据库用例使用随机独立测试库；没有改动业务库。

模块4回归执行 `python -m pytest tests/unit/test_study_minutes.py tests/integration/test_study_workflow.py`；正式页面从 `frontend/` 执行 `node tests/study-workflows.mjs`。浏览器API使用合成响应，覆盖年度计划、材料提纲、不同审核人、参学与原文纪要、归档门禁、可读导出、历史统计、请求重试和移动布局。学校真实组织、电子效力确认及用户验收仍待完成。

## 审查分支记录的适用范围

[模块4/5审查](MODULE4_MODULE5_REVIEW_2026-10-10.md)记录独立分支 `codex/modules4-5-review-20261010` 的最终整合：422通过、0失败、1跳过，缺少 `pypdf`；未验证覆盖率、mypy、锁定Python3.11环境或生产部署。这是历史分支结果，本次没有重跑或将其视为当前工作区验收。

[模块1—3审查](MODULE1_MODULE2_MODULE3_REVIEW_2026-10-10.md)针对另一固定上传版本和独立修补分支，包含本工作区没有的文件存储、全流程党员发展与独立组织生活代码。报告的测试数和修补不能直接套用到当前项目。以实际检出的代码、明确版本和新执行日志为准。
