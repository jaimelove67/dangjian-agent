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
    path: '/api/v1/qa/sessions',
    purpose: '查询历史问答记录',
    available: false,
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
    available: false,
  },
  {
    label: '删除文件',
    method: 'DELETE',
    path: '/api/v1/knowledge-docs/{doc_id}',
    purpose: '移除知识库中的文件',
    available: false,
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
    available: false,
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
