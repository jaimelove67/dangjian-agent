// 界面交互与请求契约验证。所有 API 在浏览器内拦截，不写数据库、不调用模型。
// node scripts/verify-modules123.mjs [预览URL] [截图目录] [--audit]
import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'

const BASE = process.argv[2] || 'http://127.0.0.1:5677'
const OUT = resolve(
  process.argv[3] || fileURLToPath(new URL('../../tmp/modules123-ui', import.meta.url)),
)
const audit = process.argv.includes('--audit')
await mkdir(OUT, { recursive: true })
const date = new Date()
const today = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
const year = date.getFullYear()
const future = `${year + 1}-01-12`
const permissions = [
  'qa.ask',
  'knowledge.query',
  'knowledge.manage',
  'member.query',
  'member.stage_transition',
  'member.scoring',
  'meeting.query',
  'meeting.manage',
  'meeting.review',
  'meeting.archive',
]
const org = { id: 'branch-a', name: '软件工程学生第一党支部', org_type: 'branch' }
const doc = {
  id: 'doc-a',
  doc_id: 'sample-policy',
  file_name: '样例材料归档细则.txt',
  title: '样例：发展党员材料归档细则',
  issuer: '样例学校党委组织部',
  doc_number: '样例〔2026〕7号',
  level: 'school',
  visibility: 'school',
  security_level: 'internal',
  status: 'effective',
  effective_date: '2025-01-01',
  expiration_date: null,
  tags: ['发展党员', '档案'],
  summary: '界面验证用的资料样例，不作为业务依据。',
  page_count: 3,
  content_revision: 1,
}
const profile = {
  id: 'member-a',
  name: '陈见微',
  org_name: org.name,
  org_unit_id: org.id,
  current_stage: 'activist',
  stage_joined_on: `${year - 1}-01-12`,
  year,
  batch_no: 'B1',
  is_active: true,
  pending: 1,
  materials: [
    {
      id: 'material-a',
      material_type: '思想汇报',
      file_version: '第1版',
      stage: 'activist',
      submit_date: today,
      review_status: 'pending',
      note: '',
      data_level: 'internal',
      data_level_label: '内部',
      cloud_allowed: true,
      embedding_allowed: true,
      redacted_fields: [],
      review_history: [],
    },
    {
      // 政审类材料按涉密级返回：第三人字段正文（审核备注）由后端脱敏，
      // 这里给的就是脱敏后的占位，界面只应展示密级与占位说明。
      material_type: '政治审查材料',
      file_version: '第1版',
      stage: 'activist',
      submit_date: today,
      review_status: 'approved',
      note: '（涉密材料正文不在界面展示，请查党组织线下原件）',
      data_level: 'classified',
      data_level_label: '涉密',
      cloud_allowed: false,
      embedding_allowed: false,
      redacted_fields: ['note'],
      review_history: [],
    },
  ],
  cultivation: [],
  stage_history: [],
  boundary: '阶段流转仅由人工操作完成，辅助结果不构成组织认定。',
}
// 组织关系接转（T-MEM-14）用到的在册正式党员：接转只面向预备党员与正式党员，
// 上面的"陈见微"是培养对象（入党积极分子/发展对象），正好用来验证培养对象不出现在转出候选里。
const transferMember = {
  id: 'member-b',
  name: '林舟',
  org_name: org.name,
  org_unit_id: org.id,
  current_stage: 'member',
  stage_joined_on: `${year - 3}-06-01`,
  year,
  batch_no: 'B1',
  is_active: true,
  pending: 0,
  materials: [],
}
const source = {
  ...doc,
  excerpt: '界面验证样例正文，不作为业务依据。',
  chunk_id: 'chunk-a',
  article: null,
}
const meeting = {
  id: 'meeting-a',
  org_unit_id: org.id,
  activity_type: 'branch_member_meeting',
  activity_type_label: '支部大会',
  title: '样例：支部组织生活安排',
  scheduled_on: today,
  held_on: null,
  host: '陈见微',
  participants: [],
  source_doc_ids: [doc.doc_id],
  sources: [source],
  context: {},
  transcript: '',
  minutes: {},
  revision: 1,
  review_status: 'draft',
  submitted_by: null,
  reviewed_by: null,
  reviewed_at: null,
  review_comment: '',
  archived_at: null,
  archive_policy_version: null,
  tasks: [],
  missing: ['实际召开日期待补', '参会人员待补', '会议原文待补', '纪要条目待补'],
  restricted: false,
  notice: '生成内容仅为草稿，须人工核对。',
  execution_status: 'planned',
}
// 三会一课频次：一条"已召开但纪要没审"的党课 + 上一季度缺口，用来钉住提醒与缺口分区
const frequencyRow = {
  org_unit_id: org.id,
  org_unit_name: org.name,
  activity_type: 'party_lecture',
  activity_type_label: '党课',
  period: 'quarter',
  period_label: '2026 年第 2 季度',
  period_start: '2026-04-01',
  period_end: '2026-06-30',
  required: 1,
  performed: 0,
  awaiting_review: 2,
  scheduled: 0,
  missing: 1,
  days_left: 51,
  annual_required: 4,
  period_text: '每季度至少 1 次',
  basis: '党支部一般每季度至少组织 1 次党课',
  state: 'awaiting_review',
  reminder:
    '2026 年第 2 季度党课已召开 2 次，但纪要尚未通过人工审核；完成审核后即计入本周期，请先完成纪要审核（退回的需修订后重新提交）',
}
const frequency = {
  as_of: '2026-05-10',
  year,
  org_unit_id: null,
  branch_count: 1,
  rows: [frequencyRow],
  reminders: [frequencyRow],
  gaps: [
    {
      org_unit_id: org.id,
      org_unit_name: org.name,
      activity_type: 'party_lecture',
      activity_type_label: '党课',
      period: 'quarter',
      required: 1,
      missed_periods: ['2026 年第 1 季度'],
      missing_total: 1,
      awaiting_total: 0,
      text: `${org.name}党课：本年度已结束 1 个周期中 1 个未达标（2026 年第 1 季度），累计缺口 1 次；跨周期不抵扣，不因后续补开而消除，请在台账中说明原因`,
    },
  ],
  missing: [],
  truncated: false,
  notice: '频次为制度提示，完成认定以人工审核通过的会议记录为准，系统不自动认定完成',
  calculation_rule:
    'org-life-frequency-1：按《中国共产党支部工作条例（试行）》的周期口径（支部党员大会、党课每季度至少 1 次；党支部委员会会议、党小组会每月至少 1 次）；只统计已召开且人工审核通过的记录',
}

// 民主评议党员：一条已通过（优秀）、一条基本合格（须研究处置）、一条待审核、一条未发起。
// 待审核那条的提交人写成另一个人，界面上才可能出现"审核"按钮（提交人不能自审）。
const memberReviewRows = [
  {
    profile_id: 'review-profile-1',
    member_name: '陈见微',
    stage: 'member',
    stage_label: '正式党员',
    org_unit_id: org.id,
    org_name: org.name,
    in_roster: true,
    review_id: 'review-1',
    revision: 3,
    review_status: 'approved',
    submitted_by: 'viewer-a',
    grade: 'outstanding',
    grade_label: '优秀',
    basis: '民主测评情况与日常表现',
    rectification: '',
    procedure: {
      self_assessment: '本人对照党员标准自评：按时参加组织生活。',
      peer_review: '其他党员认为该同志履职认真。',
      test: { eligible: 10, attended: 9, outstanding: 7, qualified: 2, basic: 0, unqualified: 0 },
      branch_opinion: '支委会同意评定为优秀。',
    },
  },
  {
    profile_id: 'review-profile-2',
    member_name: '李知行',
    stage: 'probationary',
    stage_label: '预备党员',
    org_unit_id: org.id,
    org_name: org.name,
    in_roster: true,
    review_id: 'review-2',
    revision: 3,
    review_status: 'approved',
    submitted_by: 'viewer-a',
    grade: 'basic',
    grade_label: '基本合格',
    basis: '理论学习与实际表现',
    rectification: '限期改正理论学习不系统的问题。',
    procedure: {
      self_assessment: '本人自评：理论学习不够系统。',
      peer_review: '',
      test: null,
      branch_opinion: '支委会同意评定为基本合格。',
    },
  },
  {
    profile_id: 'review-profile-3',
    member_name: '赵向知',
    stage: 'member',
    stage_label: '正式党员',
    org_unit_id: org.id,
    org_name: org.name,
    in_roster: true,
    review_id: 'review-3',
    revision: 2,
    review_status: 'pending',
    submitted_by: 'viewer-a',
    grade: 'qualified',
    grade_label: '合格',
    basis: '民主测评情况与日常表现',
    rectification: '',
    procedure: {
      self_assessment: '本人对照党员标准自评：能完成组织交办的任务。',
      peer_review: '',
      test: null,
      branch_opinion: '支委会同意评定为合格。',
    },
  },
  {
    profile_id: 'review-profile-4',
    member_name: '王砚清',
    stage: 'member',
    stage_label: '正式党员',
    org_unit_id: org.id,
    org_name: org.name,
    in_roster: true,
    review_id: null,
    revision: 0,
    review_status: 'not_started',
    submitted_by: null,
    grade: '',
    grade_label: '',
    basis: '',
    rectification: '',
    procedure: {},
  },
  {
    profile_id: 'review-profile-5',
    member_name: '周慕白',
    stage: 'probationary',
    stage_label: '预备党员',
    org_unit_id: org.id,
    org_name: org.name,
    in_roster: true,
    review_id: null,
    revision: 0,
    review_status: 'not_started',
    submitted_by: null,
    grade: '',
    grade_label: '',
    basis: '',
    rectification: '',
    procedure: {},
  },
]
const gradeOptions = [
  { key: 'outstanding', label: '优秀' },
  { key: 'qualified', label: '合格' },
  { key: 'basic', label: '基本合格' },
  { key: 'unqualified', label: '不合格' },
]

function reviewMissing(row) {
  const procedure = row.procedure || {}
  const missing = []
  if (!String(procedure.self_assessment || '').trim()) missing.push('个人自评待录')
  if (!String(procedure.branch_opinion || '').trim()) missing.push('支部评定意见待录')
  if (!row.grade) missing.push('评定等次待定')
  if (!String(row.basis || '').trim()) missing.push('评定依据待填')
  return missing
}

function reviewAdvisories(row) {
  const procedure = row.procedure || {}
  const advisories = []
  if (!String(procedure.peer_review || '').trim()) advisories.push('未登记党员互评意见')
  if (!procedure.test) advisories.push('未登记民主测评票数')
  return advisories
}

function reviewTarget(row, viewer, canReview = true) {
  return {
    ...structuredClone(row),
    missing: reviewMissing(row),
    advisories: reviewAdvisories(row),
    can_review: canReview && row.review_status === 'pending' && row.submitted_by !== viewer,
  }
}

function reviewWorkspace(data, viewer, canReview = true) {
  const targets = data.memberReviews.map((row) => reviewTarget(row, viewer, canReview))
  const progress = {
    target_total: targets.length,
    launched: 0,
    not_started: 0,
    draft: 0,
    pending: 0,
    approved: 0,
    rejected: 0,
  }
  const grades = { outstanding: 0, qualified: 0, basic: 0, unqualified: 0 }
  const attention = []
  for (const row of targets) {
    if (row.review_status === 'not_started') progress.not_started += 1
    else {
      progress.launched += 1
      progress[row.review_status] += 1
    }
    if (row.review_status === 'approved') {
      if (grades[row.grade] !== undefined) grades[row.grade] += 1
      if (row.grade === 'basic' || row.grade === 'unqualified') {
        attention.push({
          review_id: row.review_id,
          member_name: row.member_name,
          org_name: row.org_name,
          grade: row.grade,
          grade_label: row.grade_label,
          rectification: row.rectification,
        })
      }
    }
  }
  const outstanding = grades.outstanding
  return {
    year,
    org_unit_id: org.id,
    org_name: org.name,
    targets,
    target_total: targets.length,
    progress,
    grades,
    grade_options: gradeOptions,
    outstanding,
    outstanding_ratio: targets.length ? Math.round((outstanding * 1000) / targets.length) / 10 : 0,
    attention,
    advisory_count: targets.filter((row) => row.advisories.length).length,
    truncated: false,
    missing: [],
    notices: {
      outstanding_notice: '优秀等次比例上限按学校党委组织部门的规定执行，系统不自动截断或排名',
      unqualified_notice:
        '拟评定不合格的，组织处置须按党章党规由党组织研究决定，系统不自动生成处置意见',
      feedback_notice: '评定意见应向本人反馈；本人只能在"本人档案"查看自己的评议结果',
    },
    notice: '评议程序与等次由组织人员记录、审核人确认；系统不按票数自动排名或定等次',
    boundary: '等次与组织处置属于组织结论，须人工形成；系统只记录、送审与留痕',
  }
}

function applyReviewPayload(row, body) {
  const procedure = body.procedure || {}
  row.procedure = {
    self_assessment: procedure.self_assessment || '',
    peer_review: procedure.peer_review || '',
    test: procedure.test ?? null,
    branch_opinion: procedure.branch_opinion || '',
  }
  row.grade = body.grade || ''
  row.grade_label = (gradeOptions.find((item) => item.key === body.grade) || {}).label || ''
  row.basis = body.basis || ''
  row.rectification = body.rectification || ''
}

function reviewDetail(row, viewer, canReview = true) {
  return {
    ...reviewTarget(row, viewer, canReview),
    id: row.review_id,
    year,
    reviewed_by: null,
    reviewed_at: null,
    review_comment: '',
    revisions: [],
    notice: '',
    boundary: '',
  }
}

