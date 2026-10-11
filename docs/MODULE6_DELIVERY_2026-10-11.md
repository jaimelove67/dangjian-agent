# 模块6代码与验收工具交付（2026-10-11）

对应 [GitHub #24](https://github.com/jaimelove67/dangjian-agent/issues/24)，固定需求见
[MODULE6_ISSUE24.md](MODULE6_ISSUE24.md)。

交付范围为代码、管理界面和验收工具。用户已确认真实学校、组织树、账号角色、模型出网及
电子归档审批暂未确认。默认清单为空且保持待配置；开发样例不能替代学校确认。
本文不是学校准入、生产发布或完整 issue 验收报告。

开发分支：codex/module6-security-ops-20261010。
固定审查基线：5bd24d3fc5650d71fc9650304dae0a5dec1f164f。
该基线的正式业务界面及前置修补包含在分支历史中。本次未合并主分支或部署生产环境。

## 实现与验收边界

| 任务 | 本次代码或工具 | 待验收或待学校确认 |
| --- | --- | --- |
| M6-01 | 完整服务、ORM、010/011迁移及新库/009回退再升级工具 | 原生镜像与迁移执行、旧库升级及主分支交付 |
| M6-02 | 组织/角色初始化校验、管理登记、空的待配置清单 | 学校认可的真实树和账号绑定 |
| M6-03 | 租户/组织/账号维护、停用、类型与循环校验、祖先撤权与公共库写权限 | 正式组织与权限对照 |
| M6-04 | 精确HTTPS主机限制、涉密AI拒绝、敏感云端拒绝、所属学校审批及路由限制 | 三方评审、校内模型及出网范围 |
| M6-05 | AEAD、内容寻址原件、登记版本SHA256验证、原子发布、轮换、TLS模板、严格保留配置 | 旧材料迁移、保留审批及TLS/网络部署 |
| M6-06 | 独立请求审计/加密离线缓冲、后台每次拒绝/失败/租约耗尽追加审计 | 原生事务/离线恢复及正式业务抽验 |
| M6-07 | 审计筛选/分页/告警、只追加触发器、禁止TRUNCATE、最小运行角色 | 原生账号与防篡改演练 |
| M6-08 | 冻结来源版本、禁止自审、人工意见、变更失效及历史权限校验 | 组织人工流程与正式材料 |
| M6-09 | 配置版本/继承、评分/提示词/模型策略、归档确认 | 学校规则及确认依据 |
| M6-10 | PG持久任务、去重、租约、有限重试/超时、重启恢复、Redis限流与模型用量 | 原生并发/中断恢复 |
| M6-11 | 真实就绪检查、近期有效模型证据、运行指标、完整问答负载工具 | 真实模型连通及完整问答P95≤3秒 |
| M6-12 | 全哈希锁、原生SQLAlchemy类型、真实PDF、双版本CI、完整后端80%门槛 | 完整原生后端及覆盖率≥80%证据 |
| M6-13 | 实际镜像/HTTPS/回退/加密备份、中断续跑恢复及运行权限工具 | 可用原生Docker环境执行报告 |
| M6-14 | 准入登记、三方审批、试点范围及归档默认关闭 | 真实审批、试点清单与安全闭环 |

## 本地实际验证

- Python3.11.16全新环境按requirements-dev.lock完整哈希安装成功，最终限定回归387项通过。
- Python3.12.14另建全新环境，完整哈希安装成功，同一回归387项通过。
- 两种解释器实际运行mypy app，130个源文件无类型错误。
- 应用及本次全部运维脚本的black、isort和flake8检查通过。
- 前端vue-tsc和Vite生产构建通过，172模块。
- 真实Chrome浏览器10项治理交互通过，包括冻结版本提交、失效快照、自审限制、待配置开关、
  组织创建契约、任务去重编号、审计筛选、受限入口及390/768像素五个工作区无整页溢出。
  API为浏览器拦截样例，不代表正式后端权限或学校数据验收。
- 真实有效两页PDF验证文本/页数提取；损坏PDF明确失败，未替换PDF阅读器。
- pip-audit --strict实际审计210个安装依赖，报告0个已知漏洞。
- 默认初始化返回pending_configuration、applied:false、school_count:0。
- 合成Compose展开、CI/Compose/YAML解析、pre-commit配置校验和Git空白检查通过。
- 原生治理集成测试6项成功收集；收集成功不记为运行通过。

限定回归命令：

~~~bash
python -m pytest -o addopts= tests/unit tests/security tests/integration/test_llm_integration.py -q
~~~

上述387项不是完整后端或80%覆盖率通过证据。原生PG/Redis、容器恢复及完整问答负载没有在本地
通过验收：现有Windows Docker Engine启动失败，本机PostgreSQL缺少pgvector。此前WASM数据库DDL
检查不能替代原生事务、并发或恢复。弃用警告仍存在，不影响已执行检查的通过结果。
日志/截图在忽略的tmp目录，原始材料、密钥、备份和虚拟环境不提交入库。

## 首次原生CI证据与修复待复验

[GitHub Actions 38115805019](https://github.com/jaimelove67/dangjian-agent/actions/runs/38115805019)
执行提交814c8180ccb85588fd3cec3a3ea15716886c57db，容器恢复任务通过：真实后端/前端镜像、
TLS、待配置就绪503、迁移回退数据、登记原件缺失反例、33表加密备份、数据库/文件/权限恢复、
中断后显式续跑及审计修改/删除/TRUNCATE拒绝均有报告。

Python3.11.17和3.12.15的格式、导入、lint、完整类型、前端构建和10项浏览器交互通过。
完整后端为480通过、8失败、36初始化错误；包含分支的实际覆盖率65.71%，80%门禁失败。
3.11预装setuptools79.0.1审计失败，3.12依赖审计通过。首次CI不是整体质量验收通过。

后续修复增加011治理时间默认值迁移，支持已升级到010的数据库且保留已有记录；旧模块测试
在各自旧版迁移演练后升级到当前head；审计保留安全版本/快照/删除指针并继续哈希正文；
检索回归验证旧片段不可召回，同时允许模糊检索命中新版共同词；生产/开发哈希锁显式固定
setuptools83.0.0。修复后本地3.11限定回归392项通过、mypy130文件通过，完整原生复验仍待运行。

## 独立审查

Standards和Spec并行审查后已修复并定点复核：

1. 运行账号拒绝高权限角色成员、表所有者成员及当前数据库所有者；就绪、授权、恢复共用SQL条件。
2. 备份/恢复核验DB登记的当前及历史原件。缺失、内层加密失败、跨租户路径或SHA256不符均失败。
3. 后台拒绝/失败及租约耗尽审计与状态同事务提交，保留操作者、对象、追踪号及尝试次数。
4. Study受限材料、失效快照、冻结选优范围、SYS角色变更、伪健康及无限流式等待等问题已修复回归。

两条最终只读审查没有新增已确认代码问题；不保证没有缺陷，也不替代未执行的原生验收。

## 严格质量与原生验收

.github/workflows/module6.yml在Python3.11/3.12使用真实pgvector PostgreSQL16及Redis7。
从完整哈希锁和npm锁干净安装，执行格式/静态/全部应用类型、完整后端、前端构建/浏览器及依赖审计：

~~~bash
python scripts/module6_acceptance.py quality --report-dir tmp/module6-quality
~~~

完整后端覆盖率门槛明确80%，失败或未执行不计通过，没有降低门槛或删减应用统计。
独立日志和report.json保留每项结果。浏览器需先在frontend中npm ci及
npx playwright install --with-deps chromium；Windows可明确MODULE6_BROWSER_CHANNEL=chrome。

独立容器验收只用于Linux非root Docker运行者的本机module6_native_ci测试基础库：

~~~bash
python scripts/module6_container_check.py --isolated --output tmp/module6-container/report.json
~~~

工具只创建随机前缀的自身数据库/容器/角色/临时目录。实际验证镜像构建、登记原件缺失反例、
存活/待配置就绪503、受信任测试TLS、迁移回退/再升级、加密备份、中断后显式续跑、
数据/原件哈希及运行账号不能UPDATE/DELETE/TRUNCATE审计。退出仅清理自身对象。
必须使用独立测试PG/Redis；合成资料和证书不生成正式学校准入。

## 学校资料与运行配置

默认仅校验：

~~~bash
python scripts/module6_bootstrap.py
python scripts/module6_bootstrap.py --manifest /secure/school.confirmed.json
~~~

真实学校清单需status=confirmed和非空依据，租户/组织按父级在前登记，角色匹配组织。
密码仅由清单指定的环境变量读取，不进入清单/日志/审计。
学校批准后DBA在空库显式--apply；旧库采纳既有SYS身份还需--adopt-actor-id，须符合工具已有
平台身份/租户校验。组织登记不代替模型、三方评审及电子归档确认。

生产Compose要求学校HTTPS证书、明确来源、JWT/文件密钥环、分别授权的运行/迁移TLS PG URL
和rediss URL文件。模型未批准时密钥可为空。仅公开443；PG/Redis由学校提供受控网络服务。
Secret文件由entrypoint加载，不写镜像。合成Compose展开不是正式TLS部署验收。
运行账号为非所有者，DBA先建立角色，再默认输出SQL或显式应用：

~~~bash
python scripts/module6_runtime_role.py --role party_runtime
python scripts/module6_runtime_role.py --role party_runtime --apply
~~~

不合规授权回滚，审计仅SELECT/INSERT。学校及模型未就绪时生产ready仍503，不能据此发布可用声明。

## 密钥轮换及加密恢复

FILE_ENCRYPTION_KEYS提供base64编码32字节密钥环，FILE_ENCRYPTION_ACTIVE_KEY选择当前版本。
停止写入、任务及轮换后先校验再应用：

~~~bash
FILE_STORAGE_DIR=/secure/originals python scripts/module6_rotate_files.py
FILE_STORAGE_DIR=/secure/originals python scripts/module6_rotate_files.py --apply
AUDIT_SPOOL_DIR=/secure/audit-spool python scripts/module6_rotate_files.py --audit-spool --apply
~~~

旧明文迁移须显式--allow-legacy-plaintext。先完整校验、发布前再次检查密文哈希，拒绝覆盖并发修改。
旧密钥在保留期及旧备份恢复结束前不得销毁。文件/审计保留至少365天，物理清理默认关闭。
本次没有自动删除历史原件或正式记录。

备份包含public表、全部登记原件/现存加密归档、离线审计及Redis auth:*吊销记录。
必须暂停业务写入、任务和密钥轮换，显式声明--quiesced：

~~~bash
python scripts/module6_backup.py backup --quiesced --output /secure/backups/module6.bin
~~~

整体包再AEAD加密，不在磁盘生成中间明文dump。当前上限512MiB，PG客户端600秒超时。
超量须另选获准的大规模备份方案。旧原件应先补齐路径/版本/SHA256和加密迁移；
未登记原件的旧文档不能凭空生成文件。

恢复仅允许新建module6_restore_*库、相同PG主版本、独立空Redis库及独立空目录。
设置RESTORE_DATABASE_URL/RESTORE_REDIS_URL，默认验证不写：

~~~bash
python scripts/module6_backup.py restore --input /secure/backups/module6.bin --files /secure/restore-originals --audit /secure/restore-audit --runtime-role party_runtime
~~~

原生空目标验证后才显式--apply。中断后保留目标；仅本工具的认证加密检查点可--resume，
且同一包/DB/Redis/目录。不同既有数据不删除或覆盖。恢复核验表计数/哈希、全部登记原件、
文件解密/哈希、吊销载荷及审计权限。不指定运行角色返回restored_pending_permissions及非零退出码。

## 真实模型与完整问答负载

完成学校登记、三方审批、试点范围、精确主机及模型选择后，获准人员执行
module6_model_probe.py --actor-id APPROVED_SCHOOL_ADMIN --output /secure/model-probe.json，仅用固定公开文本验证聊天/向量/重排，
保存真实成功、有效配置版本及用量。未执行不会伪造模型健康记录。

令牌仅通过MODULE6_ADMIN_TOKEN/MODULE6_LOAD_TOKEN提供，在获准服务和公开验收问题下运行：

~~~bash
python scripts/module6_acceptance.py load --base-url https://approved-school-host --questions /secure/approved-public-questions.json --requests 100 --concurrency 5 --output /secure/qa-load-report.json
~~~

报告声明请求量/并发/完整成功问答P95。必须成功、有引用、未拒答，全部请求成功且P95≤3秒才通过。
快速403/429、无依据或模型故障不能形成通过指标。准入/模型未批准返回待配置、发起0次问答。
本次没有正式模型调用、真实负载验收或生产发布。
