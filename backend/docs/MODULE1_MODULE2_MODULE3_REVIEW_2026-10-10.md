# 模块1—3上传核对与代码审核

日期：2026-10-10（Asia/Shanghai）。结论：**三个模块的新提交均已上传到主分支，但当前远端版本不能通过整体验收。** 已复现的安全和局部业务缺陷已在本地独立审查分支修补；正式页面和质量评测仍有需求缺口。

## 上传与审核范围

仓库：<https://github.com/jaimelove67/dangjian-agent>。审核开始及结束核对到的远端 `master` 均为 `8d2eb1f22784bb0a9fd3a4d3074c91d51b06a053`。未发现模块1—3对应的新 PR；代码直接位于主分支。

| 模块 | 原始需求 | 已上传提交 | 本次主要增量 |
| --- | --- | --- | --- |
| 1：知识库与问答 | [#25](https://github.com/jaimelove67/dangjian-agent/issues/25) | [8d2eb1f](https://github.com/jaimelove67/dangjian-agent/commit/8d2eb1f22784bb0a9fd3a4d3074c91d51b06a053) | 原始文件留存/下载、处理状态、元数据维护、40条评测样本 |
| 2：发展党员全流程 | [#26](https://github.com/jaimelove67/dangjian-agent/issues/26) | [9721867](https://github.com/jaimelove67/dangjian-agent/commit/9721867) | 年度批次、材料、人工流转、提醒、培养、投票、评分及档案检查 API |
| 3：组织生活与三会一课 | [#27](https://github.com/jaimelove67/dangjian-agent/issues/27) | [e9b2dc5](https://github.com/jaimelove67/dangjian-agent/commit/e9b2dc5) | 活动、议程、纪要审核、任务台账、归档及工作台 |

固定比较基线为刚完成模块4/5合并的 `05bbc4a35522e1f1a6bf4c2f9039a9e6ded4d392`。命令：`git diff 05bbc4a...8d2eb1f`，原始增量27个文件、5229行新增、28行删除。需求全文从 GitHub 读取，并在独立工作区 `tmp/review-context/issue-{25,26,27}.md` 留存。

规范来源：`开发规范文档.md`、`党建工作智能体_LangChain实现项目文档.md`、`docs/CODE_REVIEW.md`、`docs/TEST_PLAN.md`、`pyproject.toml`。以下源代码行号引用固定的上传版本 `8d2eb1f`，不会随本地修补改变。

## Standards

规范轴主要发现 **6项，最高P1**；均已在本地修补并复核。远端未更新，仍包含原问题。

| 严重度 | 已确认问题与触发条件 | 规范依据 | 本地修补 |
| --- | --- | --- | --- |
| P1 | [file_store.py:27](https://github.com/jaimelove67/dangjian-agent/blob/8d2eb1f/app/services/file_store.py#L27)：上传标识只限制长度，直接参与路径。Windows 下 `..\\..\\escaped` 可越出租户目录，跨目录读取也能取得其他租户原件。临时目录复现成功。 | 开发规范1.2：租户隔离不可绕过。 | 拒绝路径、驱动器、特殊文件名字符及符号链接；上传提前返回422，读取非法旧标识返回404。正常中文标识及不同版本仍可读取。 |
| P1 | [knowledge.py:627](https://github.com/jaimelove67/dangjian-agent/blob/8d2eb1f/app/api/v1/knowledge.py#L627)：院系管理员可将敏感文档改为 `central/public/public`，成为跨租户公共库内容；修正绕过上传校验。 | 框架9.2：公共库与私有库写入严格分离。 | 校验前锁定并刷新文档；复用完整元数据及公共库权限校验；检查所有留存片段和描述的分级下限。公共原件下载改用已授权文档的真实所属租户。 |
| P1 | [member_service.py:554](https://github.com/jaimelove67/dangjian-agent/blob/8d2eb1f/app/services/member_service.py#L554)：投票仅按租户/批次/轮次查询，返回其他支部对象和投票人；名册及批次计数也缺组织限制。 | 框架9.1：支部书记/组织员仅访问本支部。 | 投票连接人员记录后执行组织过滤；名册和批次人数复用相同组织范围。实际 SQLite 查询验证普通支部及空授权范围。 |
| P1 | [activity_service.py:517](https://github.com/jaimelove67/dangjian-agent/blob/8d2eb1f/app/services/activity_service.py#L517)：关联政策收紧权限后，详情仍返回含原文的议程和任务；独立任务列表/处理路径也可访问。二次复核进一步证实清空资料关联可重新暴露旧正文。 | 框架10.1：角色可见范围。 | 保留正文衍生来源；旧记录从不可覆盖的版本历史补全来源。详情、任务、推荐、纪要生成、审核、归档和历史共同检查；受限响应清空正文、议程与任务摘录，清空资料选择不解除门禁。 |
| P2 | [knowledge.py:534](https://github.com/jaimelove67/dangjian-agent/blob/8d2eb1f/app/api/v1/knowledge.py#L534)：软删除在数据库提交前永久删除全部原件，事务回滚也不能恢复文件。 | 框架7.3：业务数据统一软删除，物理删除走审批。 | 取消原件物理删除，保留文件版本；已删除文档仍由现有授权过滤禁止下载。 |
| P2 | [member_service.py:279](https://github.com/jaimelove67/dangjian-agent/blob/8d2eb1f/app/services/member_service.py#L279)：再次审核覆盖材料状态及意见，理由未保存，无法回查首轮审核。 | 框架10.3：保留审核人、时间和意见。 | 加材料行锁，追加审核前基线及每次 `ContentRevision` 快照；材料列表返回审核历史。验证两名审核人的意见和理由均保留。 |

独立 Standards 复核未发现本次修补的剩余具体阻塞。未把仅由格式化工具强制的风格问题当作审核发现。

## Spec

需求轴主要发现 **7项，最高P1**。3项局部业务错误已修补；以下4项用户闭环和评测缺口仍在。

| 严重度 | 需求与已核实差异 | 状态 |
| --- | --- | --- |
| P1 | [KnowledgeView.vue:4](https://github.com/jaimelove67/dangjian-agent/blob/8d2eb1f/frontend/src/views/KnowledgeView.vue#L4)：#25 M1-02要求“在正式页面完成向量化闭环”，M1-03/04要求元数据维护与原文件访问。正式前端没有处理状态、向量化/重试、元数据修正或原件下载请求。 | **未完成**。后端 API 存在，页面用户仍不能完成新增操作。需要接入正式页面及失败恢复流程。 |
| P1 | [MembersView.vue:4](https://github.com/jaimelove67/dangjian-agent/blob/8d2eb1f/frontend/src/views/MembersView.vue#L4)：#26 M2-12要求年度/批次、详情、材料、流转、提醒、评价/投票、评分与档案检查。全前端没有 `member-full` 请求。 | **未完成**。当前仍是基础登记、校验和建议页面，不能执行新业务。需要补齐整套业务页面。 |
| P1 | [MeetingView.vue:320](https://github.com/jaimelove67/dangjian-agent/blob/8d2eb1f/frontend/src/views/MeetingView.vue#L320)：#27 M3-11要求纪要编辑审核及归档闭环。页面新建不登记参会记录/召开日期，无参会维护，日期输入仅在已有值时出现；保存只提交原文。后端送审要求参会与实际日期。 | **未完成**。页面新建活动无法进入送审/归档。需接入基础记录编辑及持久化，而不是放宽后端审核门禁。 |
| P1 | [member_service.py:294](https://github.com/jaimelove67/dangjian-agent/blob/8d2eb1f/app/services/member_service.py#L294)：#26 M2-04要求材料及时限校验。当天进入积极分子阶段，传一年后的决策日期即可立即流转。 | **本地已修补**。未来决策日期返回422且阶段不变；正常已满365天、当天决策的流转由独立复核确认仍可执行。 |
| P2 | [member_service.py:589](https://github.com/jaimelove67/dangjian-agent/blob/8d2eb1f/app/services/member_service.py#L589)：#26 M2-09要求统计区间和计算过程。`year` 未参与查询，请求2026仍计入2025成绩/风险。 | **本地已修补**。年度模式仅取 `period="2026"` 的成绩和风险，并返回年度。季度、跨年日期范围及空值未被纳入，不能宣称已支持任意统计区间。 |
| P2 | [meeting.py:81](https://github.com/jaimelove67/dangjian-agent/blob/8d2eb1f/app/schemas/meeting.py#L81)：#27 M3-02要求活动计划创建和修订，原代码拒绝未来计划日期。 | **本地已修补**。未来计划可创建/修订，未来实际召开日期仍被拒绝。 |
| P2 | [run_evaluation.py:96](https://github.com/jaimelove67/dangjian-agent/blob/8d2eb1f/tests/evaluation/run_evaluation.py#L96)：#25 M1-06要求扩充并执行至少200条、30拒答及20过期案例。新增文件仅40条（20正常、10拒答、10时效），结构与旧 runner 不一致；runner仍固定加载原20条。 | **未完成**。没有新增样本的实际执行入口和运行证据。需接入评测、扩充经领域复核的样本，再执行真实质量评测。 |

这些需求缺口需要继续业务开发和验收，不以局部安全修补替代。代码已上传也不能据此关闭 #25/#26/#27。

## 其他需求覆盖及验收限制

- 模块1：标签/适用范围的服务端筛选、处理中/失败记录、模型故障体验、流式问答、批准的知识内容基线及参数调优尚无完整交付/验收证据。未执行真实质量或性能评测，不能声称达到正确率或P95目标。
- 模块2：现有提醒仍未覆盖公示、政审全部节点；调度按首个可查询用户的范围扫描，未证明全组织覆盖。评分/选优缺少完整审核与证据快照，规则仅使用固定标识；真实文件关联、组织转接、多年度批次及档案检查准确率仍需全过程核验。
- 模块3：通知已有草稿，未见独立确认发送及通知留痕闭环。任务期限、提醒及完整处理轨迹仍需验收；P2录音整理没有交付证据，不能以预留入口计作完成。
- 三个模块均未完成真实学校资料、组织人员流程确认及人工验收；不操作现有业务数据，不代发组织通知，也不运行未经批准的外部模型路径。

## 实际执行的验证

| 检查 | 实际结果与边界 |
| --- | --- |
| 上传版本全套 `pytest tests` | **334通过、6跳过、98环境错误**。错误的共同根因是配置的本机 PostgreSQL 55432端口连接被拒绝，不能归结为98个代码缺陷，也不能记作全套通过。 |
| 数据库可用性 | Docker引擎未运行；本机 PostgreSQL 5432运行，但现有凭据无法连接。仅作只读探测；未创建或更改该实例业务库。 |
| 修补后 `pytest tests/unit tests/security` | **320通过、1跳过**，其中包含24项新增缺陷回归。PDF解析用例因环境缺少 `pypdf` 跳过。 |
| 新增回归 | 使用实际 SQLite 汇总、年度评分与审核版本SQL，临时文件读写，以及隔离的来源权限对象；24项通过。包含空授权、跨支部投票、未来决策、跨年证据、连续材料审核、路径越界、非法元数据、旧版本敏感正文、清空关联和旧记录来源恢复。 |
| 独立复核 | Standards两次反向检查找到并关闭清空资料关联的漏洞；最终4项离线权限回归通过。Spec核对正常流转、年度风险及计划/实际日期边界。 |
| 前端 | `vue-tsc -b` 与 Vite生产构建通过，148模块。构建通过不代表新增页面操作已接入或真实端到端联调通过。 |
| 工具检查 | 本次6个修补/新增Python文件通过 Black、isort、flake8；`git diff --check`通过。未将此结果扩大到整个仓库。 |
| 工作区保护 | 审查使用独立分支 `codex/modules1-3-review-20261010`；主工作区原暂存区SHA256前后完全一致，未混入其他暂存内容。 |

尚未验证 PostgreSQL迁移/行锁并发、Redis及模型真实联调、真实浏览器和API全过程、原文件实际部署存储、性能、质量或学校人工验收。修补保留在本地审查分支，**没有推送或更改远端主分支**。

审核统计：Standards主要发现6项（最高P1，本地修补复核通过）；Spec主要发现7项（最高P1，3项本地修补、4项仍需开发/评测），完整业务验收尚未通过。
