/** Real Vue browser contract checks with explicitly synthetic HTTP responses. */
import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'
import { chromium } from 'playwright'

const root = fileURLToPath(new URL('../', import.meta.url))
const year = new Date().getFullYear()
const server = await createServer({ root, configLoader: 'native', server: { host: '127.0.0.1', port: 0 } })
let browser
try {
  await server.listen()
  const address = server.httpServer.address()
  browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE })
  const page = await browser.newPage()
  page.setDefaultTimeout(15000)
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.addInitScript(() => localStorage.setItem('party.access_token', 'synthetic-assessment-ui-token'))
  const user = { id: 'ui-school-user', username: 'synthetic', name: '合成校级用户', role: 'school_admin', tenant_id: 'ui-tenant', org_unit_id: 'ui-school' }
  const permissions = ['qa.ask', 'assessment.query', 'assessment.manage', 'assessment.configure', 'assessment.review', 'assessment.export']
  const state = { org_unit_id: 'ui-school', org_name: '合成学校', school_org_id: 'ui-school', year, as_of: `${year}-10-10`, fingerprint: 'ui-fingerprint', engine_version: 'assessment-1',
    indicators: [], results: [], tasks: [], evidence: [], owners: [{ id: user.id, name: user.name }], runs: [], plan: null,
    policy: { version: 0, archive_version: 0, archive_enabled: false, reminder_advance_days: 14, confirmation_note: '' }, reminders: [], needs_recalculation: true, notices: ['仅合成浏览器输入'] }
  const reference = { source: 'organizations', record_id: 'ui-school', version: 'ui-source-v1', org_unit_id: 'ui-school', occurred_on: `${year}-01-01`, facts: { org_type: 'school', period_basis: '当前组织快照' } }
  const requests = []
  let rejectTask = true
  function invalidated() { state.needs_recalculation = true; state.fingerprint += '-changed' }
  await page.route(`http://127.0.0.1:${address.port}/api/**`, async route => {
    const request = route.request()
    const path = new URL(request.url()).pathname.replace(/^\/api(?:\/v1)?/, '')
    const body = request.postData() ? request.postDataJSON() : null
    requests.push({ path, method: request.method(), body })
    let data
    if (path === '/auth/me') data = user
    else if (path === '/auth/codes') data = permissions
    else if (path === '/assessment/org-units') data = [{ id: 'ui-school', name: '合成学校', org_type: 'school' }]
    else if (path === '/assessment/workspace') data = state
    else if (path === '/assessment/indicators') {
      const version = state.indicators.length + 1
      data = { ...body, id: `ui-rule-${version}`, version, active: true, effective_from: `${year}-01-01T00:00:00`, created_by: user.id }
      state.indicators.forEach(rule => { rule.active = false })
      state.indicators.push(data)
      state.results = [{ code: body.code, name: body.name, rule_id: data.id, rule_version: version, requirement: body.requirement, source: body.source, formula: body.formula,
        actual: 1, target: body.target, satisfied: null, unit: body.unit, period_start: body.period_start, period_end: body.period_end, sources: [reference], evidence: [], missing: ['学校指标口径待确认'] }]
      invalidated()
    } else if (path === '/assessment/recalculate') {
      state.needs_recalculation = false
      data = { id: `ui-run-${state.runs.length + 1}`, fingerprint: state.fingerprint, engine_version: 'assessment-1', created_at: `${year}-10-10T00:00:00`, created_by: user.id, review_status: 'pending', revision: 1, review_opinion: '' }
      state.runs.unshift(data)
    } else if (path === '/assessment/tasks' && rejectTask) {
      rejectTask = false
      await route.fulfill({ status: 409, json: { code: 40901, message: '合成并发冲突，请保留输入后重试', data: null, trace_id: 'synthetic-conflict' } })
      return
    } else if (path === '/assessment/tasks') {
      data = { ...body, id: 'ui-task', revision: 1, progress: 0, complete: false, overdue: false, due_soon: true, missing: ['学校指标口径待确认'], review_status: 'pending', created_by: user.id, review_opinion: '' }
      state.tasks.push(data)
      invalidated()
    } else if (path === '/assessment/plans') {
      data = { id: 'ui-plan', run_id: body.run_id, content: body.content ?? `${year}年度合成学校党建工作计划（参考草案）\n工作任务和时间安排待补，提交人工研究。`, year,
        version: (state.plan?.version ?? 0) + 1, revision: 1, review_status: 'pending', created_by: user.id, review_opinion: '', stale: false }
      state.plan = data
    } else if (path === '/assessment/policy') {
      state.policy = { version: body.expected_version + 1, archive_version: body.expected_archive_version + 1, archive_enabled: body.archive_enabled, reminder_advance_days: body.reminder_advance_days, confirmation_note: body.confirmation_note }
      data = state.policy
    } else if (path === '/assessment/reminders/sync') data = { count: 0 }
    else if (/^\/assessment\/runs\/ui-run-\d+$/.test(path)) data = { ...state.runs.find(run => path.endsWith(run.id)), results: state.results, stale: true, notice: '合成历史快照；当前授权已重新核查。' }
    else if (path === '/assessment/sources/organizations/ui-school') data = reference
    else if (path.endsWith('/export')) {
      await route.fulfill({ contentType: 'application/zip', body: 'synthetic-browser-download-contract' })
      return
    } else throw new Error(`Unexpected request: ${request.method()} ${path}`)
    await route.fulfill({ json: { code: 0, message: '成功', data, trace_id: 'synthetic-assessment-ui' } })
  })
  await page.goto(`http://127.0.0.1:${address.port}/assessment`)
  await page.getByRole('button', { name: '新增指标', exact: true }).click()
  await page.getByLabel('指标编码', { exact: true }).fill('ORG_TEST')
  await page.getByLabel('指标名称', { exact: true }).fill('合成组织指标')
  await page.getByLabel('考核要求', { exact: true }).fill('合成学校当前组织数，待学校确认')
  await page.getByRole('button', { name: '保存指标版本', exact: true }).click()
  await page.getByRole('heading', { name: 'ORG_TEST · 合成组织指标' }).waitFor()
  const ruleRequest = requests.find(request => request.path === '/assessment/indicators')
  assert.equal(ruleRequest.body.org_unit_id, 'ui-school')
  assert.equal(ruleRequest.body.expected_version, 0)
  assert.equal(ruleRequest.body.confirmed, false)
  await page.getByRole('button', { name: '重新归集', exact: true }).click()
  await page.getByText('归集与当前数据一致', { exact: true }).waitFor()
  await page.locator('details').first().locator('summary').click()
  await page.getByRole('button', { name: /查看授权来源/ }).click()
  await page.getByRole('heading', { name: '来源记录核查', exact: true }).waitFor()
  await page.getByText('历史归集与计算版本', { exact: true }).click()
  await page.getByRole('button', { name: '核查归集版本', exact: true }).click()
  await page.getByRole('heading', { name: '历史归集核查', exact: true }).waitFor()
  await page.getByText('此版本与当前规则或数据有差异。', { exact: true }).waitFor()
  await page.getByRole('button', { name: '关闭历史详情', exact: true }).click()
  console.log('PASS: historical run preserves versions and identifies stale snapshots')
  console.log('PASS: rule creation, recalculation and authorized source drilldown')
  await page.getByRole('tab', { name: '年度任务', exact: true }).click()
  await page.getByRole('button', { name: '新增年度任务', exact: true }).click()
  await page.getByLabel('任务名称', { exact: true }).fill('合成年度任务')
  await page.getByRole('button', { name: '保存任务', exact: true }).click()
  await page.getByRole('alert').filter({ hasText: '合成并发冲突' }).waitFor()
  assert.equal(await page.getByLabel('任务名称', { exact: true }).inputValue(), '合成年度任务')
  await page.getByRole('button', { name: '保存任务', exact: true }).click()
  await page.getByRole('heading', { name: '合成年度任务', exact: true }).waitFor()
  assert.equal(state.tasks[0].owner_id, user.id)
  console.log('PASS: annual task, responsibility and failed-save input preservation')
  await page.getByRole('button', { name: '重新归集', exact: true }).click()
  await page.getByText('归集与当前数据一致', { exact: true }).waitFor()
  await page.getByRole('tab', { name: '计划草案', exact: true }).click()
  await page.getByRole('button', { name: '生成计划草案', exact: true }).click()
  await page.getByLabel('计划内容（供组织人员研究确定）', { exact: true }).waitFor()
  await page.getByLabel('计划内容（供组织人员研究确定）', { exact: true }).fill('人工修订：合成重点，时间安排待确认。')
  await page.getByRole('button', { name: '保存计划修订版本', exact: true }).click()
  await page.getByText('计划 v2', { exact: false }).waitFor()
  assert.equal(state.plan.review_status, 'pending')
  console.log('PASS: generated plan stays a draft; editing saves a new pending version')
  await page.getByRole('tab', { name: '佐证与缺项', exact: true }).click()
  assert.equal(await page.getByRole('button', { name: '归档审核后佐证目录', exact: true }).isDisabled(), true)
  const download = page.waitForEvent('download')
  await page.getByRole('button', { name: '导出材料目录', exact: true }).click()
  assert.ok((await download).suggestedFilename().endsWith('.zip'))
  console.log('PASS: default archive gate and authorized export request')
  await page.getByRole('tab', { name: '提醒与设置', exact: true }).click()
  await page.getByLabel('提前提醒天数', { exact: true }).fill('7')
  await page.getByRole('button', { name: '保存学校确认', exact: true }).click()
  await page.getByRole('status').filter({ hasText: '学校电子记录确认已保存' }).waitFor()
  assert.equal(state.policy.reminder_advance_days, 7)
  await page.getByRole('tab', { name: '指标与归集', exact: true }).click()
  await page.getByText('指标规则与生效版本', { exact: true }).click()
  await page.getByRole('button', { name: '修订版本', exact: true }).click()
  assert.equal(await page.getByLabel('指标编码', { exact: true }).inputValue(), 'ORG_TEST')
  assert.equal(await page.getByLabel('指标编码', { exact: true }).getAttribute('readonly'), '')
  console.log('PASS: shared policy settings and editing a Vue reactive rule')
  const screenshots = resolve(root, '../tmp/test-results/assessment-browser')
  await mkdir(screenshots, { recursive: true })
  await page.getByRole('button', { name: '取消', exact: true }).click()
  await page.evaluate(() => window.scrollTo(0, 0))
  await page.waitForFunction(() => window.scrollY === 0)
  await page.screenshot({ path: resolve(screenshots, 'desktop.png'), fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.evaluate(() => window.scrollTo(0, 0))
  await page.waitForFunction(() => document.querySelector('.rail').getBoundingClientRect().right <= 0)
  await page.screenshot({ path: resolve(screenshots, 'mobile.png'), fullPage: true })
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), 'Mobile page must not overflow horizontally')
  assert.deepEqual(errors, [])
  console.log('PASS: mobile layout and no browser runtime errors')
} finally {
  await browser?.close()
  await server.close()
}