function fixture() {
  return {
    doc: structuredClone(doc),
    ready: false,
    rejectMetadata: false,
    profile: structuredClone(profile),
    batches: [
      {
        id: 'batch-a',
        year,
        batch_no: 'B1',
        label: '春季发展批次',
        org_unit_id: org.id,
        org_name: org.name,
        member_count: 1,
        is_active: true,
      },
    ],
    reminders: [
      {
        id: 'reminder-a',
        profile_id: profile.id,
        kind: 'training_period',
        due_on: today,
        status: 'open',
        note: '',
        processed_at: null,
      },
    ],
    votes: [],
    selections: [],
    leagueRecommendations: [],
    transfers: [],
    upperReports: [],
    records: [structuredClone(meeting)],
    memberReviews: structuredClone(memberReviewRows),
    revisions: [],
    allowArchive: false,
    restricted: false,
    empty: false,
    failList: false,
    // 名册按支部筛选（T-MEM-02）：记下名册列表与名册统计两处收到的 org_unit_id，
    // 用来钉住"两个入口用同一组筛选"（只看列表、统计其实是全院系＝假筛选）
    rosterOrgCalls: [],
    statsOrgCalls: [],
  }
}
// ----- 选优结论与团组织推优（T-MEM-13、T-MEM-06）：界面验证用的样例视图 -----
const stageLabels = {
  applicant: '入党申请人',
  activist: '入党积极分子',
  candidate: '发展对象',
  probationary: '预备党员',
  member: '正式党员',
  rejected: '退回',
}
const selectionStatusLabels = {
  draft: '草稿',
  pending: '待审核',
  approved: '已通过',
  rejected: '已退回',
}
const researchMethodLabels = { committee: '支委会', member_meeting: '党员大会' }
const ageNotice =
  '系统不判断年龄（名册里没有出生年月）：是否属 28 周岁以下青年请组织核对，缺推优记录不阻断选优与阶段流转'
const selectionNotice =
  '结论由组织人员填写、第二位组织人员审核；投票汇总与评分只是辅助材料，系统不按票数排序、不自动产生名单、不自动定等次'
const selectionBoundary =
  '生效结论是组织认定依据：阶段流转仍由授权人员按程序人工办理，系统不自动改阶段，也不自动向上级党组织报送'
const selectionHints = {
  activist: '确定入党积极分子后须报上级党委备案（细则第八条）：请在「上级审批 / 备案报送台账」登记',
  candidate: '列为发展对象后须报上级党委备案（细则第十三条）：请在「上级审批 / 备案报送台账」登记',
  probationary:
    '接收预备党员须报上级党委审批（细则第二十一 / 二十二条）：请在「上级审批 / 备案报送台账」登记',
  member: '预备党员转正须报上级党委审批：请在「上级审批 / 备案报送台账」登记',
}
const recommendationNotice =
  '团组织推优只登记事实：推荐团组织、推荐日期与推优说明；推优记录不自动写进选优结论'

function rosterRows() {
  return [state.profile, transferMember]
}

function memberName(profileId) {
  const row = rosterRows().find((item) => item.id === profileId)
  return row ? row.name : `对象 ${String(profileId).slice(0, 8)}`
}

function memberStage(profileId) {
  const row = rosterRows().find((item) => item.id === profileId)
  return row ? row.current_stage : 'activist'
}

function selectionTally(batchNo, roundNo, candidateIds) {
  const tally = {}
  for (const id of candidateIds) {
    const rows = state.votes.filter(
      (item) => item.profile_id === id && item.batch_no === batchNo && item.round_no === roundNo,
    )
    if (!rows.length) continue
    tally[id] = { agree: 0, disagree: 0, abstain: 0 }
    for (const row of rows) tally[id][row.vote] += 1
  }
  return tally
}

function selectionView(row, viewer, detail = false) {
  const view = {
    id: row.id,
    batch_no: row.batch_no,
    round_no: row.round_no,
    org_unit_id: org.id,
    org_name: org.name,
    target_stage: row.target_stage,
    target_stage_label: stageLabels[row.target_stage] || row.target_stage,
    candidates: row.candidate_ids.map((profileId) => ({
      profile_id: profileId,
      member_name: memberName(profileId),
      stage: memberStage(profileId),
      stage_label: stageLabels[memberStage(profileId)] || memberStage(profileId),
    })),
    candidate_count: row.candidate_ids.length,
    basis: row.basis,
    evidence: row.evidence,
    research_on: row.research_on,
    research_method: row.research_method,
    research_method_label: researchMethodLabels[row.research_method] || row.research_method,
    review_status: row.review_status,
    review_status_label: selectionStatusLabels[row.review_status],
    submitted_by: row.submitted_by,
    reviewed_by: row.reviewed_by,
    reviewed_at: row.reviewed_at,
    review_comment: row.review_comment,
    revision: row.revision,
    effective: row.review_status === 'approved',
    // 与后端同一条规则：待审核 + 不是自己送审的，才给审核入口
    can_review: row.review_status === 'pending' && row.submitted_by !== viewer,
    next_step_hint: selectionHints[row.target_stage] || '',
    notice: selectionNotice,
    boundary: selectionBoundary,
    data_level: 'sensitive',
    data_level_label: '敏感',
    cloud_allowed: false,
    embedding_allowed: true,
    redacted_fields: [],
  }
  if (!detail) return view
  const pending = row.candidate_ids.filter(
    (profileId) =>
      !state.leagueRecommendations.some((item) => item.profile_id === profileId && !item.revoked_on),
  )
  return {
    ...view,
    missing: [],
    advisories: pending.length
      ? [`${pending.length} 名拟推荐对象尚无团组织推优记录：${ageNotice}`]
      : [],
    revisions: row.revisions.map((item) => ({ ...item })),
  }
}

function recommendationStatusList() {
  return rosterRows().map((row) => {
    const active = state.leagueRecommendations.filter(
      (item) => item.profile_id === row.id && !item.revoked_on,
    )
    const latest = active[active.length - 1]
    return {
      profile_id: row.id,
      member_name: row.name,
      has_record: active.length > 0,
      active_count: active.length,
      latest_on: latest ? latest.recommended_on : null,
      latest_org: latest ? latest.league_org : '',
      age_notice: ageNotice,
    }
  })
}

function recommendationView(row) {
  return {
    ...row,
    member_name: memberName(row.profile_id),
    stage: memberStage(row.profile_id),
    stage_label: stageLabels[memberStage(row.profile_id)] || memberStage(row.profile_id),
    org_unit_id: org.id,
    org_name: org.name,
    revoke_reason: row.revoke_reason || '',
    active: !row.revoked_on,
    age_notice: ageNotice,
    notice: '推优记录只登记事实：系统不判断年龄、不替代支部研究，也不阻断选优与阶段流转',
    data_level: 'sensitive',
    data_level_label: '敏感',
    cloud_allowed: false,
    embedding_allowed: true,
    redacted_fields: [],
  }
}

const requests = []
const errors = []
const checks = []
const state = fixture()
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ok = (data) => ({
  status: 200,
  contentType: 'application/json',
  body: JSON.stringify({ code: 0, message: 'success', data, trace_id: 'ui-fixture-trace' }),
})
const failed = (status, message) => ({
  status,
  contentType: 'application/json',
  body: JSON.stringify({
    code: status * 100 + 1,
    message,
    data: null,
    trace_id: 'ui-fixture-error',
  }),
})
const pagination = (items, params) => ({
  items,
  total: items.length,
  page: Number(params.get('page') || 1),
  page_size: Number(params.get('page_size') || 20),
})

// ---------------------------- 组织关系接转（T-MEM-14） ----------------------------
const transferDirections = { in: '转入', out: '转出' }
const transferStatuses = { pending: '待接收', settled: '已接收', revoked: '已作废' }
const transferStates = { in_place: '在册', out_pending: '转出待接收', transferred_out: '已转出' }
const addDays = (iso, days) => {
  const value = new Date(`${iso}T00:00:00Z`)
  value.setUTCDate(value.getUTCDate() + days)
  return value.toISOString().slice(0, 10)
}
/** 与后端 latest_transfer_states 同一口径：作废视同未发生，取最后一条有效记录。 */
function transferState(transfers, profileId) {
  let state = 'in_place'
  for (const row of transfers.filter((item) => item.profile_id === profileId)) {
    if (row.status === 'revoked') continue
    state =
      row.direction === 'out'
        ? row.status === 'settled'
          ? 'transferred_out'
          : 'out_pending'
        : 'in_place'
  }
  return state
}
function transferView(row, currentDay) {
  const overdue = row.status === 'pending' && row.valid_until < currentDay
  return {
    ...row,
    direction_label: transferDirections[row.direction],
    status_label: transferStatuses[row.status],
    state_label: transferStates[row.state ?? 'in_place'],
    stage_label: row.stage === 'member' ? '正式党员' : '预备党员',
    days_left: Math.round(
      (Date.parse(`${row.valid_until}T00:00:00Z`) - Date.parse(`${currentDay}T00:00:00Z`)) / 86400000,
    ),
    overdue,
    overdue_notice: overdue
      ? `介绍信已超过有效期仍未回执（${row.counterpart_org}），请核实本人是否已到新组织报到并联系接收组织确认；系统不自动判定转出失败`
      : '',
  }
}
function transferSummary(transfers, currentDay) {
  const pending = transfers.filter((row) => row.status === 'pending')
  return {
    pending_out: pending.filter((row) => row.direction === 'out').length,
    pending_in: pending.filter((row) => row.direction === 'in').length,
    overdue: pending.filter((row) => row.valid_until < currentDay).length,
    settled_out: transfers.filter((row) => row.direction === 'out' && row.status === 'settled').length,
    settled_in: transfers.filter((row) => row.direction === 'in' && row.status === 'settled').length,
    revoked: transfers.filter((row) => row.status === 'revoked').length,
    this_year_out: transfers.filter((row) => row.direction === 'out' && row.issued_on.startsWith(String(year))).length,
    this_year_in: transfers.filter((row) => row.direction === 'in' && row.issued_on.startsWith(String(year))).length,
    pending_total: pending.length,
  }
}
const TRANSFER_NOTICE =
  '接转只记录事实：转出须收到回执才算完成，转入须核对档案；系统不自动认定接收，也不因介绍信到期自动判定失败'

// ---------------------------- 上级审批 / 备案（T-MEM-11） ----------------------------
// 事项、类别与依据由后端目录单源给出；界面不自己编条文。
const upperStageRank = (stage) =>
  ['applicant', 'activist', 'candidate', 'probationary', 'member'].indexOf(stage)
const upperApprovalDays = 90
const upperItems = [
  {
    item: 'activist_record',
    label: '确定入党积极分子（报上级党委备案）',
    kind: 'record',
    kind_label: '备案',
    stage: 'activist',
    stage_label: '入党积极分子',
    basis: '《中国共产党发展党员工作细则》第八条：确定入党积极分子由党支部委员会会议研究决定后，报上级党委备案。',
    report_to: '上级党委',
    materials: ['入党申请书', '党组织谈话记录', '入党积极分子备案报告'],
  },
  {
    item: 'candidate_record',
    label: '确定发展对象（报上级党委备案）',
    kind: 'record',
    kind_label: '备案',
    stage: 'candidate',
    stage_label: '发展对象',
    basis: '《中国共产党发展党员工作细则》第十三条：确定发展对象由支部委员会研究后报上级党委备案。',
    report_to: '上级党委',
    materials: ['入党申请书', '党组织谈话记录', '思想汇报', '培养考察记录', '发展对象备案报告'],
  },
  {
    item: 'probationary_approval',
    label: '接收预备党员（报上级党委审批）',
    kind: 'approval',
    kind_label: '审批',
    stage: 'probationary',
    stage_label: '预备党员',
    basis: '《中国共产党发展党员工作细则》第二十一条、第二十二条：支部大会通过后报上级党委审批，上级党委应派人谈话。',
    report_to: '上级党委',
    materials: [
      '入党申请书',
      '党组织谈话记录',
      '思想汇报',
      '培养考察记录',
      '政治审查材料',
      '入党积极分子培养考察登记表',
      '中国共产党入党志愿书',
    ],
  },
  {
    item: 'member_approval',
    label: '预备党员转正（报上级党委审批）',
    kind: 'approval',
    kind_label: '审批',
    stage: 'member',
    stage_label: '正式党员',
    basis: '《中国共产党发展党员工作细则》第五章：预备党员预备期满，支部大会讨论通过后报上级党委审批。',
    report_to: '上级党委',
    materials: [
      '入党申请书',
      '党组织谈话记录',
      '思想汇报',
      '培养考察记录',
      '政治审查材料',
      '入党积极分子培养考察登记表',
      '中国共产党入党志愿书',
      '转正申请书',
      '预备期考察记录',
      '预备党员教育考察登记表',
    ],
  },
]
const UPPER_NOTICE =
  '本台账只登记两件事：材料已报送、上级批复结果。系统不代替上级党组织审批，回填批复不改动党员阶段；备案类时限按上级党委规定。'
const upperAdvanceDays = 15

/** 只有审批类且仍在等批复的报送才有到期日；备案类细则未统一规定时限。 */
function upperOverdue(row, currentDay) {
  return (
    row.kind === 'approval' &&
    row.status === 'submitted' &&
    addDays(row.submitted_on, upperApprovalDays) < currentDay
  )
}
function upperReportView(row, currentDay) {
  const item = upperItems.find((entry) => entry.item === row.item)
  const approval = row.kind === 'approval'
  const deadline = approval ? addDays(row.submitted_on, upperApprovalDays) : null
  const overdue = upperOverdue(row, currentDay)
  const remaining = deadline
    ? Math.round((Date.parse(`${deadline}T00:00:00Z`) - Date.parse(`${currentDay}T00:00:00Z`)) / 86400000)
    : null
  return {
    ...row,
    item_label: item.label,
    kind_label: item.kind_label,
    basis: item.basis,
    report_to: item.report_to,
    stage_label: item.stage_label,
    material_count: row.materials.length,
    status_label:
      row.status === 'submitted' ? '已报送待批复' : row.status === 'settled' ? '已回填批复' : '已作废',
    result_label:
      row.result === 'agreed'
        ? '同意 / 批准'
        : row.result === 'rejected'
          ? '不同意'
          : row.result === 'supplement'
            ? '需补充材料'
            : '',
    deadline,
    days_left: remaining,
    overdue,
    due_soon:
      approval && row.status === 'submitted' && remaining !== null && remaining >= 0 && remaining <= upperAdvanceDays,
    overdue_notice: overdue
      ? `报送已超过审批时限仍未收到批复（${row.upper_org}），请向上级党组织核实审批进度；系统不判定审批失效、也不改动党员阶段`
      : '',
    no_deadline_note: approval ? '' : '备案类事项细则未统一规定时限，时限按上级党委规定，本系统不另设期限',
  }
}
function upperSummary(rows, currentDay) {
  const pending = rows.filter((row) => row.status === 'submitted')
  return {
    pending: pending.length,
    pending_approval: pending.filter((row) => row.kind === 'approval').length,
    overdue: rows.filter((row) => upperOverdue(row, currentDay)).length,
    supplement: rows.filter((row) => row.result === 'supplement').length,
    settled: rows.filter((row) => row.status === 'settled').length,
    revoked: rows.filter((row) => row.status === 'revoked').length,
    this_year: rows.filter((row) => row.submitted_on.startsWith(String(year))).length,
  }
}

