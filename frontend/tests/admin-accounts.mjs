/** Actual Vue form, role guards and request contract with synthetic account data. */
import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'
import { chromium } from 'playwright'

const root = fileURLToPath(new URL('../', import.meta.url))
const server = await createServer({ root, configLoader: 'native', server: { host: '127.0.0.1', port: 0 } })
let browser
try {
  await server.listen()
  const base = `http://127.0.0.1:${server.httpServer.address().port}`
  browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE })
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
  page.setDefaultTimeout(10000)
  const errors = [], unexpected = [], requests = [], creations = []
  let phase = 'normal', rejectNextCreation = true
  const user = { id: 'admin', username: 'admin', name: '合成管理员', role: 'system_admin', tenant_id: 'synthetic-tenant', org_unit_id: 'school' }
  const organizations = [
    { id: 'school', name: '合成学校', org_type: 'school' },
    { id: 'department', name: '合成院系', org_type: 'department' },
    { id: 'branch', name: '合成支部', org_type: 'branch' },
  ]
  page.on('pageerror', (error) => errors.push(error.message))
  await page.addInitScript(() => localStorage.setItem('party.access_token', 'synthetic-admin-token'))
  await page.route(`${base}/api/**`, async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname.replace(/^\/api(?:\/v1)?/, '')
    requests.push(path)
    let data
    if (path === '/auth/me') data = user
    else if (path === '/auth/codes') data = ['qa.ask', 'admin.config']
    else if (path === '/admin/org-units') {
      if (phase === 'load-error') {
        await route.fulfill({ status: 503, json: { code: 50301, message: '合成组织加载失败', data: null, trace_id: 'synthetic-load-error' } })
        return
      }
      data = phase === 'empty' ? [] : organizations
    } else if (path === '/admin/users' && request.method() === 'POST') {
      const body = request.postDataJSON()
      creations.push(body)
      if (rejectNextCreation) {
        rejectNextCreation = false
        await route.fulfill({ status: 409, json: { code: 40901, message: '用户名不可用，请更换后重试', data: null, trace_id: 'synthetic-conflict' } })
        return
      }
      await new Promise((done) => setTimeout(done, 250))
      data = {
        id: `created-${creations.length}`, username: body.username, name: body.name, role: body.role,
        tenant_id: user.tenant_id, org_unit_id: body.org_unit_id,
        org_name: organizations.find((org) => org.id === body.org_unit_id).name,
      }
    } else {
      unexpected.push(path)
      await route.fulfill({ status: 404, json: { code: 40401, message: `Unexpected synthetic API: ${path}` } })
      return
    }
    await route.fulfill({ status: request.method() === 'POST' ? 201 : 200, json: { code: 0, message: '成功', data, trace_id: 'synthetic-account' } })
  })
  async function screenshot(name) {
    const directory = resolve(process.env.UI_SCREENSHOT_DIR || resolve(root, '../tmp/test-results/admin-accounts'))
    await mkdir(directory, { recursive: true })
    await page.screenshot({ path: resolve(directory, `${name}.png`), fullPage: true })
  }
  async function password(value, confirmation = value) {
    await page.getByLabel('密码', { exact: true }).fill(value)
    await page.getByLabel('确认密码', { exact: true }).fill(confirmation)
  }

  for (const role of ['member', 'applicant', 'organizer', 'branch_secretary', 'department_admin', 'school_admin']) {
    user.role = role
    requests.length = 0
    await page.goto(`${base}/accounts`, { waitUntil: 'networkidle' })
    assert.equal(new URL(page.url()).pathname, '/forbidden', role)
    assert.equal(await page.getByRole('link', { name: '创建账号', exact: true }).count(), 0, role)
    assert.equal(requests.filter((path) => path.startsWith('/admin/')).length, 0, role)
  }
  console.log('PASS: all six other roles lack the menu and cannot load the account page or its APIs')

  user.role = 'system_admin'
  await page.goto(`${base}/accounts`, { waitUntil: 'networkidle' })
  assert.equal(await page.getByRole('link', { name: '创建账号', exact: true }).count(), 1)
  assert.equal(await page.getByLabel('角色', { exact: true }).inputValue(), 'member')
  assert.equal(await page.getByLabel('角色', { exact: true }).locator('option').count(), 7)
  const organization = page.getByLabel('所属组织', { exact: true })
  assert.deepEqual(await organization.locator('option').allTextContents(), ['请选择组织', '合成支部 · 支部'])
  await organization.selectOption('branch')
  await page.getByLabel('角色', { exact: true }).selectOption('department_admin')
  assert.equal(await organization.inputValue(), '')
  assert.deepEqual(await organization.locator('option').allTextContents(), ['请选择组织', '合成院系 · 院系'])
  await page.getByLabel('角色', { exact: true }).selectOption('member')
  await organization.selectOption('branch')
  console.log('PASS: default role has least privilege and organization choices follow the selected role')

  const submit = page.getByRole('button', { name: '创建账号', exact: true })
  await page.getByLabel('用户名', { exact: true }).fill('  first-member  ')
  await page.getByLabel('姓名', { exact: true }).fill('  合成新党员  ')
  await password('synthetic-password', 'different-password')
  await page.getByText('两次输入的密码不一致。', { exact: true }).waitFor()
  assert.ok(await submit.isDisabled())
  await password('中'.repeat(25))
  assert.ok(await submit.isDisabled(), 'UTF-8 password over 72 bytes is rejected')
  await password('中'.repeat(24))
  assert.ok(await submit.isEnabled(), '72-byte UTF-8 password is allowed')
  await password('🔐'.repeat(4))
  assert.ok(await submit.isDisabled(), 'length counts Unicode characters consistently with the backend')
  await password('synthetic-password')
  assert.ok(await submit.isEnabled())
  console.log('PASS: password confirmation, character count and bcrypt byte limit are enforced')

  await submit.click()
  await page.getByText('用户名不可用，请更换后重试', { exact: true }).waitFor()
  assert.equal(await page.getByLabel('用户名', { exact: true }).inputValue(), '  first-member  ')
  assert.equal(await page.getByLabel('密码', { exact: true }).inputValue(), 'synthetic-password')
  assert.equal(await organization.inputValue(), 'branch')
  await page.getByText('synthetic-conflict', { exact: true }).waitFor()
  console.log('PASS: creation failure explains the conflict and retains input for correction')

  await page.getByLabel('用户名', { exact: true }).fill('  available-member  ')
  await submit.click()
  assert.ok(await page.getByRole('button', { name: '正在创建…', exact: true }).isDisabled())
  await page.locator('form').evaluate((form) => form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })))
  await page.getByRole('heading', { name: '账号创建成功', exact: true }).waitFor()
  assert.equal(creations.length, 2, 'busy state prevents a second simultaneous request')
  assert.deepEqual(creations[1], { username: 'available-member', name: '合成新党员', role: 'member', org_unit_id: 'branch', password: 'synthetic-password' })
  assert.equal(await page.getByLabel('用户名', { exact: true }).inputValue(), '')
  assert.equal(await page.getByLabel('密码', { exact: true }).inputValue(), '')
  assert.equal(await page.getByLabel('确认密码', { exact: true }).inputValue(), '')
  assert.ok(!(await page.locator('main').innerText()).includes('synthetic-password'))
  assert.ok(!(await page.evaluate(() => JSON.stringify({ ...localStorage }))).includes('synthetic-password'))
  await page.getByRole('link', { name: '前往党员发展关联档案', exact: true }).waitFor()
  await screenshot('accounts-desktop')
  console.log('PASS: successful creation trims input, clears credentials and shows account and archive guidance')

  await page.setViewportSize({ width: 390, height: 844 })
  await page.waitForFunction(() => document.querySelector('#app-rail').getBoundingClientRect().right <= 1)
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1))
  await screenshot('accounts-mobile')
  console.log('PASS: mobile page fits without horizontal scrolling')

  phase = 'load-error'
  await page.reload({ waitUntil: 'networkidle' })
  await page.getByText('合成组织加载失败', { exact: true }).waitFor()
  assert.equal(await page.getByLabel('用户名', { exact: true }).count(), 0)
  phase = 'normal'
  await page.getByRole('button', { name: '重新加载组织', exact: true }).click()
  await page.getByLabel('用户名', { exact: true }).waitFor()
  phase = 'empty'
  await page.reload({ waitUntil: 'networkidle' })
  await page.getByText('尚未配置组织', { exact: true }).waitFor()
  assert.equal(await page.getByLabel('用户名', { exact: true }).count(), 0)
  console.log('PASS: organization fetch errors can be retried; missing organizations block creation')
  assert.deepEqual(errors, [], 'no browser runtime errors')
  assert.deepEqual(unexpected, [], 'no unexpected API requests')
} finally {
  await browser?.close()
  await server.close()
}
