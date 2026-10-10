/** Real Vue interactions with synthetic responses; backend/DB tests are separate. */
import assert from 'node:assert/strict'
import { mkdir, readFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'
import { createServer } from 'vite'

const root = fileURLToPath(new URL('../', import.meta.url))
const output = resolve(root, '../tmp/module4-ui')
const server = await createServer({ root, configLoader: 'native', server: { host: '127.0.0.1', port: 0 } })
let browser, page
try {
  await server.listen()
  await mkdir(output, { recursive: true })
  const address = server.httpServer.address()
  browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE })
  page = await browser.newPage({ viewport: { width: 1366, height: 900 } })
  page.setDefaultTimeout(10000)
  const pageErrors = [], unexpected = [], requests = []
  page.on('pageerror', (error) => pageErrors.push(error.message))
  await page.addInitScript(() => localStorage.setItem('party.access_token', 'synthetic-study-token'))
  let currentActor = 'author', plan = null, record = null, failRecommendation = false, activityCreates = 0
  let policy = { enabled: false, revision: 0 }
  const source = { doc_id: 'UI-STUDY-1', title: '合成学习重点制度', issuer: '合成单位', file_name: 'synthetic.txt', effective_date: '2020-01-01', expiration_date: null, visibility: 'school', level: 'school', status: 'effective', content_revision: 1, summary: '浏览器合成材料', excerpt: '第一条 合成学习重点真实引用。', chunk_id: 'UI-STUDY-1-1', article: '第一条' }
  const baseReview = () => ({ review_status: 'draft', submitted_by: null, reviewed_by: null, reviewed_at: null, review_comment: '', sources: [source], source_doc_ids: [source.doc_id], missing: [], restricted: false, notice: '供党委研究确定' })
  function reviewAction(entity, path, body) {
    entity.revision += 1
    if (path.endsWith('/submit')) { entity.review_status = 'pending'; entity.submitted_by = currentActor }
    else { entity.review_status = body.decision; entity.reviewed_by = currentActor; entity.reviewed_at = '2026-10-10T06:00:00'; entity.review_comment = body.reason }
  }
  const identity = () => ({ id: currentActor, username: currentActor, name: '合成组织人员', role: currentActor === 'member' ? 'member' : currentActor === 'school-confirm' ? 'school_admin' : 'department_admin', tenant_id: 'ui-tenant', org_unit_id: currentActor === 'school-confirm' ? 'school' : 'department' })
  await page.route(`http://127.0.0.1:${address.port}/api/**`, async (route) => {
    const request = route.request(), url = new URL(request.url())
    const path = url.pathname.replace(/^\/api(?:\/v1)?/, '')
    const method = request.method(), body = request.postDataJSON()
    requests.push({ path, method, body })
    let data
    if (path === '/auth/me') data = identity()
    else if (path === '/auth/codes') data = currentActor === 'member' ? ['qa.ask', 'knowledge.query'] : ['qa.ask', 'knowledge.query', 'knowledge.manage', 'study.query', 'study.manage', 'study.review', 'meeting.archive', ...(currentActor === 'school-confirm' ? ['admin.archive_confirm'] : [])]
    else if (path.startsWith('/health')) data = { status: 'ok', version: '1.0.0', dependencies: {}, components: {} }
    else if (path === '/study/org-units') data = { items: [{ id: 'department', name: '合成院系党委', org_type: 'department' }] }
    else if (path === '/admin/electronic-archive') {
      if (method === 'PATCH') policy = { ...body, revision: policy.revision + 1, confirmed_by: currentActor, confirmed_at: '2026-10-10T06:00:00' }
      data = policy
    }
    else if (path === '/study/plans' && method === 'GET') data = { items: plan && plan.year === Number(url.searchParams.get('year')) ? [plan] : [], total: plan ? 1 : 0, page: 1, page_size: 20 }
    else if (path === '/study/plans' && method === 'POST') {
      plan = { ...baseReview(), ...body, id: 'plan-1', revision: 1, items: [{ id: 'item-1', plan_id: 'plan-1', topic: body.priorities[0], scheduled_on: `${body.year}-04-01`, responsible: body.responsible, source_doc_ids: body.source_doc_ids, sources: [source], agenda: '', outline: '', template_version: null, meeting_record_id: null, execution_status: 'planned', missing: [] }] }
      data = plan
    }
    else if (path.endsWith('/recommendations')) {
      if (failRecommendation) { failRecommendation = false; await route.fulfill({ status: 503, json: { code: 50301, message: '合成资料服务暂不可用', trace_id: 'study-ui-retry', data: null } }); return }
      data = { sources: [source], missing: [] }
    }
    else if (path.endsWith('/generate-drafts')) {
      plan.revision += 1
      Object.assign(plan.items[0], { agenda: '一、学习真实材料[1]。\n供党委研究确定', outline: source.excerpt + '\n供党委研究确定', template_version: 'study-1' })
      data = plan
    }
    else if (path === '/study/plans/plan-1/items/item-1' && method === 'PATCH') {
      assert.equal(body.expected_revision, plan.revision)
      Object.assign(plan.items[0], body)
      plan.revision += 1
      plan.review_status = 'draft'
      data = plan
    }
    else if (path === '/study/plans/plan-1' && method === 'PATCH') { Object.assign(plan, body); plan.revision += 1; plan.review_status = 'draft'; data = plan }
    else if (/\/study\/plans\/plan-1\/(?:submit|review)$/.test(path)) { reviewAction(plan, path, body); data = plan }
    else if (path.endsWith('/items/item-1/activity') && method === 'POST') {
      activityCreates += 1
      record = { ...baseReview(), id: 'activity-1', org_unit_id: 'department', title: plan.items[0].topic, scheduled_on: plan.items[0].scheduled_on, held_on: null, host: '', revision: 1, participants: [], transcript: '', minutes: {}, context: { plan_id: plan.id, item_id: 'item-1', plan_revision: plan.revision, agenda: plan.items[0].agenda, outline: plan.items[0].outline }, archived_at: null, archive_policy_version: null, execution_status: 'draft' }
      plan.items[0].meeting_record_id = record.id
      data = record
    }
    else if (path === '/study/activities/activity-1' && method === 'PATCH') {
      assert.equal(body.expected_revision, record.revision)
      Object.assign(record, body)
      record.revision += 1
      record.review_status = 'draft'
      data = record
    }
    else if (path.endsWith('/generate-minutes')) {
      record.minutes = {}
      for (const [key, label] of [['learning_points', '学习要点'], ['consensus', '讨论共识'], ['requirements', '工作要求']]) {
        const match = record.transcript.match(new RegExp(label + '：([^\n]+)'))
        const start = record.transcript.indexOf(match[1])
        record.minutes[key] = [{ text: match[1], quote: match[1], start, end: start + match[1].length }]
      }
      record.revision += 1
      data = record
    }
    else if (/\/study\/activities\/activity-1\/(?:submit|review)$/.test(path)) { reviewAction(record, path, body); data = record }
    else if (path.endsWith('/activity-1/archive')) { assert.ok(policy.enabled); record.archived_at = '2026-10-10T06:00:00'; record.archive_policy_version = policy.revision; record.revision += 1; record.execution_status = 'archived'; data = record }
    else if (path.endsWith('/activity-1/export')) data = { notice: '供党委研究确定', record, plan_version: plan, archive_confirmation: policy, revisions: [{ revision: record.revision, action: 'archive', actor_id: currentActor, created_at: record.archived_at, reason: '合成归档审核' }], exported_at: '2026-10-10T06:00:00' }
    else if (path === '/study/activities/activity-1') data = record
    else if (path === '/study/history') data = { items: record?.archived_at ? [record] : [], total: record?.archived_at ? 1 : 0, page: 1, page_size: 20 }
    else if (path === '/study/metrics') data = { year: plan.year, learning_count: { value: 1, status: 'known' }, plan_completion_rate: { value: 1, numerator: 1, denominator: 1 }, attendance_rate: { value: 0.5, numerator: 1, denominator: 2 }, minutes_completeness: { value: 1, numerator: 1, denominator: 1 }, evidence: [{ activity_id: record.id, revision: record.revision, held_on: record.held_on, reviewed_by: record.reviewed_by, participants: record.participants.map((person) => ({ ...person, source_id: `${record.id}:${person.participant_id}` })), sources: [source] }], plan_evidence: [], missing: [], calculation_rule: '按实际学习年度复用原活动，重复查询不新增记录' }
    else if (path.endsWith('/revisions')) data = { items: [{ revision: plan.revision, action: 'revise', actor_id: currentActor, created_at: '2026-10-10T06:00:00', reason: '保留合成历史依据', snapshot: plan, restricted: false }] }
    else { unexpected.push(path); await route.fulfill({ status: 404, json: { code: 40401, message: 'Unexpected test API' } }); return }
    await route.fulfill({ json: { code: 0, message: '成功', data, trace_id: 'synthetic-study-ui' } })
  })
  const base = `http://127.0.0.1:${address.port}`
  const reason = () => page.getByLabel('操作依据 / 修订理由 / 审核意见', { exact: true })
  async function reopenPlan(actor) {
    currentActor = actor
    await page.goto(base + '/study')
    await page.locator('.plan-row').click()
    await reason().fill('合成回归：已核对原文和依据')
  }
  await page.goto(base + '/study')
  await page.getByRole('button', { name: '新建年度计划', exact: true }).click()
  await reason().fill('合成回归年度重点依据')
  await page.getByLabel('所属党委', { exact: true }).selectOption('department')
  await page.getByLabel('新计划年度', { exact: true }).fill('2026')
  await page.getByLabel('计划名称', { exact: true }).fill('2026年合成学习计划')
  await page.getByLabel('计划负责人', { exact: true }).fill('合成负责人')
  await page.getByLabel('年度重点（每行一项）', { exact: true }).fill('年度学习重点')
  await page.getByLabel('年度依据文件编号（每行一项，可在材料推荐后补齐）', { exact: true }).fill(source.doc_id)
  await page.getByRole('button', { name: '保存年度草案', exact: true }).click()
  await page.getByRole('heading', { name: '主题材料、议程与发言提纲', exact: true }).waitFor()
  await page.getByRole('button', { name: '推荐学习材料', exact: true }).click()
  await page.getByRole('button', { name: '从已保存材料生成议程提纲', exact: true }).click()
  await page.getByLabel('发言提纲（人工可编辑）', { exact: true }).fill(source.excerpt + '\n人工补充工作实际。\n供党委研究确定')
  await page.getByRole('button', { name: '保存本期安排与提纲', exact: true }).click()
  await page.getByText('每期安排与议程提纲已保存，请重新送审年度计划。', { exact: true }).waitFor()
  await page.evaluate(() => window.scrollTo(0, 0))
  await page.screenshot({ path: resolve(output, '01-study-plan.png'), fullPage: true })
  await page.getByRole('button', { name: '提交计划审核', exact: true }).click()
  await page.getByRole('button', { name: '通过计划审核', exact: true }).waitFor()
  assert.ok(await page.getByRole('button', { name: '通过计划审核', exact: true }).isDisabled())
  await reopenPlan('reviewer')
  await page.getByRole('button', { name: '通过计划审核', exact: true }).click()
  await page.getByRole('button', { name: '登记学习活动', exact: true }).click()
  const activityPanel = page.locator('[aria-label="学习活动与纪要"]')
  await activityPanel.waitFor()
  await page.getByLabel('实际学习日期', { exact: true }).fill('2026-04-01')
  await page.getByLabel('学习主持人', { exact: true }).fill('合成主持人')
  for (const [index, name] of ['合成人员甲', '合成人员乙'].entries()) {
    await page.getByRole('button', { name: '增加参学人员', exact: true }).click()
    await page.getByLabel(`参学人员 ${index + 1}`, { exact: true }).fill(name)
  }
  await activityPanel.getByLabel('实际参学').nth(1).uncheck()
  const transcript = '学习要点：研读合成制度第一条。\n讨论共识：共同核对真实依据。\n工作要求：按讨论要求落实。'
  await page.getByLabel('原始学习文本', { exact: true }).fill(transcript)
  await page.getByRole('button', { name: '保存学习记录与纪要', exact: true }).click()
  await page.getByRole('button', { name: '从已保存原文生成纪要', exact: true }).click()
  await page.getByLabel('学习要点表述', { exact: true }).waitFor()
  await activityPanel.getByRole('button', { name: /定位原文/ }).first().click()
  const selectedExcerpt = await page.getByLabel('原始学习文本', { exact: true }).evaluate((element) => element.value.slice(element.selectionStart, element.selectionEnd))
  assert.equal(selectedExcerpt, record.minutes.learning_points[0].quote)
  await page.evaluate(() => window.scrollTo(0, 0))
  await page.screenshot({ path: resolve(output, '02-study-minutes.png'), fullPage: true })
  await page.getByRole('button', { name: '提交纪要审核', exact: true }).click()
  await page.getByRole('button', { name: '通过纪要审核', exact: true }).waitFor()
  assert.ok(await page.getByRole('button', { name: '通过纪要审核', exact: true }).isDisabled())
  await reopenPlan('author')
  await page.getByRole('button', { name: '查看学习活动与纪要', exact: true }).click()
  await page.getByRole('button', { name: '通过纪要审核', exact: true }).click()
  await page.getByRole('button', { name: '归档已审核记录', exact: true }).waitFor()
  assert.ok(await page.getByRole('button', { name: '归档已审核记录', exact: true }).isDisabled())
  await reopenPlan('school-confirm')
  await page.getByText('电子归档确认与状态', { exact: true }).click()
  await page.getByLabel('学校组织部门已确认电子记录效力', { exact: true }).check()
  await page.getByLabel('学校效力确认依据 / 撤销理由', { exact: true }).fill('合成浏览器回归确认，非真实学校批准')
  await page.getByRole('button', { name: '保存学校归档确认', exact: true }).click()
  await page.getByRole('button', { name: '查看学习活动与纪要', exact: true }).click()
  await page.getByRole('button', { name: '归档已审核记录', exact: true }).click()
  const downloadReady = page.waitForEvent('download')
  await page.getByRole('button', { name: '导出学习材料', exact: true }).click()
  const download = await downloadReady
  const exportedText = await readFile(await download.path(), 'utf8')
  assert.ok(exportedText.includes(transcript) && exportedText.includes(source.doc_id) && exportedText.includes('审核人：author'))
  await page.getByRole('button', { name: '历史归档', exact: true }).click()
  await page.getByRole('button', { name: '查看归档详情', exact: true }).waitFor()
  await page.getByRole('button', { name: '考核复用', exact: true }).click()
  await page.getByText('50%', { exact: true }).waitFor()
  assert.equal(activityCreates, 1)
  assert.equal(requests.find((request) => request.path === '/study/activities/activity-1' && request.method === 'PATCH').body.participants.length, 2)
  console.log('PASS: annual plan, materials, editable drafts, separate reviewers, original-text minutes, archive gate, download, history, and evidence metrics')
  await page.getByRole('button', { name: '年度计划与每期学习', exact: true }).click()
  await page.locator('.plan-row').click()
  failRecommendation = true
  await page.getByRole('button', { name: '推荐学习材料', exact: true }).click()
  await page.getByText('study-ui-retry', { exact: true }).waitFor()
  await page.getByRole('button', { name: '推荐学习材料', exact: true }).click()
  await page.getByText(source.title, { exact: true }).first().waitFor()
  await page.setViewportSize({ width: 390, height: 844 })
  await page.waitForFunction(() => document.querySelector('#app-rail').getBoundingClientRect().right <= 1)
  await page.evaluate(() => window.scrollTo(0, 0))
  await page.screenshot({ path: resolve(output, '03-study-mobile.png'), fullPage: true })
  await page.screenshot({ path: resolve(output, '04-study-mobile-viewport.png') })
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1))
  console.log('PASS: request failure keeps work intact, retry succeeds, and mobile layout stays within the viewport')
  currentActor = 'member'
  await page.goto(base + '/study')
  await page.waitForURL('**/system**')
  assert.equal(await page.getByRole('link', { name: '中心组学习', exact: true }).count(), 0)
  assert.deepEqual(pageErrors, [])
  assert.deepEqual(unexpected, [])
  console.log('PASS: ordinary members cannot open the workbench; no browser exceptions or unexpected API requests')
} catch (error) {
  if (page) {
    await page.screenshot({ path: resolve(output, '00-failure.png'), fullPage: true })
    console.error('Browser state:', (await page.locator('body').innerText()).slice(0, 2200))
  }
  throw error
} finally {
  await browser?.close()
  await server.close()
}