function updateMissing(record) {
  record.missing = [
    !record.held_on && '实际召开日期待补',
    !record.participants.length && '参会人员待补',
    !record.host && '主持人待补',
    !record.transcript && '会议原文待补',
    !Object.values(record.minutes).some((items) => items.length) && '纪要条目待补',
  ].filter(Boolean)
  record.execution_status = record.archived_at
    ? 'archived'
    : record.review_status === 'approved'
      ? 'completed'
      : record.review_status === 'pending'
        ? 'pending'
        : record.held_on
          ? 'held'
          : 'planned'
}

async function context(width = 1440, readonly = false, viewer = 'viewer-a', data = state) {
  const ctx = await browser.newContext({
    viewport: { width, height: width < 768 ? 844 : 1000 },
    deviceScaleFactor: 1,
  })
  await ctx.addInitScript(() => localStorage.setItem('party.access_token', 'ui-fixture-token'))
  await ctx.route(`${BASE}/api/**`, async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname.replace('/api', '')
    const method = request.method()
    const body = request.postDataJSON()
    assert.equal(request.headers().authorization, 'Bearer ui-fixture-token')
    assert.ok(!url.searchParams.has('access_token'), '令牌不能出现在下载URL中')
    if (method !== 'GET') requests.push({ method, path, body })
    if (path === '/auth/me')
      return route.fulfill(
        ok({
          id: viewer,
          username: '界面验证账号（样例）',
          name: '界面验证账号',
          role: 'system_admin',
          tenant_id: 'fixture-tenant',
          org_unit_id: org.id,
        }),
      )
    if (path === '/auth/codes')
      return route.fulfill(
        ok(readonly ? ['qa.ask', 'knowledge.query', 'member.query', 'meeting.query'] : permissions),
      )
    if (path === '/knowledge-docs' && method === 'GET')
      return route.fulfill(
        data.failList
          ? failed(503, '资料服务暂不可用')
          : ok({
              ...pagination(data.empty ? [] : [data.doc], url.searchParams),
              counts: {
                all: data.empty ? 0 : 1,
                effective: data.empty ? 0 : 1,
                expired: 0,
                abolished: 0,
              },
            }),
      )
    if (path.endsWith('/processing-status'))
      return route.fulfill(
        ok({
          doc_id: data.doc.doc_id,
          status: data.ready ? 'ready' : 'pending',
          total_chunks: 3,
          embedded_chunks: data.ready ? 3 : 0,
          pending_chunks: data.ready ? 0 : 3,
          error: null,
          content_revision: 1,
          retry_endpoint: data.ready ? null : '/embeddings/embed',
        }),
      )
    if (path === '/embeddings/embed') {
      assert.equal(body.doc_id, data.doc.doc_id)
      data.ready = true
      return route.fulfill(ok({ embedded_count: 3 }))
    }
    if (path.endsWith('/metadata')) {
      if (data.rejectMetadata) return route.fulfill(failed(403, '共享公共库只能由系统管理员维护'))
      Object.assign(data.doc, body, { tags: body.tags.split(/[,，]/).filter(Boolean) })
      return route.fulfill(ok(data.doc))
    }
    if (path.endsWith('/file'))
      return route.fulfill({
        status: 200,
        contentType: 'application/octet-stream',
        body: '界面验证用原件样例',
      })
    if (path === '/member/org-units') return route.fulfill(ok([org]))
    if (path === '/member/roster') {
      data.rosterOrgCalls.push(url.searchParams.get('org_unit_id') ?? '')
      const match =
        (!url.searchParams.has('year') ||
          Number(url.searchParams.get('year')) === data.profile.year) &&
        (!url.searchParams.has('batch_no') ||
          url.searchParams.get('batch_no') === data.profile.batch_no) &&
        (!url.searchParams.has('org_unit_id') ||
          url.searchParams.get('org_unit_id') === data.profile.org_unit_id)
      const includeTransferred = url.searchParams.get('include_transferred') === 'true'
      // 组织关系已转出的人不在默认名册里（T-MEM-14），与后端 include_transferred 口径一致
      const rows = (data.empty || !match ? [] : [data.profile, transferMember])
        .map((item) => {
          const relationStatus = transferState(data.transfers, item.id)
          return {
            ...item,
            materials: item.materials.map((entry) => entry.material_type),
            stage: item.current_stage,
            days_in_stage: 500,
            relation_status: relationStatus,
          }
        })
        .filter((item) => includeTransferred || item.relation_status !== 'transferred_out')
      return route.fulfill(ok(pagination(rows, url.searchParams)))
    }
    // ---------------------------- 组织关系接转（T-MEM-14） ----------------------------
    if (path === '/member-full/transfers' && method === 'GET') {
      const rows = data.transfers
        .filter(
          (row) =>
            !url.searchParams.has('direction') ||
            row.direction === url.searchParams.get('direction'),
        )
        .filter(
          (row) => !url.searchParams.has('status') || row.status === url.searchParams.get('status'),
        )
        .filter(
          (row) =>
            url.searchParams.get('overdue') !== 'true' ||
            (row.status === 'pending' && row.valid_until < today),
        )
        // 列表不带留痕：留痕要走单条明细接口，避免"看起来看完了其实没查"
        .map(({ history, ...row }) => {
          void history
          return transferView({ ...row, state: transferState(data.transfers, row.profile_id) }, today)
        })
      return route.fulfill(
        ok({
          items: rows,
          total: rows.length,
          page: 1,
          page_size: 20,
          summary: transferSummary(data.transfers, today),
          notice: TRANSFER_NOTICE,
        }),
      )
    }
    if (path === '/member-full/transfers' && method === 'POST') {
      const base = [
        '入党申请书',
        '党组织谈话记录',
        '思想汇报',
        '培养考察记录',
        '群众评议材料',
        '党课培训证明',
        '政治审查材料',
        '公示情况报告',
        '支部大会决议',
        '上级审批意见',
      ]
      const row = {
        id: `transfer-${data.transfers.length}`,
        direction: body.direction,
        profile_id: body.profile_id ?? `member-in-${data.transfers.length}`,
        member_name: '',
        stage: '',
        org_unit_id: org.id,
        org_name: org.name,
        counterpart_org: body.counterpart_org,
        letter_no: body.letter_no,
        issued_on: body.issued_on,
        valid_until: body.valid_until || addDays(body.issued_on, 90),
        status: 'pending',
        settled_on: null,
        receipt_no: '',
        note: body.note || '',
        revoked_on: null,
        revoke_reason: '',
        revision: 1,
        created_at: `${body.issued_on}T09:00:00`,
        history: [],
      }
      let notice
      let extra = {}
      if (body.direction === 'out') {
        assert.equal(
          transferState(data.transfers, row.profile_id),
          'in_place',
          '只有在册党员可以办理转出',
        )
        const target = body.profile_id === data.profile.id ? data.profile : transferMember
        assert.ok(
          ['probationary', 'member'].includes(target.current_stage),
          '培养对象不办组织关系接转',
        )
        Object.assign(row, { member_name: target.name, stage: target.current_stage })
        notice =
          '介绍信已登记为待接收：本人持介绍信到对方组织报到并回执后才算转出完成；到期未回执请核实是否已报到'
      } else {
        const target = body.profile_id
          ? body.profile_id === data.profile.id
            ? data.profile
            : transferMember
          : { name: body.name, current_stage: body.current_stage }
        assert.ok(
          ['probationary', 'member'].includes(target.current_stage),
          '转入只面向预备党员与正式党员',
        )
        Object.assign(row, { member_name: target.name, stage: target.current_stage })
        const required =
          target.current_stage === 'member' ? [...base, '转正申请书', '预备期考察记录'] : base
        extra = {
          created_profile: !body.profile_id,
          archive: { check_id: `check-${data.transfers.length}`, required, missing: required },
        }
        notice =
          '转入已登记为待核对档案：请按档案清单逐项核对本人档案并回执；缺项不影响登记，核对完成后回执即可'
      }
      row.history.push({
        revision: 1,
        action: 'create',
        actor_id: 'viewer-a',
        reason: body.reason,
        created_at: row.created_at,
      })
      data.transfers.push(row)
      return route.fulfill(
        ok({
          ...transferView(
            { ...row, state: transferState(data.transfers, row.profile_id) },
            today,
          ),
          ...extra,
          notice,
        }),
      )
    }
    if (path.startsWith('/member-full/transfers/')) {
      const parts = path.split('/')
      const row = data.transfers.find((item) => item.id === parts[3])
      assert.ok(row, '接转记录必须存在')
      if (parts[4] === 'settle') {
        assert.equal(row.status, 'pending', '只有待接收的接转可以回执')
        row.status = 'settled'
        row.settled_on = body.settled_on || today
        row.receipt_no = body.receipt_no || ''
        row.revision += 1
        row.history.push({
          revision: row.revision,
          action: 'settle',
          actor_id: 'viewer-a',
          reason: body.reason,
          created_at: `${today}T10:00:00`,
        })
        const state = transferState(data.transfers, row.profile_id)
        return route.fulfill(
          ok({
            ...transferView({ ...row, state }, today),
            notice:
              row.direction === 'out'
                ? '已登记回执：本次转出完成，该党员不再计入本组织在册名单与应评议名单'
                : '已登记回执：转入办结，档案缺项仍可在档案面板逐项补齐',
          }),
        )
      }
      if (parts[4] === 'revoke') {
        assert.notEqual(row.status, 'revoked', '已作废的接转不能重复作废')
        row.status = 'revoked'
        row.revoked_on = today
        row.revoke_reason = body.reason
        row.revision += 1
        row.history.push({
          revision: row.revision,
          action: 'revoke',
          actor_id: 'viewer-a',
          reason: body.reason,
          created_at: `${today}T11:00:00`,
        })
        return route.fulfill(
          ok({
            ...transferView(
              { ...row, state: transferState(data.transfers, row.profile_id) },
              today,
            ),
            notice: '已作废：该次接转视同未发生，组织关系状态按其余有效记录重新推导；记录保留可查',
          }),
        )
      }
      if (method === 'GET') {
        return route.fulfill(
          ok({
            ...transferView(
              { ...row, state: transferState(data.transfers, row.profile_id) },
              today,
            ),
            history: row.history,
            notice: TRANSFER_NOTICE,
          }),
        )
      }
    }
    // ---------------------------- 上级审批 / 备案（T-MEM-11） ----------------------------
    if (path === '/member-full/upper-reports/export' && method === 'GET') {
      data.exported = true
      return route.fulfill({
        status: 200,
        contentType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        body: '界面验证用台账样例',
      })
    }
    if (path === '/member-full/upper-reports' && method === 'GET') {
      const rows = data.upperReports
        .filter((row) => !url.searchParams.has('item') || row.item === url.searchParams.get('item'))
        .filter((row) => !url.searchParams.has('kind') || row.kind === url.searchParams.get('kind'))
        .filter(
          (row) => !url.searchParams.has('status') || row.status === url.searchParams.get('status'),
        )
        .filter((row) => url.searchParams.get('overdue') !== 'true' || upperOverdue(row, today))
        // 列表不带留痕：留痕要走单条明细接口
        .map(({ history, ...row }) => {
          void history
          return upperReportView(row, today)
        })
      return route.fulfill(
        ok({
          items: rows,
          total: rows.length,
          page: 1,
          page_size: 20,
          summary: upperSummary(data.upperReports, today),
          items_catalog: upperItems,
          notice: UPPER_NOTICE,
        }),
      )
    }
    if (path === '/member-full/upper-reports' && method === 'POST') {
      const item = upperItems.find((entry) => entry.item === body.item)
      assert.ok(item, '报送事项必须在目录内')
      const target = body.profile_id === data.profile.id ? data.profile : transferMember
      assert.ok(
        upperStageRank(target.current_stage) >= upperStageRank(item.stage),
        '阶段未到该环节不能报送',
      )
      const row = {
        id: `upper-${data.upperReports.length}`,
        item: body.item,
        kind: item.kind,
        profile_id: body.profile_id,
        member_name: target.name,
        stage: target.current_stage,
        org_unit_id: org.id,
        org_name: org.name,
        upper_org: body.upper_org,
        letter_no: body.letter_no || '',
        submitted_on: body.submitted_on,
        materials: item.materials,
        status: 'submitted',
        result: '',
        decided_on: null,
        reply_no: '',
        decide_note: '',
        note: body.note || '',
        revoked_on: null,
        revoke_reason: '',
        revision: 1,
        created_at: `${body.submitted_on}T09:00:00`,
        history: [],
      }
      row.history.push({
        revision: 1,
        action: 'submit',
        actor_id: 'viewer-a',
        reason: body.reason,
        created_at: row.created_at,
      })
      data.upperReports.push(row)
      return route.fulfill(
        ok({
          ...upperReportView(row, today),
          notice:
            '已登记报送：本记录只表示材料已报出，党员阶段不受影响；收到上级批复后在台账回填批复结果',
        }),
      )
    }
    if (path.startsWith('/member-full/upper-reports/')) {
      const parts = path.split('/')
      const row = data.upperReports.find((entry) => entry.id === parts[3])
      assert.ok(row, '报送记录必须存在')
      if (parts[4] === 'settle') {
        assert.equal(row.status, 'submitted', '只有待批复的报送可以回填')
        if (body.result !== 'supplement') assert.ok(body.reply_no, '同意 / 不同意必须有批复文号')
        if (body.result === 'supplement') assert.ok(body.decide_note, '需补充材料必须写清缺什么')
        row.status = 'settled'
        row.result = body.result
        row.decided_on = body.decided_on || today
        row.reply_no = body.reply_no || ''
        row.decide_note = body.decide_note || ''
        row.revision += 1
        row.history.push({
          revision: row.revision,
          action: 'settle',
          actor_id: 'viewer-a',
          reason: body.reason,
          created_at: `${today}T10:00:00`,
        })
        const notice =
          body.result === 'agreed'
            ? '已回填批复「同意 / 批准」。党员阶段不会自动变化：请按程序由授权人员在阶段流转中人工办理，并把批复件归入档案'
            : body.result === 'rejected'
              ? '已回填批复「不同意」。系统不自动回退阶段、不自动移出名册；请按上级结论与有关规定研究后续处理并人工办理阶段调整'
              : '已回填「需补充材料」：补齐后重新报送，本次报送记录保留可查'
        return route.fulfill(ok({ ...upperReportView(row, today), notice }))
      }
      if (parts[4] === 'revoke') {
        assert.notEqual(row.status, 'revoked', '已作废的报送不能重复作废')
        row.status = 'revoked'
        row.revoked_on = today
        row.revoke_reason = body.reason
        row.revision += 1
        row.history.push({
          revision: row.revision,
          action: 'revoke',
          actor_id: 'viewer-a',
          reason: body.reason,
          created_at: `${today}T11:00:00`,
        })
        return route.fulfill(
          ok({
            ...upperReportView(row, today),
            notice: '已作废：该次报送视同未发生，需重新报送时按新记录登记；原记录保留可查',
          }),
        )
      }
      if (method === 'GET') {
        return route.fulfill(
          ok({ ...upperReportView(row, today), history: row.history, notice: UPPER_NOTICE }),
        )
      }
    }
    if (path === '/member-full/stats') {
      data.statsOrgCalls.push(url.searchParams.get('org_unit_id') ?? '')
      const rows = (data.empty ? [] : [data.profile, transferMember]).filter(
        (item) =>
          (!url.searchParams.has('year') || Number(url.searchParams.get('year')) === item.year) &&
          (!url.searchParams.has('batch_no') ||
            url.searchParams.get('batch_no') === item.batch_no) &&
          (!url.searchParams.has('org_unit_id') ||
            url.searchParams.get('org_unit_id') === item.org_unit_id),
      )
      const byStage = {}
      for (const item of rows) byStage[item.current_stage] = (byStage[item.current_stage] ?? 0) + 1
      return route.fulfill(
        ok({
          year: url.searchParams.has('year') ? Number(url.searchParams.get('year')) : null,
          batch_no: url.searchParams.get('batch_no'),
          org_unit_id: url.searchParams.get('org_unit_id'),
          by_stage: byStage,
          total: rows.length,
        }),
      )
    }
    if (path === '/member-full/batches') {
      if (method === 'POST') {
        await new Promise((resolve) => setTimeout(resolve, 150))
        data.batches.push({
          ...body,
          id: `batch-${data.batches.length}`,
          org_name: org.name,
          member_count: 0,
          is_active: true,
        })
        return route.fulfill(ok(data.batches.at(-1)))
      }
      return route.fulfill(
        ok(
          pagination(
            data.batches.filter(
              (item) =>
                !url.searchParams.has('year') || item.year === Number(url.searchParams.get('year')),
            ),
            url.searchParams,
          ),
        ),
      )
    }
    if (path === '/member-full/reminders')
      return route.fulfill(
        ok(
          pagination(
            data.reminders.filter(
              (item) =>
                !url.searchParams.has('status') || item.status === url.searchParams.get('status'),
            ),
            url.searchParams,
          ),
        ),
      )
    if (path.endsWith('/resolve')) {
      Object.assign(data.reminders[0], body, { processed_at: `${today}T09:00:00` })
      return route.fulfill(ok(data.reminders[0]))
    }
    if (path === '/member-full/votes/summary') {
      const rows = data.votes.filter(
        (item) =>
          item.batch_no === url.searchParams.get('batch_no') &&
          item.round_no === Number(url.searchParams.get('round_no')),
      )
      const tally = {}
      for (const row of rows) {
        tally[row.profile_id] ??= { agree: 0, disagree: 0, abstain: 0, voted_by_me: false }
        tally[row.profile_id][row.vote] += 1
        tally[row.profile_id].voted_by_me ||= row.voter_id === viewer
      }
      return route.fulfill(
        ok({
          batch_no: url.searchParams.get('batch_no'),
          round_no: Number(url.searchParams.get('round_no')),
          voter_count: new Set(rows.map((item) => item.voter_id)).size,
          tally,
          data_level: 'sensitive',
          data_level_label: '敏感',
          cloud_allowed: false,
          embedding_allowed: true,
          note: '汇总仅为过程记录，组织结论由人工形成；无记名，不给出投票人身份。',
        }),
      )
    }
    if (path === '/member-full/votes') {
      data.votes.push(
        ...body.votes.map((vote) => ({
          ...vote,
          batch_no: body.batch_no,
          round_no: body.round_no,
          voter_id: viewer,
        })),
      )
      return route.fulfill(ok({ recorded: body.votes.length }))
    }
    // 选优结论（拟推荐名单）：登记 → 送审 → 另一位组织人员审核（T-MEM-13）
    if (path === '/member-full/selections' && method === 'GET') {
      const rows = data.selections.filter(
        (row) =>
          (!url.searchParams.has('batch_no') ||
            row.batch_no === url.searchParams.get('batch_no')) &&
          (!url.searchParams.has('round_no') ||
            row.round_no === Number(url.searchParams.get('round_no'))),
      )
      const summary = { draft: 0, pending: 0, approved: 0, rejected: 0 }
      for (const row of rows) summary[row.review_status] += 1
      return route.fulfill(
        ok({
          ...pagination(rows.map((row) => selectionView(row, viewer)), url.searchParams),
          summary,
          notice: selectionNotice,
          boundary: selectionBoundary,
        }),
      )
    }
    if (path === '/member-full/selections' && method === 'POST') {
      const row = {
        id: `selection-${data.selections.length + 1}`,
        batch_no: body.batch_no,
        round_no: body.round_no,
        target_stage: body.target_stage,
        candidate_ids: body.candidate_ids,
        basis: body.basis,
        research_on: body.research_on,
        research_method: body.research_method,
        review_status: 'draft',
        revision: 1,
        submitted_by: null,
        reviewed_by: null,
        reviewed_at: null,
        review_comment: '',
        // 依据快照是"本轮无记名汇总按拟推荐名单裁剪"，不含投票人身份，也不替组织排序
        evidence: {
          batch_no: body.batch_no,
          round_no: body.round_no,
          voter_count: new Set(
            data.votes
              .filter(
                (item) =>
                  item.batch_no === body.batch_no && item.round_no === body.round_no,
              )
              .map((item) => item.voter_id),
          ).size,
          tally: selectionTally(body.batch_no, body.round_no, body.candidate_ids),
          evidence_note:
            '依据位置：本轮选优投票的无记名汇总（按拟推荐名单裁剪），只含票数与投票人数、不含投票人身份；票数不构成结论',
        },
        revisions: [
          {
            revision: 1,
            action: 'create',
            actor_id: viewer,
            reason: body.reason,
            created_at: `${today}T09:00:00`,
          },
        ],
      }
      data.selections.push(row)
      return route.fulfill(ok(selectionView(row, viewer, true)))
    }
    const selectionMatch = path.match(/^\/member-full\/selections\/([^/]+)(\/submit|\/review)?$/)
    if (selectionMatch) {
      const row = data.selections.find((item) => item.id === selectionMatch[1])
      if (!row) return route.fulfill(failed(404, '选优结论不存在'))
      if (!selectionMatch[2] && method === 'GET') {
        return route.fulfill(ok(selectionView(row, viewer, true)))
      }
      if (!selectionMatch[2] && method === 'PATCH') {
        assert.equal(body.expected_revision, row.revision, '过期版本号不得覆盖已改内容')
        Object.assign(row, {
          target_stage: body.target_stage ?? row.target_stage,
          candidate_ids: body.candidate_ids ?? row.candidate_ids,
          basis: body.basis ?? row.basis,
          research_on: body.research_on ?? row.research_on,
          research_method: body.research_method ?? row.research_method,
          // 修订即回到草稿：必须重新送审
          review_status: 'draft',
          submitted_by: null,
          reviewed_by: null,
          reviewed_at: null,
          review_comment: '',
          revision: row.revision + 1,
          evidence: {
            ...row.evidence,
            voter_count: new Set(
              data.votes
                .filter(
                  (item) =>
                    item.batch_no === row.batch_no && item.round_no === row.round_no,
                )
                .map((item) => item.voter_id),
            ).size,
            tally: selectionTally(row.batch_no, row.round_no, row.candidate_ids),
          },
        })
        row.revisions.push({
          revision: row.revision,
          action: 'revise',
          actor_id: viewer,
          reason: body.reason,
          created_at: `${today}T09:30:00`,
        })
        return route.fulfill(ok(selectionView(row, viewer, true)))
      }
      if (selectionMatch[2] === '/submit') {
        if (row.review_status !== 'draft' && row.review_status !== 'rejected') {
          return route.fulfill(failed(409, '当前内容不在可送审状态'))
        }
        assert.equal(body.expected_revision, row.revision, '过期版本号不得覆盖已改内容')
        row.review_status = 'pending'
        row.submitted_by = viewer
        row.revision += 1
        row.revisions.push({
          revision: row.revision,
          action: 'submit',
          actor_id: viewer,
          reason: body.reason,
          created_at: `${today}T10:00:00`,
        })
        return route.fulfill(ok(selectionView(row, viewer, true)))
      }
      if (selectionMatch[2] === '/review') {
        if (row.review_status !== 'pending') {
          return route.fulfill(failed(409, '当前内容不在待审核状态'))
        }
        if (row.submitted_by === viewer) {
          return route.fulfill(failed(403, '请由另一位有权限的组织人员审核'))
        }
        assert.equal(body.expected_revision, row.revision, '过期版本号不得覆盖已改内容')
        row.review_status = body.decision
        row.reviewed_by = viewer
        row.reviewed_at = `${today}T11:00:00`
        row.review_comment = body.reason
        row.revision += 1
        row.revisions.push({
          revision: row.revision,
          action: 'review',
          actor_id: viewer,
          reason: body.reason,
          created_at: `${today}T11:00:00`,
        })
        return route.fulfill(ok(selectionView(row, viewer, true)))
      }
      return route.fulfill(failed(404, `验证未覆盖接口：${method} ${path}`))
    }
    // 团组织推优：只登记与该人的事实，不判断年龄、不阻断业务（T-MEM-06）
    if (path === '/member-full/league-recommendations' && method === 'GET') {
      const wanted = url.searchParams.get('profile_ids')
        ? url.searchParams.get('profile_ids').split(',')
        : url.searchParams.has('profile_id')
          ? [url.searchParams.get('profile_id')]
          : null
      const rows = data.leagueRecommendations.filter(
        (row) => !wanted || wanted.includes(row.profile_id),
      )
      const active = rows.filter((row) => !row.revoked_on).length
      return route.fulfill(
        ok({
          ...pagination(rows.map((row) => recommendationView(row)), url.searchParams),
          summary: { total: rows.length, active, revoked: rows.length - active },
          status: recommendationStatusList().filter(
            (item) => !wanted || wanted.includes(item.profile_id),
          ),
          age_notice: ageNotice,
          notice: '推优记录只登记事实：系统不判断年龄、不替代支部研究，也不阻断选优与阶段流转',
        }),
      )
    }
    if (path === '/member-full/league-recommendations' && method === 'POST') {
      const row = {
        id: `recommendation-${data.leagueRecommendations.length + 1}`,
        profile_id: body.profile_id,
        league_org: body.league_org,
        recommended_on: body.recommended_on,
        note: body.note,
        revoked_on: null,
        revoke_reason: '',
        revision: 1,
      }
      data.leagueRecommendations.push(row)
      return route.fulfill(ok(recommendationView(row)))
    }
    const recommendationMatch = path.match(
      /^\/member-full\/league-recommendations\/([^/]+)\/revoke$/,
    )
    if (recommendationMatch) {
      const row = data.leagueRecommendations.find((item) => item.id === recommendationMatch[1])
      if (!row) return route.fulfill(failed(404, '推优记录不存在'))
      if (row.revoked_on) return route.fulfill(failed(409, '该推优记录已作废'))
      row.revoked_on = today
      row.revoke_reason = body.reason
      row.revision += 1
      return route.fulfill(ok(recommendationView(row)))
    }
    if (path === '/member-full/scoring')
      return route.fulfill(
        ok({
          year: body.year,
          weighted_score:
            data.profile.cultivation.find((item) => item.period === String(body.year))?.score ??
            null,
          rule_version: '样例规则',
          disclaimer: '评分仅供人工核验，不自动形成组织认定。',
          dimensions: {
            theory_test: {
              value: data.profile.cultivation[0]?.score ?? null,
              status: 'known',
              weight: 0.3,
              evidence: data.profile.cultivation.map((item) => ({
                source_id: item.id,
                period: item.period,
                note: item.source_note,
              })),
            },
          },
          risks: [],
          missing: [],
        }),
      )
    if (path === '/member-full/archive-check')
      return route.fulfill(
        ok({
          check_id: 'check-a',
          checked_at: `${today}T09:00:00`,
          rule_version: '样例规则',
          note: '档案检查结果仅为提示。',
          result: {
            required_for: '发展对象材料检查',
            missing: ['政治审查材料'],
            irregular: [],
            risks: [],
          },
        }),
      )
    if (path.endsWith('/review') && path.includes('/member-full/materials/')) {
      const material = data.profile.materials[0]
      Object.assign(material, body)
      material.review_history.push({
        revision: material.review_history.length + 1,
        action: 'review',
        actor_id: viewer,
        created_at: `${today}T09:00:00`,
        reason: body.reason,
        snapshot: { review_status: body.review_status, note: body.note },
      })
      return route.fulfill(ok(material))
    }
    if (path.startsWith('/member-full/profiles/')) {
      if (path.endsWith('/materials')) {
        data.profile.materials.push({
          ...body,
          id: 'material-new',
          review_status: 'pending',
          note: '',
          review_history: [],
        })
        return route.fulfill(ok(data.profile.materials.at(-1)))
      }
      if (path.endsWith('/cultivation')) {
        data.profile.cultivation.push({
          ...body,
          id: `cultivation-${data.profile.cultivation.length}`,
          verified_at: `${today}T09:00:00`,
        })
        return route.fulfill(ok(data.profile.cultivation.at(-1)))
      }
      if (path.endsWith('/transition')) {
        data.profile.stage_history.push({
          id: 'transition-a',
          from_stage: data.profile.current_stage,
          to_stage: body.target_stage,
          ...body,
          decided_by: viewer,
        })
        data.profile.current_stage = body.target_stage
        return route.fulfill(ok(data.profile))
      }
      if (path.endsWith('/sync-reminders'))
        return route.fulfill(ok({ created: 0, notice: '提醒已同步' }))
      if (method === 'PATCH') Object.assign(data.profile, body)
      return route.fulfill(ok(data.profile))
    }
    if (path === '/meeting/org-units') return route.fulfill(ok({ items: [org] }))
    if (path === '/meeting/records' || path === '/meeting/history') {
      if (method === 'POST') {
        const record = {
          ...structuredClone(meeting),
          ...body,
          id: `meeting-${data.records.length}`,
          source_doc_ids: body.source_doc_ids,
          sources: body.source_doc_ids.length ? [source] : [],
        }
        updateMissing(record)
        data.records.push(record)
        return route.fulfill(ok(record))
      }
      return route.fulfill(
        ok(
          pagination(
            data.empty
              ? []
              : data.records.filter((record) => path !== '/meeting/history' || record.archived_at),
            url.searchParams,
          ),
        ),
      )
    }
    if (path === '/meeting/tasks')
      return route.fulfill(
        ok(
          pagination(
            data.restricted
              ? [{ id: 'restricted-task', restricted: true }]
              : data.records.flatMap((record) => record.tasks),
            url.searchParams,
          ),
        ),
      )
    if (path === '/meeting/stats')
      return route.fulfill(
        ok({
          year: Number(url.searchParams.get('year')),
          counts: { total: data.records.length },
          by_type: {
            branch_member_meeting: {
              label: '支部大会',
              required: 4,
              performed: data.records.filter((record) => record.review_status === 'approved')
                .length,
              total_registered: data.records.length,
              period: 'quarter',
              period_text: '每季度至少 1 次',
              basis: '支部党员大会一般每季度召开 1 次',
            },
            branch_committee_meeting: {
              label: '支委会',
              required: 12,
              performed: 0,
              total_registered: 0,
              period: 'month',
              period_text: '每月至少 1 次',
              basis: '党支部委员会会议一般每月召开 1 次',
            },
          },
          attendance_rate: { value: 0.5, numerator: 1, denominator: 2, status: 'known' },
          minutes_completeness: { value: null, numerator: 0, denominator: 0, status: 'pending' },
          evidence: [],
          missing: [],
          calculation_rule: '仅统计已审核记录；统计结果须人工确认。',
        }),
      )
    if (path === '/meeting/frequency')
      return route.fulfill(ok(structuredClone(frequency)))
    if (path === '/meeting/member-reviews/workspace')
      return route.fulfill(ok(reviewWorkspace(data, viewer, !readonly)))
    if (path === '/meeting/member-reviews/launch' && method === 'POST') {
      const created = data.memberReviews.filter((row) => !row.review_id)
      created.forEach((row, index) => {
        row.review_id = `review-new-${index}`
        row.revision = 1
        row.review_status = 'draft'
      })
      return route.fulfill(
        ok({
          year: body.year,
          org_unit_id: body.org_unit_id,
          org_name: org.name,
          created: created.length,
          skipped: data.memberReviews.length - created.length,
          target_total: data.memberReviews.length,
          items: created.map((row) => reviewTarget(row, viewer, !readonly)),
          notice: '已为在册党员建立本年度评议草稿；已有记录不会被覆盖',
        }),
      )
    }
    if (path === '/meeting/member-reviews' && method === 'POST') {
      const row = data.memberReviews.find((item) => item.profile_id === body.profile_id)
      assert.ok(row, '评议对象必须在本支部在册名册内')
      assert.equal(body.year, year)
      row.review_id = row.review_id || 'review-created'
      row.revision = 1
      row.review_status = 'draft'
      applyReviewPayload(row, body)
      return route.fulfill(ok({ id: row.review_id, year, revision: row.revision }))
    }
    if (path.startsWith('/meeting/member-reviews/')) {
      const parts = path.split('/')
      const row = data.memberReviews.find((item) => item.review_id === parts[3])
      if (!row) return route.fulfill(failed(404, '评议记录不存在'))
      if (parts[4] === 'submit') {
        row.review_status = 'pending'
        row.submitted_by = viewer
        row.revision += 1
        return route.fulfill(ok(reviewTarget(row, viewer, !readonly)))
      }
      if (parts[4] === 'review') {
        // 提交人不能自审：界面上能不能点\"审核\"由后端逐行给的 can_review 决定
        assert.notEqual(row.submitted_by, viewer, '提交人不能审核自己的版本')
        row.review_status = body.decision === 'approved' ? 'approved' : 'rejected'
        row.reviewed_by = viewer
        row.review_comment = body.reason
        return route.fulfill(ok(reviewTarget(row, viewer, !readonly)))
      }
      if (method === 'PATCH') {
        applyReviewPayload(row, body)
        row.revision += 1
        row.review_status = 'draft'
        return route.fulfill(ok(reviewTarget(row, viewer, !readonly)))
      }
      return route.fulfill(ok(reviewDetail(row, viewer, !readonly)))
    }
    if (path.startsWith('/meeting/tasks/')) {
      const task = data.records
        .flatMap((record) => record.tasks)
        .find((item) => path.includes(item.id))
      Object.assign(task, body, { status: path.endsWith('/handle') ? body.status : 'active' })
      return route.fulfill(ok({ task, notice: '任务已保存' }))
    }
    if (path.startsWith('/meeting/records/')) {
      const parts = path.split('/')
      const record = data.records.find((item) => item.id === parts[3])
      if (!record) return route.fulfill(failed(404, '活动不存在'))
      if (parts[4] === 'revisions') return route.fulfill(ok({ items: data.revisions }))
      if (parts[4] === 'export') return route.fulfill(ok({ record, revisions: data.revisions }))
      if (parts[4] === 'tasks') {
        const task = {
          ...body,
          id: `task-${record.tasks.length}`,
          record_id: record.id,
          status: 'pending',
          handle_note: '',
        }
        assert.equal(
          Array.from(record.transcript).slice(body.source_start, body.source_end).join(''),
          body.task_text,
        )
        record.tasks.push(task)
        return route.fulfill(ok({ task, notice: '待人工确认' }))
      }
      if (method === 'PATCH') {
        assert.equal(body.expected_revision, record.revision)
        if (body.transcript !== record.transcript && !body.minutes) record.minutes = {}
        Object.assign(record, body, {
          context: { ...record.context, agenda: body.agenda, notice: body.notice },
        })
      } else if (method === 'POST') {
        assert.equal(body.expected_revision, record.revision)
        if (parts[4] === 'generate-agenda')
          record.context = {
            agenda: '样例议程：学习、讨论、落实',
            notice: '样例通知草稿：请按期参加',
          }
        if (parts[4] === 'generate-minutes') {
          record.minutes = {}
          for (const [label, key] of [
            ['学习要点', 'learning_points'],
            ['讨论共识', 'consensus'],
            ['工作要求', 'requirements'],
          ]) {
            const quote = record.transcript.split('\n').find((line) => line.includes(label))
            const start = Array.from(
              record.transcript.slice(0, record.transcript.indexOf(quote)),
            ).length
            record.minutes[key] = [
              { text: quote, quote, start, end: start + Array.from(quote).length },
            ]
          }
        }
        if (parts[4] === 'submit') {
          record.review_status = 'pending'
          record.submitted_by = viewer
        }
        if (parts[4] === 'review') {
          record.review_status = body.decision
          record.reviewed_by = viewer
          record.reviewed_at = `${today}T09:00:00`
          record.review_comment = body.reason
        }
        if (parts[4] === 'archive') {
          if (!data.allowArchive) return route.fulfill(failed(409, '学校尚未确认电子归档效力'))
          record.archived_at = `${today}T10:00:00`
          record.archive_policy_version = 1
        }
      }
      if (method !== 'GET') {
        record.revision += 1
        updateMissing(record)
        data.revisions.push({
          revision: record.revision,
          action: parts[4] || 'revise',
          actor_id: viewer,
          created_at: `${today}T09:00:00`,
          reason: body.reason,
          restricted: false,
          snapshot: structuredClone(record),
        })
      }
      return route.fulfill(
        ok(
          data.restricted
            ? {
                ...record,
                restricted: true,
                title: '关联资料权限变更，内容待复核',
                transcript: '',
                participants: [],
                minutes: {},
                sources: [],
                source_doc_ids: [],
                context: {},
                tasks: [],
              }
            : record,
        ),
      )
    }
    return route.fulfill(failed(404, `验证未覆盖接口：${method} ${path}`))
  })
  const page = await ctx.newPage()
  page.on('pageerror', (err) => errors.push(err.message))
  return { ctx, page }
}

