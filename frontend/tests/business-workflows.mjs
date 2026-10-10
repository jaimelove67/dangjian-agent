/** Browser contract regression: real Vue pages with synthetic API responses. */
import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'
import { chromium } from 'playwright'

const root = process.env.UI_SOURCE_ROOT ?? fileURLToPath(new URL('../', import.meta.url))
const server = await createServer({ root, configLoader: 'native', server: { host: '127.0.0.1', port: 0 } })
let browser
try {
  await server.listen()
  const address = server.httpServer.address()
  browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE })
  const page = await browser.newPage()
  page.setDefaultTimeout(10000)
  const browserErrors = []
  page.on('pageerror', (error) => browserErrors.push(error.message))
  await page.addInitScript(() => localStorage.setItem('party.access_token', 'synthetic-ui-token'))
  const requests = []
  const user = { id: 'ui-user', username: 'ui-user', name: '测试用户', role: 'department_admin', tenant_id: 'ui-tenant', org_unit_id: 'ui-org' }
  const roster = [{ id: 'ui-member', name: '合成培养对象', org_name: '合成组织', org_unit_id: 'ui-org', stage: 'activist', stage_joined_on: '2024-01-01', days_in_stage: 400, materials: ['入党申请书'], pending: 0 }]
  const organizations = [{ id: 'ui-org', name: '合成组织', org_type: 'department' }]
  const documents = Array.from({ length: 41 }, (_, index) => ({
    id: `ui-doc-${index}`, doc_id: `DOC-${index}`, file_name: 'synthetic.txt', title: `合成制度 ${index}`,
    issuer: '合成单位', level: 'school', visibility: 'school', security_level: 'internal',
    status: 'effective', effective_date: '2020-01-01', expiration_date: null, tags: [], content_revision: 1,
  }))
  const answer = {
    answer: '第一条要求提交申请。[1]', citations: [{ title: '合成制度', issuer: '合成单位', content: '第一条 要求提交申请。', score: 0.9, index: 1, doc_id: 'DOC-QA-1', file_name: 'synthetic.txt', effective_date: '2020-01-01' }],
    retrieved_count: 2, used_count: 1, has_sufficient_evidence: true,
    warnings: ['请核对文件时效。'], disclaimer: '本回答仅供参考，具体以组织部门确认为准。', refused: false,
  }
  const history = [{ ...answer, id: 'ui-history', question: '历史培养期需要多久？', data_level: 'internal', created_at: '2026-10-10T03:00:00', session_id: 'past-session' }]
  let failNextDelete = false
  let failNextHistory = false
  const unexpectedRequests = []
  async function screenshot(name) {
    if (!process.env.UI_SCREENSHOT_DIR) return
    const directory = resolve(process.env.UI_SCREENSHOT_DIR)
    await mkdir(directory, { recursive: true })
    await page.screenshot({ path: resolve(directory, name + '.png'), fullPage: true })
  }
  await page.route(`http://127.0.0.1:${address.port}/api/**`, async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname.replace(/^\/api(?:\/v1)?/, '')
    requests.push({ path, method: request.method(), body: request.postDataJSON() })
    let data
    if (path === '/auth/me') data = user
    else if (path === '/auth/codes') data = ['qa.ask', 'knowledge.query', 'knowledge.manage', 'member.query', 'member.stage_transition']
    else if (path === '/member/org-units') data = organizations
    else if (path === '/member/roster' && request.method() === 'GET') data = { items: roster, total: roster.length, page: 1, page_size: 40 }
    else if (path === '/member/roster' && request.method() === 'POST') {
      const body = request.postDataJSON()
      data = { ...body, id: 'ui-member-2', org_name: '合成组织', stage: body.current_stage, stage_joined_on: body.stage_joined_on ?? '2026-10-10', days_in_stage: 400 }
      roster.unshift(data)
    }
    else if (path === '/member/transition-suggestion') data = { current_stage: request.postDataJSON().current_stage, suggested_target: request.postDataJSON().target_stage, eligible: false, procedures: [], blockers: ['待人工确认'], note: '阶段流转须人工确认。' }
    else if (path === '/member/todo-suggestions') data = { todos: [{ category: 'material', content: '补齐培养考察记录' }], note: '阶段流转须人工确认。' }
    else if (path === '/knowledge-docs' && request.method() === 'GET') {
      const pageNumber = Number(url.searchParams.get('page') ?? 1)
      const pageSize = Number(url.searchParams.get('page_size') ?? 40)
      const q = url.searchParams.get('q') ?? ''
      const matched = documents.filter((doc) => doc.title.includes(q))
      data = { items: matched.slice((pageNumber - 1) * pageSize, pageNumber * pageSize), total: matched.length, page: pageNumber, page_size: pageSize, counts: { all: matched.length, effective: matched.length } }
    }
    else if (path.startsWith('/knowledge-docs/') && request.method() === 'DELETE') {
      if (failNextDelete) {
        failNextDelete = false
        await route.fulfill({ status: 403, json: { code: 40301, message: '合成权限不足', data: null, trace_id: 'synthetic-denied' } })
        return
      }
      const index = documents.findIndex((document) => document.doc_id === decodeURIComponent(path.split('/').at(-1)))
      assert.notEqual(index, -1)
      data = documents.splice(index, 1)[0]
    }
    else if (path === '/qa/sessions') {
      if (failNextHistory) {
        failNextHistory = false
        await route.fulfill({ status: 503, json: { code: 50301, message: '合成历史暂不可用', data: null, trace_id: 'synthetic-history' } })
        return
      }
      const pageNumber = Number(url.searchParams.get('page') ?? 1)
      const pageSize = Number(url.searchParams.get('page_size') ?? 8)
      data = { items: history.slice((pageNumber - 1) * pageSize, pageNumber * pageSize), total: history.length, page: pageNumber, page_size: pageSize }
    }
    else if (path === '/qa' && request.method() === 'POST') {
      const body = request.postDataJSON()
      data = { ...answer, session_id: body.session_id }
      history.unshift({ ...data, id: 'ui-history-2', question: body.question, data_level: body.data_level, created_at: '2026-10-10T03:05:00' })
    }
    else {
      unexpectedRequests.push(path)
      await route.fulfill({ status: 404, json: { code: 40401, message: 'Unexpected synthetic API: ' + path } })
      return
    }
    await route.fulfill({ json: { code: 0, message: '成功', data, trace_id: 'synthetic-ui' } })
  })
  await page.goto(`http://127.0.0.1:${address.port}/members`)
  await page.getByRole('tab', { name: '流转建议', exact: true }).waitFor().catch(async (error) => {
    console.error('Page:', page.url(), (await page.locator('body').innerText()).slice(0, 1200))
    throw error
  })
  await page.getByRole('tab', { name: '流转建议', exact: true }).click()
  const target = await page.locator('#tgt').inputValue()
  const response = page.waitForResponse((response) => response.url().includes('/member/transition-suggestion'))
  await page.getByRole('button', { name: '生成流转建议', exact: true }).click()
  await response
  const transition = requests.find((request) => request.path === '/member/transition-suggestion')
  assert.equal(transition.body.target_stage, target, 'Transition request must include the selected target stage')
  console.log('PASS: selected target stage reaches the real transition request')
  assert.ok(requests.some((request) => request.path === '/member/roster' && request.method === 'GET'))
  await page.getByRole('button', { name: '登记培养对象', exact: true }).click()
  await page.getByLabel('姓名', { exact: true }).fill('合成新增培养对象')
  await page.getByLabel('所属组织', { exact: true }).selectOption('ui-org')
  await page.getByLabel('已确认的当前阶段', { exact: true }).selectOption('activist')
  await page.getByLabel('已具备材料（每行一项）', { exact: true }).fill('入党申请书\n思想汇报')
  await screenshot('member-registration')
  const registered = page.waitForResponse((response) => response.url().endsWith('/member/roster') && response.request().method() === 'POST')
  await page.getByRole('button', { name: '保存登记', exact: true }).click()
  await registered
  await page.locator('.work__name').filter({ hasText: '合成新增培养对象' }).waitFor()
  const registration = requests.find((request) => request.path === '/member/roster' && request.method === 'POST')
  assert.equal(registration.body.org_unit_id, 'ui-org')
  assert.deepEqual(registration.body.materials, ['入党申请书', '思想汇报'])
  await page.getByRole('tab', { name: '待办建议', exact: true }).click()
  const todoResponse = page.waitForResponse((response) => response.url().includes('/member/todo-suggestions'))
  await page.getByRole('button', { name: '生成待办建议', exact: true }).click()
  await todoResponse
  const todo = requests.find((request) => request.path === '/member/todo-suggestions')
  assert.deepEqual(todo.body.materials, registration.body.materials)
  assert.equal(todo.body.days_in_stage, 400)
  console.log('PASS: real roster, manual registration, and selected materials reach the rule API')

  await page.goto(`http://127.0.0.1:${address.port}/knowledge`)
  await page.getByRole('button', { name: '下一页', exact: true }).click()
  const lastRow = page.getByRole('row').filter({ hasText: '合成制度 40' })
  await lastRow.waitFor()
  await lastRow.getByText('合成制度 40', { exact: true }).click()
  await page.getByRole('heading', { name: '文件详情', exact: true }).waitFor()
  page.once('dialog', (dialog) => dialog.accept())
  const removed = page.waitForResponse((response) => response.request().method() === 'DELETE')
  await lastRow.getByRole('button', { name: '移除', exact: true }).click()
  await removed
  await page.getByText('共 40 条，第 1 页。选择行可查看完整信息。', { exact: true }).waitFor()
  assert.equal(await page.getByRole('heading', { name: '文件详情', exact: true }).count(), 0)
  assert.equal(await page.getByRole('button', { name: '下一页', exact: true }).count(), 0)
  await screenshot('knowledge-after-removal')
  failNextDelete = true
  page.once('dialog', (dialog) => dialog.accept())
  await page.getByRole('row').filter({ hasText: '合成制度 0' }).getByRole('button', { name: '移除', exact: true }).click()
  await page.getByText('合成权限不足', { exact: true }).waitFor()
  assert.equal(documents.length, 40)
  assert.ok(requests.some((request) => request.path === '/knowledge-docs' && request.method === 'GET'))
  console.log('PASS: soft deletion refreshes server counts, closes details, returns from an empty last page, and preserves rows on failure')

  await page.goto(`http://127.0.0.1:${address.port}/ask`)
  await page.getByRole('button', { name: /历史培养期需要多久/ }).click()
  await page.getByText('当前展示历史回答，引用的文件可能已经更新或失效。再次提问会重新检索。', { exact: true }).waitFor()
  await page.getByText('DOC-QA-1', { exact: true }).waitFor()
  await page.getByText('请核对文件时效。', { exact: true }).waitFor()
  await screenshot('qa-history')
  await page.locator('#question').fill('它需要哪些材料？')
  const asked = page.waitForResponse((response) => response.url().endsWith('/qa') && response.request().method() === 'POST')
  await page.getByRole('button', { name: '提问', exact: true }).click()
  await asked
  await page.locator('.recent-item').filter({ hasText: '它需要哪些材料？' }).waitFor()
  assert.equal(requests.findLast((request) => request.path === '/qa').body.session_id, 'past-session')
  await page.getByRole('button', { name: '清空', exact: true }).click()
  await page.locator('#question').fill('独立制度问题')
  const freshAsk = page.waitForResponse((response) => response.url().endsWith('/qa') && response.request().method() === 'POST')
  await page.getByRole('button', { name: '提问', exact: true }).click()
  await freshAsk
  assert.notEqual(requests.findLast((request) => request.path === '/qa').body.session_id, 'past-session')
  await page.locator('.recent-item').filter({ hasText: '独立制度问题' }).waitFor()
  failNextHistory = true
  await page.reload()
  await page.getByText('合成历史暂不可用', { exact: true }).waitFor()
  await page.getByRole('button', { name: '重试历史查询', exact: true }).click()
  await page.locator('.recent-item').filter({ hasText: '独立制度问题' }).waitFor()
  await page.setViewportSize({ width: 390, height: 844 })
  await page.waitForFunction(() => document.querySelector('#app-rail').getBoundingClientRect().right <= 1)
  await screenshot('qa-history-mobile')
  console.log('PASS: persistent history preserves citations and warnings, restores its session, starts fresh on reset, and supports failure retry')
  assert.deepEqual(browserErrors, [])
  assert.deepEqual(unexpectedRequests, [])
} finally {
  await browser?.close()
  await server.close()
}
