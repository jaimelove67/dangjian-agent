# 演示数据说明（129.204.32.148）

生成日期：2026-10-17。用途：给客户演示一整套业务流程。

**所有数据均为虚构演示数据**，学校、院系、支部与人员姓名均为示例，知识库文档是公开党内法规的节选要点整理（标为「未核验演示」，非权威全文）。正式使用前必须由校方核对后重建或改名。

数据全部通过**真实业务接口**写入（受权限校验、组织树规则与状态机约束，并留下审计记录），没有绕过应用直连数据库造假。

---

## 一、登录地址与账号

地址：http://129.204.32.148

| 用户名 | 密码 | 姓名 | 角色 | 所属组织 |
| --- | --- | --- | --- | --- |
| `admin` | `Pq7#mK2vXz9Rt4` | 平台管理员 | 系统管理员 | 平台（跨租户治理） |
| `school_admin` | `Demo@2026hnky` | 李国华 | 学校管理员 | 湖南科技职业技术学院党委 |
| `school_admin2` | `Demo@2026hnky` | 周敏 | 学校管理员 | 湖南科技职业技术学院党委 |
| `dept_admin` | `Demo@2026hnky` | 王志远 | 院系管理员 | 信息工程学院党总支 |
| `branch_sec` | `Demo@2026hnky` | 陈晓明 | 支部书记 | 信息工程学院教工第一党支部 |
| `organizer` | `Demo@2026hnky` | 刘芳 | 组织员 | 信息工程学院教工第一党支部 |
| `member01` | `Demo@2026hnky` | 赵强 | 党员 | 信息工程学院教工第一党支部 |
| `applicant01` | `Demo@2026hnky` | 孙悦 | 申请人 | 信息工程学院教工第一党支部 |

> `school_admin2` 是为了满足「创建人不能自审」而建的第二个管理员，演示审核流时用它登录审核 `school_admin` 提交的内容。
> 演示结束后**必须修改这些密码**（都是明文记录在本文档里的弱密码）。

---

## 二、组织树

```
湖南科技职业技术学院（学校租户）
└── 湖南科技职业技术学院党委          [school]
    ├── 信息工程学院党总支            [department]
    │   ├── 信息工程学院教工第一党支部  [branch]
    │   └── 信息工程学院学生第一党支部  [branch]
    └── 机电工程学院党总支            [department]
        └── 机电工程学院学生第二党支部  [branch]
```

---

## 三、已铺的业务数据

| 模块 | 内容 | 状态 |
| --- | --- | --- |
| 培养对象名册 | 6 名合成培养对象，覆盖申请人 / 积极分子 / 发展对象 / 预备党员 / 正式党员 | 挂在教工第一党支部 |
| 知识库 | 7 篇制度节选文档，切分 40 个片段**已完成向量化** | 3 篇（党章、党员教育管理工作条例、支部工作条例）置为「现行有效」，可作学习政策依据 |
| 中心组学习 | 2026 年学习计划（3 条学习安排，均已生成提纲草稿） | 计划**已审核通过**；第 1 条安排已登记活动 → 生成纪要 → 提交 → **审核通过** |
| 年度考核 | 2026 年指标 `DEMO-INDEX-01`（党员教育培训完成率，人工求和口径，目标 100）+ 5 条院系任务 | 任务全部审核通过，归集无缺项，**归集结果已审核通过** |
| 智能问答 | 已实测：问「申请入党需要满足哪些基本条件？」返回答案 + 5 条章条级引用溯源 | 可用 |

---

## 四、建议演示动线

1. **登录 `admin`** → 治理页看租户 / 组织树 / 账号，演示多租户与权限分层
2. **登录 `school_admin`** → 知识库：上传文档、检索；问答页提问，展示引用角标与溯源卡
3. **登录 `school_admin`** → 学习工作台：看年度计划、学习安排、活动纪要（含审核留痕）
4. **登录 `dept_admin`** → 年度考核：看指标、任务进度、归集结果
5. **登录 `branch_sec`** → 党员发展：名册、阶段推进、材料提交
6. **登录 `member01` / `applicant01`** → 本人视角：我的档案、我的材料

---

## 五、数据与账号怎么重置

演示数据由三个脚本生成，均幂等，重跑不会重复创建（已存在会跳过）：

```bash
# 1. 租户、组织树、账号
docker cp scripts/seed_demo_school.py party-agent-app:/app/seed_demo_school.py
docker compose -f docker-compose.server.yml exec -T app \
  python /app/seed_demo_school.py --admin-password '<admin 密码>'

# 2. 名册 + 知识库（含向量化，会产生少量 embedding 费用）
docker cp scripts/seed_member_profiles.py party-agent-app:/app/seed_member_profiles.py
docker cp scripts/seed_knowledge_docs.py party-agent-app:/app/seed_knowledge_docs.py
docker compose ... exec -T app python /app/seed_member_profiles.py \
  --tenant <学校租户ID> --org-unit-id <支部ID>
docker compose ... exec -T app python /app/seed_knowledge_docs.py \
  --username school_admin --password 'Demo@2026hnky' --embed

# 3. 学习计划/活动 + 考核指标/任务/归集
docker cp scripts/seed_demo_business.py party-agent-app:/app/seed_demo_business.py
docker cp scripts/seed_demo_study_finish.py party-agent-app:/app/seed_demo_study_finish.py
docker compose ... exec -T app python /app/seed_demo_business.py
docker compose ... exec -T app python /app/seed_demo_study_finish.py
```

组织 id 与租户 id 在第 1 步的脚本输出末尾以 JSON 打印。

**彻底清空重来**（会删掉全部业务数据，谨慎）：

```bash
docker compose -f docker-compose.server.yml down -v   # 删除数据卷
# 重新 up → alembic upgrade head → 再跑上面三个脚本
```

---

## 六、踩过的坑（重建时对照）

- 学习模块只认**现行有效**的资料：种子文档入库后默认 `expired`，必须先 `PATCH /knowledge-docs/{doc_id}/status` 置为 `effective`，否则计划提交时判「政策依据待补」。
- 计划依据要**两级都登记**：计划级 `source_doc_ids`（PATCH 计划）和**每条学习安排级** `source_doc_ids`（PATCH 条目），缺后者同样提交不了。
- 并发保护严格：任何写操作带 `expected_revision`，改完要重新读一次再写下一步，否则报「内容已被修订」。
- 纪要三栏目（学习要点 / 讨论共识 / 工作要求）必须走 `generate-minutes` 从原文抽取，手填 `transcript` 不算。
- 考核指标口径：`formula=sum` 只能配 `source=manual` 且 `source_options.measure=sum`，否则 422。
- 归集确认前，任务必须**逐条审核通过**，否则归集结果记「来源记录含未审核内容」，归集审核会被 409 拦住。
- `POST /api/v1/admin/users` 密码最少 12 位（schema 约束），演示统一用 `Demo@2026hnky`。