async function visible(page, text) {
  await page
    .getByText(text, { exact: false })
    .and(page.locator(':visible'))
    .first()
    .waitFor({ state: 'visible' })
}
async function click(page, name) {
  await page.getByRole('button', { name, exact: true }).click()
}
async function tab(page, name) {
  await page.getByRole('tab', { name, exact: true }).click()
}
async function screenshot(page, name) {
  await page.evaluate(() => {
    window.scrollTo(0, 0)
    for (const table of document.querySelectorAll('.wb-table-wrap, .table-wrap')) table.scrollLeft = 0
  })
  await page.screenshot({ path: resolve(OUT, `${name}.png`), fullPage: true })
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth + 1,
  )
  if (overflow) {
    const diagnosis = await page.evaluate(() => {
      const limit = window.innerWidth + 1
      const path = (element) => {
        const parts = []
        let node = element
        for (let depth = 0; node && depth < 5; depth += 1) {
          const id = node.id ? `#${node.id}` : ''
          const cls = node.className && typeof node.className === 'string'
            ? `.${node.className.trim().split(/\s+/).slice(0, 3).join('.')}`
            : ''
          parts.unshift(`${node.tagName.toLowerCase()}${id}${cls}`)
          if (node.tagName.toLowerCase() === 'main' || node.tagName.toLowerCase() === 'body') break
          node = node.parentElement
        }
        return parts.join(' > ')
      }
      const wide = []
      const spilling = []
      for (const element of document.querySelectorAll('body *')) {
        const rect = element.getBoundingClientRect()
        if (rect.right > limit || rect.width > limit) {
          wide.push(`${Math.round(rect.right)} ${Math.round(rect.width)} ${path(element)}`)
        }
        if (element.scrollWidth > element.clientWidth + 1 && element.clientWidth > 0) {
          spilling.push(
            `${element.scrollWidth}/${element.clientWidth} ${path(element)}`,
          )
        }
      }
      return {
        docScroll: document.documentElement.scrollWidth,
        bodyScroll: document.body.scrollWidth,
        inner: window.innerWidth,
        wide: wide.sort((a, b) => Number(b.split(' ')[0]) - Number(a.split(' ')[0])).slice(0, 12),
        spilling: spilling.slice(0, 12),
      }
    })
    console.log(`[overflow] ${name}`, JSON.stringify(diagnosis, null, 1))
  }
  assert.equal(overflow, false, `${name} 页面不得横向溢出`)
}
async function recordAction(page, button) {
  await click(page, button)
  const dialog = page.getByRole('dialog').filter({ has: page.getByRole('checkbox') })
  await dialog.getByRole('textbox').fill('界面验证：核对原文、参会及当前版本')
  await dialog.getByRole('checkbox').check()
  await dialog.getByRole('button', { name: /^确认/ }).click()
}

