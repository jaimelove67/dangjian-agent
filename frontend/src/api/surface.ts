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
  method: 'GET' | 'POST' | 'PATCH' | 'DELETE'
  path: string
  purpose: string
  available: boolean
}

export const API_SURFACE: ApiSurfaceItem[] = [
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
    purpose: '检查数据库、向量库等依赖是否就绪',
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
    path: '/api/v1/member/transition',
    purpose: '由具备权限的人员提交阶段流转（人工途径）',
    available: false,
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
