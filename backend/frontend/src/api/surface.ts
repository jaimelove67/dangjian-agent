/**
 * 后端接口能力矩阵。
 *
 * 用途：系统状态页据实展示"哪些接口已经具备、哪些还没提供"。
 * 这不是开发者文档，而是使用者的必要认知——界面上标了「示例数据」的地方，
 * 在这里一定能找到对应的「未提供」行。二者必须始终一致。
 *
 * 维护约定：后端补齐接口后，把 available 改为 true，并同步移除对应界面上的
 * 示例数据来源与徽标。不允许只改一边。
 */

export interface ApiSurfaceItem {
  label: string
  method: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  path: string
  purpose: string
  available: boolean
}

export const API_SURFACE: ApiSurfaceItem[] = [
  { label: '创建登录账号', method: 'POST', path: '/api/v1/admin/users', purpose: '仅系统管理员可创建当前租户内的账号并分配角色和组织', available: true },
  { label: '账号组织选项', method: 'GET', path: '/api/v1/admin/org-units', purpose: '系统管理员读取本租户有效组织，用于创建账号', available: true },
  { label: '本人档案', method: 'GET', path: '/api/v1/member/self/archive', purpose: '普通党员按登录账号读取明确关联的本人档案', available: true },
  { label: '个人材料提交', method: 'POST', path: '/api/v1/member/self/materials', purpose: '私有保存本人原件，支持提交重试，不自动核验或流转', available: true },
  { label: '本人材料记录', method: 'GET', path: '/api/v1/member/self/materials', purpose: '仅查询本人提交记录', available: true },
  { label: '本人材料原件', method: 'GET', path: '/api/v1/member/self/materials/{material_id}/file', purpose: '校验登录账号所有权后下载原件', available: true },
  { label: '关联党员账号', method: 'PUT', path: '/api/v1/member/roster/{profile_id}/account', purpose: '组织人员将授权档案与同组织有效党员或申请人账号关联', available: true },
  { label: '组织接收材料', method: 'GET', path: '/api/v1/member/roster/{profile_id}/materials', purpose: '组织人员按名册授权范围查询提交记录', available: true },
  { label: '删除本人问答记录', method: 'DELETE', path: '/api/v1/qa/sessions/{session_record_id}', purpose: '仅删除本人长期问答记录，历史与审计保留', available: true },
  { label: '文件处理状态', method: 'GET', path: '/api/v1/knowledge-docs/{doc_id}/processing-status', purpose: '查看正文片段处理状态与待处理数量', available: true },
  { label: '元数据维护', method: 'PATCH', path: '/api/v1/knowledge-docs/{doc_id}/metadata', purpose: '修正来源、时效与可见范围并保留理由', available: true },
  { label: '授权原件下载', method: 'GET', path: '/api/v1/knowledge-docs/{doc_id}/file', purpose: '按当前权限下载指定版本原件', available: true },
  { label: '年度发展批次', method: 'GET', path: '/api/v1/member-full/batches', purpose: '查询授权范围内的年度批次及人数', available: true },
  { label: '培养对象档案', method: 'GET', path: '/api/v1/member-full/profiles/{id}', purpose: '回看材料、培养证据与人工流转记录', available: true },
  { label: '阶段提醒', method: 'GET', path: '/api/v1/member-full/reminders', purpose: '查看阶段节点提醒及处理状态', available: true },
  { label: '辅助评分', method: 'POST', path: '/api/v1/member-full/scoring', purpose: '按年度证据生成待人工核验的评分', available: true },
  { label: '多轮投票记录', method: 'POST', path: '/api/v1/member-full/votes', purpose: '记录组织人员人工核对后的本轮投票', available: true },
  { label: '组织生活记录', method: 'GET', path: '/api/v1/meeting/records', purpose: '查看活动安排、参会、纪要和任务', available: true },
  { label: '活动资料保存', method: 'PATCH', path: '/api/v1/meeting/records/{id}', purpose: '保存实际日期、参会和原文并核对版本', available: true },
  { label: '组织生活人工审核', method: 'POST', path: '/api/v1/meeting/records/{id}/review', purpose: '由有权限且非提交人的人员审核纪要', available: true },
  { label: '组织生活电子归档', method: 'POST', path: '/api/v1/meeting/records/{id}/archive', purpose: '学校确认电子效力后归档审核通过的记录', available: true },
  { label: '年度考核工作台', method: 'GET', path: '/api/v1/assessment/workspace', purpose: '查看授权年度指标、任务进度、佐证缺项与人工计划草案', available: true },
  { label: '指标归集', method: 'POST', path: '/api/v1/assessment/recalculate', purpose: '复用业务源记录，保存规则和归集版本', available: true },
  { label: '考核材料导出', method: 'POST', path: '/api/v1/assessment/runs/{run_id}/export', purpose: '按当前权限导出指标表、任务与佐证目录', available: true },
  { label: '中心组年度计划', method: 'GET', path: '/api/v1/study/plans', purpose: '按年度、期间和党委范围查询学习计划', available: true },
  { label: '学习资料推荐', method: 'GET', path: '/api/v1/study/materials', purpose: '检索有效且适用的授权知识材料', available: true },
  { label: '学习纪要审核', method: 'POST', path: '/api/v1/study/activities/{id}/review', purpose: '人工核对原文后通过或退回纪要', available: true },
  { label: '学习历史归档', method: 'GET', path: '/api/v1/study/history', purpose: '学校确认电子效力后查询审核归档记录', available: true },
  { label: '学习考核复用', method: 'GET', path: '/api/v1/study/metrics', purpose: '只读统计学习次数、参学率及佐证来源', available: true },
  {
    label: '登录',
    method: 'POST',
    path: '/api/v1/auth/login',
    purpose: '账号密码登录，签发访问令牌与刷新令牌',
    available: true,
  },
  {
    label: '当前用户',
    method: 'GET',
    path: '/api/v1/auth/me',
    purpose: '获取当前登录用户身份信息',
    available: true,
  },
  {
    label: '权限码',
    method: 'GET',
    path: '/api/v1/auth/codes',
    purpose: '获取当前账号的权限码列表，用于菜单显隐',
    available: true,
  },
  {
    label: '制度问答',
    method: 'POST',
    path: '/api/v1/qa',
    purpose: '提交问题，返回回答与引用来源',
    available: true,
  },
  {
    label: '问答历史',
    method: 'GET',
    path: '/api/v1/qa/history',
    purpose: '按会话编号查询当前用户的问答记录',
    available: true,
  },
  {
    label: '长期问答历史', method: 'GET', path: '/api/v1/qa/sessions',
    purpose: '分页回看当前用户的问答及完整引用', available: true,
  },
  {
    label: '健康检查',
    method: 'GET',
    path: '/api/v1/health',
    purpose: '基础存活检查',
    available: true,
  },
  {
    label: '就绪检查',
    method: 'GET',
    path: '/api/v1/health/ready',
    purpose: '仅返回整体就绪状态，供部署探针使用',
    available: true,
  },
  {
    label: '系统运行详情',
    method: 'GET',
    path: '/api/v1/admin/health',
    purpose: '仅平台管理员可查看服务名称、版本与运行环境',
    available: true,
  },
  {
    label: '系统就绪详情',
    method: 'GET',
    path: '/api/v1/admin/health/ready',
    purpose: '仅平台管理员可查看依赖与模型配置状态',
    available: true,
  },
  {
    label: '上传制度文件',
    method: 'POST',
    path: '/api/v1/knowledge-docs',
    purpose: '上传文件并切分入库',
    available: true,
  },
  {
    label: '文件详情',
    method: 'GET',
    path: '/api/v1/knowledge-docs/{doc_id}',
    purpose: '按文档编号查询单个文件',
    available: true,
  },
  {
    label: '变更文件状态',
    method: 'PATCH',
    path: '/api/v1/knowledge-docs/{doc_id}/status',
    purpose: '设置文件为有效、已失效或已废止',
    available: true,
  },
  {
    label: '文件列表',
    method: 'GET',
    path: '/api/v1/knowledge-docs',
    purpose: '分页查询知识库文件列表',
    available: true,
  },
  {
    label: '删除文件',
    method: 'DELETE',
    path: '/api/v1/knowledge-docs/{doc_id}',
    purpose: '软删除文件和片段，保留历史记录',
    available: true,
  },
  {
    label: '资格校验',
    method: 'POST',
    path: '/api/v1/member/qualification-check',
    purpose: '核对当前阶段转往目标阶段的材料与时限',
    available: true,
  },
  {
    label: '流转建议',
    method: 'POST',
    path: '/api/v1/member/transition-suggestion',
    purpose: '生成后续阶段与应走程序的建议',
    available: true,
  },
  {
    label: '待办建议',
    method: 'POST',
    path: '/api/v1/member/todo-suggestions',
    purpose: '汇总当前阶段值得关注的事项',
    available: true,
  },
  {
    label: '培养对象名册',
    method: 'GET',
    path: '/api/v1/member/roster',
    purpose: '查询培养对象及其阶段台账',
    available: true,
  },
  {
    label: '登记培养对象', method: 'POST', path: '/api/v1/member/roster',
    purpose: '由组织人员在授权组织范围内登记台账', available: true,
  },
  {
    label: '名册组织范围', method: 'GET', path: '/api/v1/member/org-units',
    purpose: '查询账号可管理的有效组织', available: true,
  },
  {
    label: '阶段流转提交',
    method: 'POST',
    path: '/api/v1/member-full/profiles/{id}/transition',
    purpose: '由具备权限的人员提交阶段流转（人工途径）',
    available: true,
  },
  {
    label: '文字向量化',
    method: 'POST',
    path: '/api/v1/embeddings/embed',
    purpose: '将文本转为向量用于检索',
    available: true,
  },
  {
    label: '批量向量化',
    method: 'POST',
    path: '/api/v1/embeddings/embed-all-pending',
    purpose: '对未向量化的片段批量处理',
    available: true,
  },
]