try {
  const { page, ctx } = await context()
  if (audit) {
    for (const route of ['knowledge', 'members', 'meeting']) {
      await page.goto(`${BASE}/${route}`, { waitUntil: 'networkidle' })
      if (route === 'knowledge') await page.locator('tbody tr').first().click()
      if (route === 'meeting') await page.locator('.meeting__row').first().click()
      await screenshot(page, `before-${route}`)
    }
    assert.deepEqual(errors, [])
    console.log('已记录3个原始界面，仅使用接口样例。')
    await ctx.close()
  } else {
    await page.goto(`${BASE}/knowledge`, { waitUntil: 'networkidle' })
    await page.locator('tbody tr').first().click()
    await visible(page, '待处理')
    await click(page, '处理待检索片段')
    await visible(page, '可检索')
    const file = page.waitForEvent('download')
    await click(page, '下载原件')
    assert.equal((await file).suggestedFilename(), doc.file_name)
    await page.getByText('修正文档元数据', { exact: true }).click()
    await page.getByLabel('文件标题', { exact: true }).fill('样例：更新后的归档细则')
    await page.getByLabel('修正理由').fill('核对已发布原件后修正标题')
    await click(page, '保存元数据')
    await visible(page, '元数据已保存')
    assert.equal(state.doc.title, '样例：更新后的归档细则')
    state.rejectMetadata = true
    await page.getByLabel('修正理由').fill('验证权限拒绝')
    await click(page, '保存元数据')
    await visible(page, '共享公共库只能由系统管理员维护')
    await visible(page, 'ui-fixture-error')
    state.rejectMetadata = false
    await page.getByLabel('修正理由').fill('权限错误验证后重新核对本校资料')
    await click(page, '保存元数据')
    await visible(page, '元数据已保存')
    checks.push('知识库处理、授权下载、元数据保存和权限错误')
    await page.getByText('修正文档元数据', { exact: true }).click()
    await screenshot(page, 'knowledge-desktop')

    await page.goto(`${BASE}/members`, { waitUntil: 'networkidle' })
    await visible(page, '陈见微的办理档案')
    const materialTab = page.getByRole('tab', { name: '档案与材料', exact: true })
    await materialTab.focus()
    await materialTab.press('ArrowRight')
    const cultivationTab = page.getByRole('tab', { name: '培养与评分', exact: true })
    assert.equal(await cultivationTab.getAttribute('aria-selected'), 'true')
    assert.equal(
      await cultivationTab.evaluate((element) => element === document.activeElement),
      true,
    )
    await cultivationTab.press('ArrowLeft')
    assert.equal(await materialTab.getAttribute('aria-selected'), 'true')
    await click(page, '登记人工审核')
    await page.getByRole('dialog').press('Escape')
    await page.getByRole('dialog').waitFor({ state: 'hidden' })
    assert.equal(
      await page
        .getByRole('button', { name: '登记人工审核', exact: true })
        .evaluate((element) => element === document.activeElement),
      true,
    )
    checks.push('键盘切换、弹窗Escape关闭与焦点返回')
    await click(page, '登记人工审核')
    await page.getByRole('dialog').getByLabel('审核意见', { exact: true }).fill('原件已逐项核验')
    await page.getByRole('dialog').getByLabel('审核依据 / 理由').fill('依据现有材料归档要求核验')
    await click(page, '保存人工审核')
    await visible(page, '人工核验通过')
    await page.getByText('查看审核历史（1）', { exact: true }).click()
    await visible(page, '原件已逐项核验')
    checks.push('材料人工审核与历史展示')
    // 字段级敏感分级（T-MEM-12）：涉密材料在界面上标出密级，第三人字段正文不展示
    await visible(page, '涉密级材料：不进名册')
    await visible(page, '涉密材料正文不在界面展示')
    checks.push('涉密材料标出密级且第三人字段正文不展示')
    await tab(page, '培养与评分')
    await page.getByText('登记培养与表现记录', { exact: true }).click()
    await page.getByLabel('分值（无评分证据时留空）').fill('0')
    await page.getByLabel('证据来源说明').fill('样例理论学习核验记录')
    await click(page, '保存培养记录')
    await visible(page, '培养记录及来源说明已保存')
    assert.equal(state.profile.cultivation[0].score, 0)
    assert.equal(state.profile.cultivation[0].period, String(year))
    await click(page, '生成辅助评分')
    await visible(page, `${year}年度辅助评分`)
    checks.push('培养证据、零分保留与按年度评分')
    await tab(page, '人工流转')
    const decisionButton = page.getByRole('button', { name: '登记人工决定', exact: true })
    assert.equal(await decisionButton.isDisabled(), true)
    await page.getByLabel('决定依据', { exact: true }).fill('样例支委会决定及已核验材料')
    await page.getByLabel('组织意见', { exact: true }).fill('已人工核对培养期与材料')
    await page.getByRole('checkbox', { name: /我已核对材料/ }).check()
    await decisionButton.click()
    await visible(page, '人工阶段决定已登记')
    assert.equal(state.profile.current_stage, 'candidate')
    await tab(page, '办理记录')
    await visible(page, '样例支委会决定及已核验材料')
    checks.push('人工确认后的阶段登记及决策记录')
    await tab(page, '档案检查')
    await click(page, '运行档案检查')
    await visible(page, '缺少材料：政治审查材料')
    checks.push('档案检查缺项提示')
    await tab(page, '年度批次')
    await click(page, '建立年度批次')
    await page.getByRole('dialog').getByLabel('批次号', { exact: true }).fill('B2')
    await page.getByRole('dialog').getByLabel('批次名称', { exact: true }).fill('秋季发展批次')
    await page.getByRole('dialog').getByLabel('建立理由').fill('年度工作计划')
    await click(page, '保存年度批次')
    await visible(page, '年度批次已建立')
    await page.getByRole('button', { name: '查看批次人员', exact: true }).first().click()
    await visible(page, '陈见微的办理档案')
    assert.equal(await page.getByLabel('名册年度', { exact: true }).inputValue(), String(year))
    // 名册按支部筛选（T-MEM-02）：选项来自权限范围内的组织；选中后名册列表与名册统计
    // 必须带同一个 org_unit_id——只看列表筛、统计还是整个院系，就是"假筛选"
    const selOrgFilter = page.locator('#roster-org')
    assert.equal(await selOrgFilter.locator('option').count(), 2, '支部筛选应为「全部支部」+ 1 个本支部')
    assert.equal(
      await page.locator('label.wb-field').filter({ hasText: '支部' }).count(),
      1,
      '支部筛选要有可见的「支部」标签',
    )
    await selOrgFilter.selectOption(org.id)
    await visible(page, '当前筛选共')
    assert.equal(await page.getByLabel('名册年度', { exact: true }).inputValue(), String(year))
    assert.ok(state.rosterOrgCalls.includes(org.id), '名册列表请求必须带上支部筛选')
    assert.ok(state.statsOrgCalls.includes(org.id), '名册统计必须与名册列表用同一个支部筛选')
    await selOrgFilter.selectOption('')
    await visible(page, '当前筛选共')
    checks.push('建立批次与完整名册筛选')
    await screenshot(page, 'members-desktop')
    await tab(page, '提醒待办')
    await click(page, '登记处理')
    await page.getByRole('dialog').getByLabel('处理说明').fill('培养期材料已核对')
    await click(page, '保存处理结果')
    await visible(page, '提醒处理结果已保存')
    assert.equal(state.reminders[0].status, 'closed')
    checks.push('提醒处理及状态回写')
    await tab(page, '多轮选优')
    await page.getByLabel('本年度批次').selectOption('B1')
    await page.getByLabel('陈见微的本轮选择').selectOption('agree')
    await click(page, '核对本轮记录（1）')
    await page.getByRole('dialog').getByRole('checkbox').check()
    await click(page, '提交本轮记录')
    await visible(page, '当前账号已提交本轮记录')
    assert.equal(state.votes.length, 1)
    assert.equal(
      await page.getByRole('button', { name: '核对本轮记录（1）', exact: true }).count(),
      0,
    )
    checks.push('多轮投票的人工核对、汇总和重复提交门禁')

    // --------------- 选优结论与团组织推优（T-MEM-13、T-MEM-06） ---------------
    await visible(page, '登记本轮拟推荐名单')
    // 记下结论生效前的档案阶段：结论生效不等于阶段流转，这里用前后对比来验证
    const selStageBefore = state.profile.current_stage
    assert.equal(selStageBefore, 'candidate')
    // 名单必须由人勾选：系统不按票数自动生成名单、不自动定等次
    assert.equal(
      await page.getByRole('button', { name: /自动生成|一键生成|系统推荐|按票数/ }).count(),
      0,
    )
    const selChenRow = page.getByRole('row').filter({ hasText: '陈见微' })
    const selLinRow = page.getByRole('row').filter({ hasText: '林舟' })
    // 前面的"人工流转"已把陈见微登记为发展对象：这里按"拟推荐接收为预备党员"登记
    await page.getByLabel('拟推进阶段').selectOption('probationary')
    // 陈见微是发展对象，可登记为"预备党员"；林舟已是正式党员，勾不上（与后端"只能向前"同一条规则）
    assert.equal(await selChenRow.getByLabel('陈见微纳入拟推荐名单').isDisabled(), false)
    assert.equal(await selLinRow.getByLabel('林舟纳入拟推荐名单').isDisabled(), true)
    checks.push('选优结论名单只由人勾选，阶段不到不给勾')

    // 团组织推优：只登记事实，系统不判断年龄；缺记录不阻断
    await selChenRow.getByRole('button', { name: '登记推优', exact: true }).click()
    const selRecDialog = page
      .getByRole('dialog')
      .filter({ has: page.getByLabel('推荐团组织') })
    await visible(page, '系统不判断年龄')
    await selRecDialog.getByLabel('推荐团组织').fill('合成学院团委')
    await selRecDialog.getByLabel('推荐日期').fill(today)
    await selRecDialog
      .getByLabel('推优说明（团组织意见，第三人信息按密级收敛）')
      .fill('团支书反映该同志在校表现积极')
    await selRecDialog.getByLabel('办理依据 / 说明').fill('收到团支部推优材料，登记台账')
    await click(page, '登记推优记录')
    await visible(page, '已登记团组织推优')
    assert.equal(state.leagueRecommendations.length, 1)
    assert.equal(state.leagueRecommendations[0].profile_id, profile.id)
    // 名册里没有出生年月：界面不能出现任何"系统判定年龄"的结论
    assert.equal(await page.getByText('系统判定为 28 周岁以下', { exact: false }).count(), 0)
    checks.push('团组织推优只登记事实并提示组织核对年龄')

    // 登记拟推荐名单：名单与依据都由人填写，投票汇总只是摊开给审核人核对的辅助材料
    await selChenRow.getByLabel('陈见微纳入拟推荐名单').check()
    await visible(page, '本轮辅助材料')
    await page
      .getByLabel('结论依据（必须写清引用了哪一轮投票 / 哪份材料 / 哪条培养记录）')
      .fill('依据第 1 轮选优投票汇总与培养考察记录，经支委会研究（细则第十三条）')
    await page.getByLabel('办理依据 / 说明').fill('支委会研究登记拟推荐名单')
    await click(page, '登记拟推荐名单（1）')
    await visible(page, '已登记拟推荐名单')
    assert.equal(state.selections.length, 1)
    assert.equal(state.selections[0].review_status, 'draft')
    assert.deepEqual(state.selections[0].candidate_ids, [profile.id])
    // 依据快照是无记名口径：有票数、有投票人数，没有投票人身份
    assert.equal(state.selections[0].evidence.voter_count, 1)
    assert.equal(state.selections[0].evidence.tally[profile.id].agree, 1)
    assert.ok(!JSON.stringify(state.selections[0].evidence).includes('viewer-a'))
    // 登记出来就是草稿：界面上没有"已生效"，也不给登记人自己审核的入口
    const selDraftRow = page.getByRole('row').filter({ hasText: '草稿' })
    await visible(page, '草稿')
    assert.equal(await selDraftRow.getByRole('button', { name: '审核', exact: true }).count(), 0)
    await visible(page, '不自动改阶段')
    checks.push('选定名单与依据后仍是草稿（不自动生成结论）')

    // 修订：保存为新版本并回到草稿，必须重新送审
    await selDraftRow.getByRole('button', { name: '修订名单与依据', exact: true }).click()
    const selEditDialog = page
      .getByRole('dialog')
      .filter({ has: page.getByLabel('修订理由') })
    await visible(page, '改完必须重新送审')
    await selEditDialog
      .getByLabel('结论依据')
      .fill('依据第 1 轮选优投票汇总、培养考察记录与党员大会意见（细则第十三条）')
    await selEditDialog.getByLabel('修订理由').fill('补充党员大会意见')
    await click(page, '保存修订')
    await visible(page, '已保存第 2 版')
    assert.equal(state.selections[0].revision, 2)
    assert.equal(state.selections[0].review_status, 'draft')
    assert.equal(state.selections[0].revisions.length, 2)
    checks.push('修订只追加版本并回到草稿')

    // 送审：自己不能审自己的版本
    await selDraftRow.getByRole('button', { name: '送审', exact: true }).click()
    const selSubmitDialog = page
      .getByRole('dialog')
      .filter({ has: page.getByLabel('送审说明') })
    await visible(page, '你自己不能审核自己的版本')
    await selSubmitDialog.getByLabel('送审说明').fill('名单与依据已核对，报另一位组织人员审核')
    await click(page, '提交审核')
    await visible(page, '已送另一位组织人员审核')
    assert.equal(state.selections[0].review_status, 'pending')
    assert.equal(state.selections[0].submitted_by, 'viewer-a')
    const selPendingRow = page.getByRole('row').filter({ hasText: '待审核' })
    assert.equal(await selPendingRow.getByRole('button', { name: '审核', exact: true }).count(), 0)
    checks.push('送审后登记人看不到审核入口')

    // 另一位组织人员审核通过：结论才生效
    const selReviewer = await context(1440, false, 'reviewer-b')
    await selReviewer.page.goto(`${BASE}/members`, { waitUntil: 'networkidle' })
    await tab(selReviewer.page, '多轮选优')
    await selReviewer.page.getByLabel('本年度批次').selectOption('B1')
    await visible(selReviewer.page, '待审核')
    const selReviewRow = selReviewer.page.getByRole('row').filter({ hasText: '待审核' })
    await selReviewRow.getByRole('button', { name: '审核', exact: true }).click()
    const selReviewDialog = selReviewer.page
      .getByRole('dialog')
      .filter({ has: selReviewer.page.getByLabel('审核意见') })
    await selReviewDialog.getByLabel('审核结果').selectOption('approved')
    await selReviewDialog.getByLabel('审核意见').fill('名单与依据核对无误，同意')
    await selReviewDialog.getByRole('button', { name: '提交审核结果', exact: true }).click()
    await visible(selReviewer.page, '结论已通过并生效')
    assert.equal(state.selections[0].review_status, 'approved')
    assert.equal(state.selections[0].reviewed_by, 'reviewer-b')
    await selReviewer.ctx.close()

    // 结论生效不等于阶段流转：档案阶段没被自动改动
    assert.equal(state.profile.current_stage, selStageBefore)
    // 工作区刷新要同时重取投票汇总与选优结论（结论可能在另一位组织人员那边刚审核过）
    const selRefresh = page
      .locator('.wb-toolbar')
      .getByRole('button', { name: '刷新', exact: true })
    assert.equal(await selRefresh.count(), 1)
    await selRefresh.click()
    await visible(page, '已通过')
    const selApprovedRow = page.getByRole('row').filter({ hasText: '已通过' })
    await selApprovedRow.getByRole('button', { name: '明细与留痕', exact: true }).click()
    const selDetailDialog = page
      .getByRole('dialog')
      .filter({ has: page.getByText('只追加留痕', { exact: false }) })
    await visible(page, '只追加留痕（4 版）')
    // 依据快照是无记名口径：摊开票数，不出现投票人身份
    await visible(page, '无记名汇总')
    const selHistory = selDetailDialog.locator('section', { hasText: '只追加留痕' })
    assert.equal(await selHistory.locator('li').count(), 4)
    assert.equal(await selHistory.getByText('操作人 viewer-a', { exact: false }).count(), 3)
    assert.equal(await selHistory.getByText('操作人 reviewer-b', { exact: false }).count(), 1)
    assert.ok(!(await selDetailDialog.innerText()).includes('voter_id'))
    await click(page, '关闭')
    checks.push('选优结论双人审核留痕与阶段不自动流转')

    // 作废推优记录：记录保留可查，且已生效结论不受影响（不阻断、不回滚）
    await selChenRow.getByRole('button', { name: '作废推优', exact: true }).click()
    const selRevokeDialog = page
      .getByRole('dialog')
      .filter({ has: page.getByLabel('作废理由') })
    await selRevokeDialog.getByLabel('作废理由').fill('推荐单位填错，重新登记')
    await click(page, '作废该记录')
    await visible(page, '该条推优记录已作废')
    assert.equal(state.leagueRecommendations[0].revoked_on, today)
    await visible(page, '原有记录已作废')
    assert.equal(state.selections[0].review_status, 'approved')
    checks.push('作废推优记录保留留痕且不影响生效结论')

    // ---------------------------- 组织关系接转（T-MEM-14） ----------------------------
    await tab(page, '组织关系接转')
    await visible(page, '转出开了介绍信不等于转出完成')
    const outDialog = page.getByRole('dialog').filter({ has: page.getByLabel('接收组织名称（介绍信抬头）') })
    const settleDialog = page.getByRole('dialog').filter({ has: page.getByLabel('回执日期') })
    await click(page, '登记转出')
    // 培养对象不是组织关系接转的对象：候选里不能出现"陈见微"（入党积极分子）
    await outDialog.getByLabel('转出党员（预备党员 / 正式党员）').waitFor()
    assert.equal(await outDialog.locator('option', { hasText: '陈见微' }).count(), 0)
    await outDialog.getByLabel('转出党员（预备党员 / 正式党员）').selectOption(transferMember.id)
    await outDialog.getByLabel('接收组织名称（介绍信抬头）').fill('合成外校党委')
    await outDialog.getByLabel('介绍信编号').fill('转字2026-001')
    await outDialog.getByLabel('开具日期').fill(today)
    await outDialog.getByLabel('办理依据 / 说明').fill('本人申请转出，支委会研究同意')
    await click(page, '登记为待接收')
    await visible(page, '已登记转出')
    await visible(page, '转出待接收')
    assert.equal(state.transfers[0].status, 'pending')
    checks.push('登记转出：状态停在待接收，且不改发展阶段')

    await click(page, '留痕')
    await visible(page, '本人申请转出，支委会研究同意')
    await click(page, '登记回执（完成转出）')
    await settleDialog.getByLabel('回执编号（可留空）').fill('回执2026-088')
    await settleDialog.getByLabel('办理依据 / 说明').fill('收到接收组织回执')
    await click(page, '确认登记回执')
    await visible(page, '不再计入本组织在册名单')
    assert.equal(state.transfers[0].status, 'settled')
    await screenshot(page, 'members-transfers')
    await click(page, '留痕')
    await visible(page, '收到接收组织回执')
    checks.push('收到回执才算转出完成，回执后移出在册名单，留痕可查办理理由')

    await tab(page, '人员档案')
    assert.equal(await page.locator('.roster__item', { hasText: '林舟' }).count(), 0)
    await page.getByRole('checkbox', { name: '含组织关系已转出人员' }).check()
    await visible(page, '林舟')
    await visible(page, '已转出')
    checks.push('已转出人员默认不出现在名册，显式勾选后可查且带标识')

    await tab(page, '组织关系接转')
    await click(page, '登记转入')
    const inDialog = page.getByRole('dialog').filter({ has: page.getByLabel('接收组织（本组织侧）') })
    await inDialog.getByLabel('关联的档案（预备党员 / 正式党员）').selectOption(transferMember.id)
    await inDialog.getByLabel('原组织名称（介绍信来历）').fill('合成外校党委')
    await inDialog.getByLabel('介绍信编号').fill('转入字2026-021')
    await inDialog.getByLabel('开具日期').fill(today)
    await inDialog.getByLabel('办理依据 / 说明').fill('本人持介绍信来校报到，关系转回本校')
    await click(page, '登记转入并生成档案清单')
    await visible(page, '转入登记结果')
    await visible(page, '已关联现有档案')
    await visible(page, '转正申请书')
    await visible(page, '缺项不影响本次登记')
    assert.equal(state.transfers[1].direction, 'in')
    assert.equal(state.transfers[1].profile_id, transferMember.id)
    await click(page, '登记回执（档案已核对）')
    await settleDialog.getByLabel('办理依据 / 说明').fill('档案逐项核对完成')
    await click(page, '确认登记回执')
    await visible(page, '转入办结')
    assert.equal(state.transfers[1].status, 'settled')
    checks.push('转入按现有档案关联并列出档案缺项，回执后仍在册')

    await click(page, '登记转出')
    await outDialog.getByLabel('转出党员（预备党员 / 正式党员）').selectOption(transferMember.id)
    await outDialog.getByLabel('接收组织名称（介绍信抬头）').fill('合成第四个单位党委')
    await outDialog.getByLabel('介绍信编号').fill('转字2026-050')
    await outDialog.getByLabel('开具日期').fill(addDays(today, -200))
    await outDialog.getByLabel('办理依据 / 说明').fill('转往第四个单位')
    await click(page, '登记为待接收')
    await visible(page, '已登记转出')
    await page.getByRole('checkbox', { name: '只看已超过有效期' }).check()
    await visible(page, '需要人工核实')
    await visible(page, '不自动判定转出失败')
    checks.push('超过介绍信有效期只提示核实，不自动判定失败')

    await click(page, '作废')
    const revokeDialog = page.getByRole('dialog').filter({ has: page.getByLabel('作废理由') })
    await revokeDialog.getByLabel('作废理由').fill('介绍信抬头写错，重新开具')
    await click(page, '确认作废')
    await visible(page, '记录保留可查')
    assert.equal(state.transfers.at(-1).status, 'revoked')
    await visible(page, '当前筛选下没有接转记录')
    checks.push('接转可作废：视同未发生但记录保留')

    // ---------------------------- 上级审批 / 备案（T-MEM-11） ----------------------------
    await tab(page, '上级审批备案')
    await visible(page, '系统不代替上级党组织审批')
    await visible(page, '备案类时限按上级党委规定')
    const reportDialog = page.getByRole('dialog').filter({ has: page.getByLabel('上级组织名称（受理备案 / 审批的党委、工委）') })
    const settleUpDialog = page.getByRole('dialog').filter({ has: page.getByLabel('批复文号（同意 / 不同意必填）') })
    const revokeUpDialog = page.getByRole('dialog').filter({ has: page.getByLabel('作废理由') })
    await click(page, '登记报送')
    await reportDialog.getByLabel('报送事项').selectOption('probationary_approval')
    // 依据条文与随报材料清单由后端目录给出：界面不自己编条文
    await visible(page, '第二十一条')
    await visible(page, '中国共产党入党志愿书')
    // 阶段未到该环节的党员不能报送：候选里不能出现"陈见微"（入党积极分子）
    const candidateSelect = reportDialog.getByLabel('报送党员（阶段已到该事项环节）')
    await candidateSelect.locator('option', { hasText: '林舟' }).waitFor({ state: 'attached' })
    assert.equal(await candidateSelect.locator('option', { hasText: '陈见微' }).count(), 0)
    await candidateSelect.selectOption(transferMember.id)
    await reportDialog.getByLabel('上级组织名称（受理备案 / 审批的党委、工委）').fill('合成院系党委')
    await reportDialog.getByLabel('报送日期').fill(today)
    await reportDialog.getByLabel('办理依据 / 说明').fill('支部大会讨论通过，报上级党委审批')
    await click(page, '登记为已报送待批复')
    await visible(page, '已登记报送')
    await visible(page, '已报送待批复')
    assert.equal(state.upperReports[0].status, 'submitted')
    checks.push('登记报送只表示材料已报出，依据与随报材料清单由后端单源给出')

    // 没有批复文号的"同意"不是批复：界面直接不允许提交
    await click(page, '回填批复')
    await settleUpDialog.getByLabel('批复文号（同意 / 不同意必填）').fill('')
    assert.equal(
      await settleUpDialog.getByRole('button', { name: '回填「同意 / 批准」', exact: true }).isDisabled(),
      true,
    )
    await settleUpDialog.getByLabel('批复文号（同意 / 不同意必填）').fill('合成党组〔2026〕15号')
    await settleUpDialog.getByLabel('批复日期').fill(today)
    await settleUpDialog.getByLabel('办理依据 / 说明').fill('收到院系党委批复原件')
    await settleUpDialog.getByRole('button', { name: '回填「同意 / 批准」', exact: true }).click()
    await visible(page, '不会自动变化')
    assert.equal(state.upperReports[0].status, 'settled')
    assert.equal(state.upperReports[0].result, 'agreed')
    checks.push('回填批复必须填文号，且回填批复不改动党员阶段')

    // 审批类超过时限只提示向上级核实进度，不判定审批失效
    await click(page, '登记报送')
    await reportDialog.getByLabel('报送事项').selectOption('member_approval')
    await reportDialog.getByLabel('报送党员（阶段已到该事项环节）').selectOption(transferMember.id)
    await reportDialog.getByLabel('上级组织名称（受理备案 / 审批的党委、工委）').fill('合成院系党委')
    await reportDialog.getByLabel('报送日期').fill(addDays(today, -200))
    await reportDialog.getByLabel('办理依据 / 说明').fill('预备期满，报上级党委审批转正')
    await click(page, '登记为已报送待批复')
    await visible(page, '需向上级核实审批进度')
    await visible(page, '不判定审批失效')
    await page.getByRole('checkbox', { name: '只看已超过审批时限' }).check()
    await visible(page, `已超过审批时限 ${200 - upperApprovalDays} 天`)
    checks.push('审批类超期只提示向上级核实，不判定审批失效、也不改动阶段')

    await click(page, '作废')
    await revokeUpDialog.getByLabel('作废理由').fill('报送事项选错，重新登记')
    await click(page, '确认作废')
    await visible(page, '视同未发生')
    assert.equal(state.upperReports.at(-1).status, 'revoked')
    checks.push('报送记录可作废：视同未发生但记录保留可查')

    await page.getByRole('checkbox', { name: '只看已超过审批时限' }).uncheck()
    await visible(page, '已回填批复')

    // 备案类细则未统一规定时限：如实写"按上级党委规定"，不编期限、也不显示倒计时
    await click(page, '登记报送')
    await reportDialog.getByLabel('报送事项').selectOption('activist_record')
    // 阶段已到即可报送：入党积极分子本人也能报"确定入党积极分子"的备案
    await candidateSelect.locator('option', { hasText: '陈见微' }).waitFor({ state: 'attached' })
    await candidateSelect.selectOption(state.profile.id)
    await reportDialog.getByLabel('上级组织名称（受理备案 / 审批的党委、工委）').fill('合成院系党委')
    await reportDialog.getByLabel('报送日期').fill(today)
    await reportDialog.getByLabel('办理依据 / 说明').fill('支委会研究确定入党积极分子，报上级党委备案')
    await click(page, '登记为已报送待批复')
    await visible(page, '已登记报送')
    assert.equal(state.upperReports.at(-1).kind, 'record')
    assert.equal(state.upperReports.at(-1).status, 'submitted')
    const recordRow = page.locator('tr', { hasText: '确定入党积极分子（报上级党委备案）' })
    await recordRow.getByText('按上级党委规定', { exact: true }).waitFor()
    assert.equal(await recordRow.getByText('剩余', { exact: false }).count(), 0)
    checks.push('备案类可报送且不显示审批倒计时，时限按上级党委规定而不是编一个期限')

    // 临近审批时限要提前提示：不能等超期了才第一次提醒（配置的提前天数是真起作用的）
    await click(page, '登记报送')
    await reportDialog.getByLabel('报送事项').selectOption('member_approval')
    await candidateSelect.selectOption(transferMember.id)
    await reportDialog.getByLabel('上级组织名称（受理备案 / 审批的党委、工委）').fill('合成院系党委')
    await reportDialog.getByLabel('报送日期').fill(addDays(today, -80))
    await reportDialog.getByLabel('办理依据 / 说明').fill('预备期满，报上级党委审批转正')
    await click(page, '登记为已报送待批复')
    await visible(page, `剩余 ${upperApprovalDays - 80} 天，临近审批时限`)
    checks.push('临近审批时限提前提示，不等到超期才第一次提醒')

    await click(page, '导出台账')
    await visible(page, '不含材料原件与政治审查材料内容')
    assert.equal(state.exported, true)
    await screenshot(page, 'members-upper-reports')
    checks.push('导出台账只含报送要素与材料清单，不含材料原件与政审材料内容')

    await page.goto(`${BASE}/meeting`, { waitUntil: 'networkidle' })
    await click(page, '登记活动计划')
    const createDialog = page.getByRole('dialog').filter({ has: page.getByLabel('活动主题') })
    await createDialog.getByLabel('活动主题').fill('样例：志愿服务专题组织生活')
    await createDialog.getByLabel('计划日期').fill(future)
    await createDialog.getByLabel('主持人').fill('陈见微')
    await createDialog.getByLabel('登记理由').fill('支部活动安排')
    await createDialog.getByRole('button', { name: '从知识库选择' }).click()
    await click(page, '选择文件')
    await click(page, '完成选择')
    await click(page, '保存活动计划')
    await visible(page, '活动计划已登记')
    await page.getByLabel('实际召开日期', { exact: true }).fill(today)
    await click(page, '添加参会人员')
    await page.getByLabel('第1位参会人员编号').fill('20260017')
    await page.getByLabel('第1位参会人员姓名').fill('陈见微')
    await tab(page, '议程与纪要')
    const transcript =
      '会场记录：🙂\n学习要点：学习有关制度。\n讨论共识：按期完成材料核验。\n  工作要求：登记志愿服务记录。  '
    await page.getByLabel('会议原始文本', { exact: true }).fill(transcript)
    await page.getByLabel('本次修改理由').fill('依据签到和会议记录补齐实际情况')
    await click(page, '保存活动资料')
    await visible(page, '活动资料已保存')
    const activeRecord = state.records.at(-1)
    assert.equal(activeRecord.held_on, today)
    assert.equal(activeRecord.participants.length, 1)
    assert.equal(activeRecord.transcript, transcript)
    checks.push('未来计划与实际日期、参会和原文的完整保存')
    await recordAction(page, '生成议程与通知草稿')
    await visible(page, '生成议程与通知草稿已完成')
    await recordAction(page, '从原文提取纪要')
    await visible(page, '从原文提取纪要已完成')
    await tab(page, '活动任务')
    await click(page, '从原文登记任务')
    await click(page, '摘取工作要求原文')
    await page.getByRole('dialog').getByLabel('操作理由', { exact: true }).fill('原文摘取工作要求')
    await click(page, '保存任务记录')
    await visible(page, '任务记录已保存')
    await click(page, '确认责任与期限')
    await page.getByRole('dialog').getByLabel('责任人', { exact: true }).fill('陈见微')
    await page.getByRole('dialog').getByLabel('办理期限').fill(future)
    await page
      .getByRole('dialog')
      .getByLabel('操作理由', { exact: true })
      .fill('人工明确负责人及期限')
    await click(page, '保存任务记录')
    await click(page, '登记落实结果')
    await page.getByRole('dialog').getByLabel('落实说明与依据').fill('服务记录已登记并核对')
    await page.getByRole('dialog').getByLabel('操作理由', { exact: true }).fill('登记实际落实情况')
    await click(page, '保存任务记录')
    await visible(page, '已完成')
    assert.equal(activeRecord.tasks[0].status, 'done')
    checks.push('Unicode原文定位、任务确认与落实闭环')
    await recordAction(page, '提交纪要审核')
    await visible(page, '提交当前纪要审核已完成')
    assert.equal(
      await page.getByRole('button', { name: '人工审核纪要', exact: true }).isDisabled(),
      true,
    )
    checks.push('纪要提交与禁止自审')
    await screenshot(page, 'meeting-desktop')
    const reviewer = await context(1440, false, 'reviewer-b')
    await reviewer.page.goto(`${BASE}/meeting`, { waitUntil: 'networkidle' })
    await reviewer.page.getByRole('button', { name: '打开活动', exact: true }).last().click()
    await recordAction(reviewer.page, '人工审核纪要')
    await visible(reviewer.page, '登记人工纪要审核已完成')
    await recordAction(reviewer.page, '归档已审核纪要')
    await visible(reviewer.page, '学校尚未确认电子归档效力')
    state.allowArchive = true
    await reviewer.page.getByRole('dialog').getByRole('button', { name: /^确认/ }).click()
    await visible(reviewer.page, '归档当前纪要已完成')
    const archiveFile = reviewer.page.waitForEvent('download')
    await click(reviewer.page, '导出归档记录')
    assert.ok((await archiveFile).suggestedFilename().endsWith('-归档.json'))
    checks.push('他人审核、电子效力门禁、归档和导出')
    await tab(reviewer.page, '年度统计')
    await visible(reviewer.page, '50.0%')
    checks.push('比例单位与缺少统计依据状态')
    // 组织生活频次：周期要求、已召开未审核的提醒、已结束周期的缺口分区展示
    await visible(reviewer.page, '每季度至少 1 次')
    await visible(reviewer.page, '组织生活频次合规')
    await visible(reviewer.page, '本周期需处理（1）')
    await visible(reviewer.page, '纪要尚未通过人工审核')
    await visible(reviewer.page, '已召开待审核')
    // 缺口列按真实待审次数显示（mock 里 2 次待审），不是笼统的"差 1 次"
    await visible(reviewer.page, '待审核 2 次')
    await reviewer.page.locator('.meeting-frequency summary', { hasText: '已结束周期缺口（1）' }).click()
    await visible(reviewer.page, '跨周期不抵扣')
    assert.equal(await reviewer.page.locator('.meeting-frequency__gaps li').count(), 1)
    checks.push('三会一课周期频次、提醒与缺口分区')

    // 民主评议党员：年度工作区、等次分布与低等次提示、录入→发起→送审→他人审核→修订
    await tab(reviewer.page, '民主评议党员')
    await visible(reviewer.page, `${year} 年度民主评议党员`)
    await visible(reviewer.page, '应评议党员')
    await visible(reviewer.page, '未发起 2')
    await visible(reviewer.page, '优秀 1 人，占应评议 20%')
    // 缺项（阻断送审）与提示（不阻断）在界面上必须分开显示
    await visible(reviewer.page, '个人自评待录')
    await visible(reviewer.page, '未登记民主测评票数')
    assert.equal(await reviewer.page.locator('.review__grade').count(), 4)
    await visible(reviewer.page, '需按党章党规研究处置（1）')
    await visible(reviewer.page, '限期改正理论学习不系统的问题。')
    checks.push('民主评议工作区、等次分布与低等次提示')

    // 名册里还没有记录的党员：直接录入评议（新建），再走发起补齐其余草稿
    await reviewer.page
      .getByRole('row').filter({ hasText: '周慕白' })
      .getByRole('button', { name: '录入评议', exact: true })
      .click()
    const reviewCreateDialog = reviewer.page
      .getByRole('dialog')
      .filter({ has: reviewer.page.getByLabel('个人自评') })
    await visible(reviewer.page, '录入周慕白 的民主评议')
    await reviewCreateDialog.getByLabel('个人自评').fill('本人对照党员标准自评：能按时参加组织生活。')
    await reviewCreateDialog.getByLabel('操作理由').fill('补录民主评议草稿')
    await reviewCreateDialog.getByRole('button', { name: '保存草稿', exact: true }).click()
    await visible(reviewer.page, '周慕白 的评议草稿已保存。')
    checks.push('未发起党员的评议录入与草稿保存')

    await click(reviewer.page, '按年度发起')
    const launchDialog = reviewer.page
      .getByRole('dialog')
      .filter({ has: reviewer.page.getByLabel('发起理由') })
    await launchDialog.getByLabel('发起理由').fill('按年度发起民主评议')
    await launchDialog.getByRole('button', { name: '确认发起', exact: true }).click()
    await visible(reviewer.page, '已发起：新建 1 条草稿，跳过 4 条已有记录（共 5 名在册党员）')
    checks.push('按年度发起只补未录入的党员，不覆盖已有记录')

    // 只有提交人不是本人、且记录处于待审核时才出现"审核"入口
    assert.equal(await reviewer.page.getByRole('button', { name: '审核', exact: true }).count(), 1)
    await reviewer.page
      .getByRole('row').filter({ hasText: '王砚清' })
      .getByRole('button', { name: '录入/修订', exact: true })
      .click()
    const recordDialog = reviewer.page
      .getByRole('dialog')
      .filter({ has: reviewer.page.getByLabel('支部评定意见') })
    await visible(reviewer.page, '送审前还需补齐')
    await recordDialog.getByLabel('个人自评').fill('本人对照党员标准自评：能按时参加组织生活。')
    await recordDialog.getByLabel('支部评定意见').fill('支委会同意评定为合格。')
    await recordDialog.getByLabel('评定等次').selectOption('qualified')
    await recordDialog.getByLabel('评定依据').fill('民主测评情况与日常表现')
    await recordDialog.getByLabel('操作理由').fill('录入民主评议结果')
    await recordDialog.getByRole('button', { name: '保存并送审', exact: true }).click()
    await visible(reviewer.page, '王砚清 的评议已送审，需由另一位有权限的人员审核后生效')
    assert.equal(await reviewer.page.getByRole('button', { name: '审核', exact: true }).count(), 1)
    checks.push('评议录入、送审与提交人不能自审')

    await reviewer.page
      .getByRole('row').filter({ hasText: '赵向知' })
      .getByRole('button', { name: '审核', exact: true })
      .click()
    const decisionDialog = reviewer.page
      .getByRole('dialog')
      .filter({ has: reviewer.page.getByLabel('审核结论') })
    await decisionDialog.getByLabel('审核意见与依据').fill('材料齐全，同意评定为合格。')
    await decisionDialog.getByRole('button', { name: '确认审核', exact: true }).click()
    await visible(reviewer.page, '已通过人工审核并生效')
    checks.push('评议人工审核与生效提示')

    // 已生效的评议再修订会回到草稿并要求重新送审
    await reviewer.page
      .getByRole('row').filter({ hasText: '陈见微' })
      .getByRole('button', { name: '录入/修订', exact: true })
      .click()
    const reviseDialog = reviewer.page
      .getByRole('dialog')
      .filter({ has: reviewer.page.getByLabel('对本人提出的整改要求') })
    await visible(reviewer.page, '该评议已通过审核并生效')
    await reviseDialog.getByLabel('对本人提出的整改要求').fill('继续加强理论学习。')
    await reviseDialog.getByLabel('操作理由').fill('补充整改要求')
    await reviseDialog.getByRole('button', { name: '保存草稿', exact: true }).click()
    await visible(reviewer.page, '陈见微 的评议草稿已保存。')
    checks.push('已生效评议的修订回到草稿')
    await reviewer.ctx.close()

    const read = await context(1440, true)
    await read.page.goto(`${BASE}/members`, { waitUntil: 'networkidle' })
    await visible(read.page, '陈见微的办理档案')
    assert.equal(
      await read.page.getByRole('button', { name: '登记人工审核', exact: true }).count(),
      0,
    )
    await tab(read.page, '人工流转')
    assert.equal(
      await read.page.getByRole('button', { name: '登记人工决定', exact: true }).count(),
      0,
    )
    await read.page.goto(`${BASE}/meeting`, { waitUntil: 'networkidle' })
    assert.equal(
      await read.page.getByRole('button', { name: '登记活动计划', exact: true }).count(),
      0,
    )
    // 只看得到的账号：民主评议结果可以查看，但不出现发起、录入或审核入口
    await tab(read.page, '民主评议党员')
    await visible(read.page, `${year} 年度民主评议党员`)
    assert.equal(
      await read.page.getByRole('button', { name: '按年度发起', exact: true }).count(),
      0,
    )
    assert.equal(
      await read.page.getByRole('button', { name: '录入/修订', exact: true }).count(),
      0,
    )
    assert.equal(await read.page.getByRole('button', { name: '审核', exact: true }).count(), 0)
    await read.page
      .getByRole('row').filter({ hasText: '赵向知' })
      .getByRole('button', { name: '查看', exact: true })
      .click()
    assert.equal(
      await read.page.getByRole('button', { name: '保存并送审', exact: true }).count(),
      0,
    )
    await read.ctx.close()
    checks.push('查询账号不展示写入与审核入口')
    const restricted = await context(1440, false, 'viewer-a', { ...state, restricted: true })
    await restricted.page.goto(`${BASE}/meeting`, { waitUntil: 'networkidle' })
    await restricted.page.getByRole('button', { name: '打开活动', exact: true }).last().click()
    await visible(restricted.page, '正文、参会明细和衍生内容暂不可访问')
    assert.equal(await restricted.page.getByLabel('会议原始文本', { exact: true }).count(), 0)
    await tab(restricted.page, '任务台账')
    await visible(restricted.page, '此任务的正文暂不可查看')
    await restricted.ctx.close()
    checks.push('受限活动与受限任务的空正文展示')
    const empty = await context(1440, false, 'viewer-a', { ...state, empty: true })
    await empty.page.goto(`${BASE}/knowledge`, { waitUntil: 'networkidle' })
    // 范围本身没有文件：空状态必须说明"授权范围内暂无可读文件"，而不是白屏或含糊的"没有匹配"
    await visible(empty.page, '授权范围内暂无可读文件')
    // 有筛选条件时才是"没有匹配的文件"，并给出清除筛选的出路
    await empty.page
      .getByPlaceholder('按标题、发文机关、文号或标签搜索')
      .fill('不存在的关键词')
    await visible(empty.page, '没有匹配的文件')
    await visible(empty.page, '清除筛选')
    await empty.ctx.close()
    checks.push('空数据状态')
    const unavailable = await context(1440, false, 'viewer-a', { ...state, failList: true })
    await unavailable.page.goto(`${BASE}/knowledge`, { waitUntil: 'networkidle' })
    await visible(unavailable.page, '资料服务暂不可用')
    await visible(unavailable.page, 'ui-fixture-error')
    await unavailable.ctx.close()
    checks.push('服务失败时保留错误原因与请求标识')
    for (const route of ['knowledge', 'members', 'meeting']) {
      const mobile = await context(390)
      await mobile.page.goto(`${BASE}/${route}`, { waitUntil: 'networkidle' })
      if (route === 'knowledge') {
        await mobile.page.locator('tbody tr').first().click()
        const scrolling = await mobile.page.locator('.table-wrap').evaluate((element) => {
          element.scrollLeft = 180
          return { overflow: getComputedStyle(element).overflowX, offset: element.scrollLeft }
        })
        assert.equal(scrolling.overflow, 'auto', '手机文件表格必须支持用户滚动')
        assert.ok(scrolling.offset > 0, '手机文件表格必须能查看屏幕外的列')
      }
      if (route === 'members') await visible(mobile.page, '陈见微的办理档案')
      if (route === 'meeting')
        await mobile.page.getByRole('button', { name: '打开活动', exact: true }).last().click()
      await screenshot(mobile.page, `${route}-mobile`)
      await mobile.ctx.close()
    }
    checks.push('三个页面390px布局没有页面横向溢出')
    assert.deepEqual(errors, [], '不得有浏览器未捕获异常')
    await writeFile(resolve(OUT, 'contract-requests.json'), JSON.stringify(requests, null, 2))
    await writeFile(
      resolve(OUT, 'verification.json'),
      JSON.stringify({ checks, uncaughtErrors: errors, fixtureOnly: true }, null, 2),
    )
    console.log(
      `${checks.length}组界面检查通过，无浏览器未捕获异常。\n${checks.map((item) => `- ${item}`).join('\n')}`,
    )
    await ctx.close()
  }
} finally {
  await browser.close()
}
