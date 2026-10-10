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
      review_history: [],
    },
  ],
  cultivation: [],
  stage_history: [],
  boundary: '阶段流转仅由人工操作完成，辅助结果不构成组织认定。',
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
    records: [structuredClone(meeting)],
    revisions: [],
    allowArchive: false,
    restricted: false,
    empty: false,
    failList: false,
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
      const match =
        (!url.searchParams.has('year') ||
          Number(url.searchParams.get('year')) === data.profile.year) &&
        (!url.searchParams.has('batch_no') ||
          url.searchParams.get('batch_no') === data.profile.batch_no)
      return route.fulfill(
        ok(
          pagination(
            data.empty || !match
              ? []
              : [
                  {
                    ...data.profile,
                    materials: data.profile.materials.map((item) => item.material_type),
                    stage: data.profile.current_stage,
                    days_in_stage: 500,
                  },
                ],
            url.searchParams,
          ),
        ),
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
        tally[row.profile_id] ??= { agree: 0, disagree: 0, abstain: 0, voters: [] }
        tally[row.profile_id][row.vote] += 1
        tally[row.profile_id].voters.push(row.voter_id)
      }
      return route.fulfill(
        ok({
          batch_no: url.searchParams.get('batch_no'),
          round_no: Number(url.searchParams.get('round_no')),
          voter_count: new Set(rows.map((item) => item.voter_id)).size,
          tally,
          note: '汇总仅为过程记录，组织结论由人工形成。',
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
            },
          },
          attendance_rate: { value: 0.5, numerator: 1, denominator: 2, status: 'known' },
          minutes_completeness: { value: null, numerator: 0, denominator: 0, status: 'pending' },
          evidence: [],
          missing: [],
          calculation_rule: '仅统计已审核记录；统计结果须人工确认。',
        }),
      )
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
    await visible(empty.page, '没有匹配的文件')
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
