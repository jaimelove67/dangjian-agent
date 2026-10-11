/** Role boundary regression: real Vue routes and pages with synthetic API data. */
import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'
import { chromium } from 'playwright'

const root = fileURLToPath(new URL('../', import.meta.url))
const server = await createServer({ root, configLoader: 'native', server: { host: '127.0.0.1', port: 0 } })
let browser
const failures = []

async function check(name, run) {
  try {
    await run()
    console.log('PASS:', name)
  } catch (error) {
    failures.push(error)
    console.error('FAIL:', name, error.message)
  }
}

try {
  await server.listen()
  const base = `http://127.0.0.1:${server.httpServer.address().port}`
  browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE })
  const page = await browser.newPage()
  page.setDefaultTimeout(5000)
  const errors = []
  const requests = []
  const unexpected = []
  let permissions = ['qa.ask', 'member.self_query', 'member.material_submit']
  async function screenshot(name) {
    if (!process.env.UI_SCREENSHOT_DIR) return
    const directory = resolve(process.env.UI_SCREENSHOT_DIR)
    await mkdir(directory, { recursive: true })
    await page.screenshot({ path: resolve(directory, `${name}.png`), fullPage: true })
  }
  page.on('pageerror', (error) => errors.push(error.message))
  await page.addInitScript(() => localStorage.setItem('party.access_token', 'synthetic-role-token'))
  const user = { id: 'role-user', username: 'role-user', name: '合成党员', role: 'member', tenant_id: 'role-tenant', org_unit_id: 'role-org' }
  const doc = { id: 'role-doc', doc_id: 'ROLE-DOC', title: '授权制度', file_name: 'synthetic.txt', issuer: '合成学校', level: 'school', visibility: 'school', security_level: 'internal', status: 'effective', effective_date: '2020-01-01', expiration_date: null, tags: [], content_revision: 1 }
  await page.route(`${base}/api/**`, async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname.replace(/^\/api(?:\/v1)?/, '')
    requests.push({ path, method: request.method() })
    let data
    if (path === '/auth/me') data = user
    else if (path === '/auth/codes') data = permissions
    else if (path === '/qa/sessions') data = { items: [], total: 0, page: 1, page_size: 8 }
    else if (path === '/knowledge-docs') data = { items: [doc], total: 1, page: 1, page_size: 40, counts: { all: 1, effective: 1 } }
    else if (path === '/health' || path === '/admin/health') data = { status: 'healthy', service: '合成服务', version: 'test', environment: 'test' }
    else if (path === '/health/ready' || path === '/admin/health/ready') data = { status: 'ready', checks: { database: 'healthy' }, model_capabilities: { chat: 'configured' } }
    else {
      unexpected.push(path)
      await route.fulfill({ status: 404, json: { code: 40401, message: `Unexpected synthetic API: ${path}` } })
      return
    }
    await route.fulfill({ json: { code: 0, message: '成功', data, trace_id: 'synthetic-role' } })
  })

  await page.goto(`${base}/ask`, { waitUntil: 'networkidle' })
  await check('党员菜单严格包含本人档案、个人材料、制度问答三个功能', async () => {
    const menu = page.getByRole('navigation', { name: '主导航' })
    assert.deepEqual(await menu.getByRole('link').allTextContents(), ['本人档案', '个人材料', '制度问答'])
  })
  await check('党员菜单隐藏系统内容', async () => {
    assert.equal(await page.getByRole('navigation', { name: '主导航' }).getByRole('link', { name: '系统状态', exact: true }).count(), 0)
  })

  await page.goto(`${base}/system`, { waitUntil: 'networkidle' })
  await check('直接访问系统页面也被拦截且不请求系统信息', async () => {
    assert.notEqual(new URL(page.url()).pathname, '/system')
    assert.equal(requests.filter((request) => request.path.includes('/health')).length, 0)
    await page.getByRole('heading', { name: '无法访问该页面', exact: true }).waitFor()
  })

  requests.length = 0
  await page.goto(`${base}/knowledge`, { waitUntil: 'networkidle' })
  await check('党员直接访问知识库也被拒绝，不请求知识库接口', async () => {
    assert.equal(new URL(page.url()).pathname, '/forbidden')
    assert.equal(requests.filter((request) => request.path.startsWith('/knowledge')).length, 0)
  })

  requests.length = 0
  await page.goto(`${base}/members`, { waitUntil: 'networkidle' })
  await check('业务页面权限不足时展示提示，不跳转到系统页', async () => {
    assert.notEqual(new URL(page.url()).pathname, '/system')
    await page.getByRole('heading', { name: '无法访问该页面', exact: true }).waitFor()
    assert.equal(requests.filter((request) => request.path.includes('/health') || request.path.startsWith('/member/')).length, 0)
    await page.setViewportSize({ width: 390, height: 844 })
    await page.waitForFunction(() => document.querySelector('#app-rail').getBoundingClientRect().right <= 1)
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1))
    await screenshot('member-forbidden-mobile')
    await page.setViewportSize({ width: 1280, height: 720 })
  })

  for (const role of ['applicant', 'organizer', 'branch_secretary', 'department_admin', 'school_admin', 'system_admin']) {
    user.role = role
    const canManage = ['department_admin', 'school_admin', 'system_admin'].includes(role)
    const canViewSystem = role === 'system_admin'
    permissions = ['qa.ask', 'knowledge.query', ...(canManage ? ['knowledge.manage'] : []), ...(canViewSystem ? ['admin.config'] : [])]
    requests.length = 0
    await page.goto(`${base}/knowledge`, { waitUntil: 'networkidle' })
    await check(`${role} 的知识维护与系统访问权限正确`, async () => {
      assert.equal(new URL(page.url()).pathname, '/knowledge')
      assert.equal(await page.getByRole('link', { name: '本人档案', exact: true }).count(), 0)
      assert.equal(await page.getByRole('link', { name: '个人材料', exact: true }).count(), 0)
      assert.equal(await page.getByRole('button', { name: '上传文件', exact: true }).count(), Number(canManage))
      assert.equal(await page.getByRole('columnheader', { name: '操作', exact: true }).count(), Number(canManage))
      await page.getByText('授权制度', { exact: true }).click()
      assert.equal(await page.getByRole('button', { name: '保存新版本', exact: true }).count(), Number(canManage))
      assert.equal(await page.getByRole('link', { name: '系统状态', exact: true }).count(), Number(canViewSystem))
      await page.goto(`${base}/system`, { waitUntil: 'networkidle' })
      if (canViewSystem) {
        assert.equal(new URL(page.url()).pathname, '/system')
        await page.getByRole('heading', { name: '服务连通性', exact: true }).waitFor()
        assert.ok(requests.some((request) => request.path === '/admin/health'))
        assert.ok(requests.some((request) => request.path === '/admin/health/ready'))
        assert.equal(requests.filter((request) => request.path.startsWith('/health')).length, 0)
        await screenshot('admin-system')
      } else {
        assert.equal(new URL(page.url()).pathname, '/forbidden')
        assert.equal(requests.filter((request) => request.path.includes('/health')).length, 0)
      }
      assert.equal(requests.filter((request) => request.method !== 'GET').length, 0)
    })
  }
  for (const role of ['applicant', 'member', 'organizer', 'branch_secretary', 'department_admin', 'school_admin']) {
    user.role = role
    permissions = ['qa.ask', 'knowledge.query', 'admin.config']
    requests.length = 0
    await check(`${role} 即使持有系统权限码也不能查看系统详情`, async () => {
      await page.goto(`${base}/ask`, { waitUntil: 'networkidle' })
      assert.equal(await page.locator('a[href="/system"]').count(), 0)
      assert.equal(await page.getByRole('button', { name: /查看系统详情/ }).count(), 0)
      assert.equal(await page.locator('.rail__group-label').filter({ hasText: /^系统$/ }).count(), 0)
      await page.goto(`${base}/system`, { waitUntil: 'networkidle' })
      assert.equal(new URL(page.url()).pathname, '/forbidden')
      await page.getByRole('heading', { name: '无法访问该页面', exact: true }).waitFor()
      assert.equal(await page.locator('a[href="/system"]').count(), 0)
      assert.equal(requests.filter((request) => request.path.includes('/health')).length, 0)
    })
  }

  user.role = 'system_admin'
  permissions = ['qa.ask', 'knowledge.query']
  requests.length = 0
  await check('平台管理员按角色查看系统详情，不依赖配置管理权限码', async () => {
    await page.goto(`${base}/ask`, { waitUntil: 'networkidle' })
    await page.getByRole('link', { name: '系统状态', exact: true }).click()
    await page.getByRole('heading', { name: '服务连通性', exact: true }).waitFor()
    assert.equal(new URL(page.url()).pathname, '/system')
    assert.ok(requests.some((request) => request.path === '/admin/health'))
    assert.ok(requests.some((request) => request.path === '/admin/health/ready'))
  })

  assert.deepEqual(errors, [], 'No browser runtime errors')
  assert.deepEqual(unexpected, [], 'No unexpected API requests')
  if (failures.length) throw new AggregateError(failures, `${failures.length} role boundary checks failed`)
} finally {
  await browser?.close()
  await server.close()
}
