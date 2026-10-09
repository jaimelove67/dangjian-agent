import type { DocumentResponse, MemberStage, TodoItem } from './types'

/**
 * 演示数据源。
 *
 * 存在的唯一理由：后端**缺少**以下查询接口，前端若不做标注就是伪造数据。
 *   - 知识库：无 GET /knowledge-docs 列表接口
 *   - 党员：  无名册/台账查询接口
 *   - 问答：  无会话历史持久化接口
 *
 * 因此本文件的数据在界面上**必须**以「示例数据」徽标标注，且不得用于
 * 任何被当作真实业务结论展示的位置。接口补齐后直接替换为真实请求。
 */

export const MOCK_NOTICE = '示例数据，后端列表接口尚未提供'

export const MOCK_DOCUMENTS: DocumentResponse[] = [
  {
    id: 'd-0001',
    doc_id: 'DOC-2024-001',
    file_name: '中国共产党发展党员工作细则.pdf',
    title: '中国共产党发展党员工作细则',
    issuer: '中共中央办公厅',
    doc_number: '中办发〔2014〕34号',
    level: 'central',
    visibility: 'public',
    security_level: 'public',
    status: 'effective',
    effective_date: '2014-05-28',
    expiration_date: null,
    tags: ['发展党员', '程序规范'],
    summary: '规范发展党员工作的基本程序与各环节材料要求。',
    page_count: 18,
  },
  {
    id: 'd-0002',
    doc_id: 'DOC-2024-002',
    file_name: '中国共产党章程.pdf',
    title: '中国共产党章程',
    issuer: '中国共产党第二十次全国代表大会',
    doc_number: null,
    level: 'central',
    visibility: 'public',
    security_level: 'public',
    status: 'effective',
    effective_date: '2022-10-22',
    expiration_date: null,
    tags: ['党章', '基本制度'],
    summary: '党的根本大法，规定党员条件、义务与权利。',
    page_count: 62,
  },
  {
    id: 'd-0003',
    doc_id: 'DOC-2024-003',
    file_name: '关于加强高校学生党员教育管理的实施意见.docx',
    title: '关于加强高校学生党员教育管理的实施意见',
    issuer: '中共某某大学委员会组织部',
    doc_number: '校党组〔2023〕15号',
    level: 'school',
    visibility: 'school',
    security_level: 'internal',
    status: 'effective',
    effective_date: '2023-09-01',
    expiration_date: '2028-08-31',
    tags: ['党员教育', '学生党员'],
    summary: '明确学生党员在校期间的培养考察与教育管理要求。',
    page_count: 9,
  },
  {
    id: 'd-0004',
    doc_id: 'DOC-2024-004',
    file_name: '院系党支部工作考核办法.docx',
    title: '院系党支部工作考核办法',
    issuer: '中共某某大学委员会',
    doc_number: '校党组〔2021〕07号',
    level: 'school',
    visibility: 'department',
    security_level: 'internal',
    status: 'expired',
    effective_date: '2021-03-01',
    expiration_date: '2023-02-28',
    tags: ['支部考核'],
    summary: '已超过有效期，检索时默认排除。',
    page_count: 6,
  },
  {
    id: 'd-0005',
    doc_id: 'DOC-2024-005',
    file_name: '发展对象政治审查工作指引.docx',
    title: '发展对象政治审查工作指引',
    issuer: '中共某某大学委员会组织部',
    doc_number: null,
    level: 'school',
    visibility: 'department',
    security_level: 'sensitive',
    status: 'effective',
    effective_date: '2024-01-10',
    expiration_date: null,
    tags: ['政治审查', '发展对象'],
    summary: '政治审查范围、程序与结论表述要求，含敏感信息处理规范。',
    page_count: 12,
  },
  {
    id: 'd-0006',
    doc_id: 'DOC-2024-006',
    file_name: '入党积极分子培养考察记录填写规范.docx',
    title: '入党积极分子培养考察记录填写规范',
    issuer: '某某大学某某学院党委',
    doc_number: '院党字〔2022〕03号',
    level: 'department',
    visibility: 'branch',
    security_level: 'internal',
    status: 'abolished',
    effective_date: '2022-04-01',
    expiration_date: null,
    tags: ['培养考察', '记录填写'],
    summary: '已废止，相关要求并入校级新规范。',
    page_count: 4,
  },
]

export interface MockMember {
  id: string
  name: string
  stage: MemberStage
  org_name: string
  joined_stage_on: string
  days_in_stage: number
  materials: string[]
  pending: number
}

export const MOCK_MEMBERS: MockMember[] = [
  {
    id: 'm-0001',
    name: '张一鸣',
    stage: 'activist',
    org_name: '计算机学院党委 · 本科生第一党支部',
    joined_stage_on: '2023-11-06',
    days_in_stage: 341,
    materials: ['思想汇报', '培养考察记录', '群众评议材料'],
    pending: 1,
  },
  {
    id: 'm-0002',
    name: '李思远',
    stage: 'activist',
    org_name: '计算机学院党委 · 本科生第一党支部',
    joined_stage_on: '2024-01-15',
    days_in_stage: 271,
    materials: ['思想汇报', '培养考察记录'],
    pending: 2,
  },
  {
    id: 'm-0003',
    name: '王砚书',
    stage: 'candidate',
    org_name: '计算机学院党委 · 研究生第二党支部',
    joined_stage_on: '2024-03-20',
    days_in_stage: 206,
    materials: ['政治审查材料', '公示情况报告'],
    pending: 2,
  },
  {
    id: 'm-0004',
    name: '陈亦舟',
    stage: 'probationary',
    org_name: '计算机学院党委 · 研究生第二党支部',
    joined_stage_on: '2024-06-28',
    days_in_stage: 106,
    materials: ['转正申请书'],
    pending: 1,
  },
  {
    id: 'm-0005',
    name: '赵惟安',
    stage: 'applicant',
    org_name: '计算机学院党委 · 本科生第三党支部',
    joined_stage_on: '2024-09-12',
    days_in_stage: 30,
    materials: ['入党申请书'],
    pending: 0,
  },
  {
    id: 'm-0006',
    name: '周砚青',
    stage: 'member',
    org_name: '计算机学院党委 · 研究生第二党支部',
    joined_stage_on: '2023-06-30',
    days_in_stage: 470,
    materials: [],
    pending: 0,
  },
]

/** 待办建议的离线回退清单，接口不可用时用于演示排版（非真实计算结论） */
export const MOCK_TODOS: TodoItem[] = [
  { category: 'material', content: '张一鸣 的培养考察记录距下次支委会审议不足 30 天' },
  { category: 'material', content: '李思远 尚缺群众评议材料，请补齐后提交' },
  { category: 'meeting', content: '研究生第二党支部本季度支部大会尚未归档' },
  { category: 'reminder', content: '王砚书 的公示情况报告公示期已满，可提交上级审批' },
]

/** 政策原文片段：用于"依据溯源"演示，内容为公开文件的常识性表述 */
export const MOCK_ANSWER = {
  answer:
    '入党积极分子确定后，党组织应当指定一至两名正式党员作为培养联系人，对其进行培养教育。\n\n' +
    '培养考察期一般不少于一年。期间，入党积极分子应当定期向党组织汇报思想，' +
    '党组织每半年至少对其进行一次考察，并形成考察记录[1]。\n\n' +
    '确定为发展对象，还应当经过支委会研究、听取党内外群众意见，' +
    '并进行政治审查[2]。培养考察期未满一年的，原则上不得确定为发展对象。\n\n' +
    '上述内容依据现行有效的党内文件整理，具体操作请以所在党组织的规定为准。',
}
