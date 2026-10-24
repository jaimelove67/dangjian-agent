/** Real member pages with explicitly synthetic HTTP data. */
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
  const page = await browser.newPage()
  page.setDefaultTimeout(10000)
  const errors = [], unexpected = [], submissions = []
  const materials = []
  let linked = true, failNextSubmit = true
  page.on('pageerror', (error) => errors.push(error.message))
  await page.addInitScript(() => localStorage.setItem('party.access_token', 'synthetic-member-token'))
  const user = { id: 'self', username: 'self', name: '合成党员', role: 'member', tenant_id: 'synthetic-tenant', org_unit_id: 'synthetic-branch' }
  const profile = { id: 'self-profile', user_id: 'self', name: '合成本人档案', org_name: '合成支部', stage: 'member', stage_joined_on: '2020-01-01', materials: ['组织已核验材料'], pending: 0, days_in_stage: 1000 }
  function field(body, name) { return new RegExp(`name="${name}"\\r?\\n\\r?\\n([^\\r\\n]*)`).exec(body)?.[1] }
  await page.route(`${base}/api/**`, async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname.replace(/^\/api(?:\/v1)?/, '')
    let data
    if (path === '/auth/me') data = user
    else if (path === '/auth/codes') data = ['qa.ask', 'member.self_query', 'member.material_submit', 'knowledge.query', 'knowledge.manage', 'member.query', 'study.query', 'assessment.query', 'admin.config']
    else if (path === '/member/self/archive') data = { profile: linked ? profile : null, max_upload_size: 10 * 1024 * 1024 }
    else if (path === '/member/self/materials' && request.method() === 'GET') data = { items: materials, total: materials.length, page: 1, page_size: 20 }
    else if (path === '/member/self/materials' && request.method() === 'POST') {
      const body = request.postData()
      submissions.push(body)
      if (failNextSubmit) {
        failNextSubmit = false
        await route.fulfill({ status: 503, json: { code: 50301, message: '合成提交失败，请重试', trace_id: 'synthetic-submit-failure' } })
        return
      }
      data = { id: 'self-material', title: field(body, 'title'), category: field(body, 'category'), description: field(body, 'description'), file_name: '本人材料.txt', file_size: 16, created_at: '2026-10-11T10:00:00', status: 'submitted' }
      materials.push(data)
    }
    else if (path === '/member/self/materials/self-material/file') {
      await route.fulfill({ contentType: 'application/octet-stream', body: 'synthetic private material' })
      return
    }
    else {
      unexpected.push(path)
      await route.fulfill({ status: 404, json: { code: 40401, message: `Unexpected synthetic API: ${path}` } })
      return
    }
    await route.fulfill({ json: { code: 0, message: '成功', data, trace_id: 'synthetic-member' } })
  })
  async function screenshot(name) {
    if (!process.env.UI_SCREENSHOT_DIR) return
    await mkdir(resolve(process.env.UI_SCREENSHOT_DIR), { recursive: true })
    await page.screenshot({ path: resolve(process.env.UI_SCREENSHOT_DIR, `${name}.png`), fullPage: true })
  }

  await page.goto(`${base}/my-archive`, { waitUntil: 'networkidle' })
  assert.deepEqual(await page.getByRole('navigation', { name: '主导航' }).getByRole('link').allTextContents(), ['本人档案', '个人材料', '制度问答'])
  await page.getByText('合成本人档案', { exact: true }).waitFor()
  assert.equal(await page.locator('main input, main select, main textarea').count(), 0)
  await screenshot('member-archive')
  console.log('PASS: exactly three member functions and read-only personal archive')

  for (const path of ['/knowledge', '/members', '/study', '/assessment', '/system']) {
    await page.goto(`${base}${path}`, { waitUntil: 'networkidle' })
    assert.equal(new URL(page.url()).pathname, '/forbidden', path)
  }
  await page.goto(`${base}/my-archive`, { waitUntil: 'networkidle' })

  await page.getByRole('link', { name: '提交个人材料', exact: true }).click()
  await page.getByLabel('材料标题', { exact: true }).fill('本人思想汇报')
  await page.getByLabel('材料说明（选填）', { exact: true }).fill('合成说明，仅供组织核验')
  await page.getByLabel('材料文件', { exact: true }).setInputFiles({ name: '本人材料.txt', mimeType: 'text/plain', buffer: Buffer.from('synthetic private material') })
  await page.getByRole('button', { name: '提交材料', exact: true }).click()
  await page.getByText('合成提交失败，请重试', { exact: true }).waitFor()
  assert.equal(await page.getByLabel('材料标题', { exact: true }).inputValue(), '本人思想汇报')
  assert.equal(await page.getByLabel('材料文件', { exact: true }).evaluate((input) => input.files.length), 1)
  await page.getByRole('button', { name: '提交材料', exact: true }).click()
  await page.getByRole('heading', { name: '本人思想汇报', exact: true }).waitFor()
  assert.equal(materials.length, 1)
  assert.equal(field(submissions[0], 'submission_key'), field(submissions[1], 'submission_key'))
  assert.ok(field(submissions[0], 'submission_key'))
  assert.equal(field(submissions[1], 'category'), 'thought_report')
  assert.equal(field(submissions[1], 'description'), '合成说明，仅供组织核验')
  assert.ok(!submissions[1].includes('name="user_id"') && !submissions[1].includes('name="profile_id"'))
  assert.equal(await page.getByLabel('材料文件', { exact: true }).inputValue(), '')
  console.log('PASS: multipart submission preserves input on failure and retries with the same submission key')

  const downloaded = page.waitForEvent('download')
  await page.getByRole('button', { name: '下载原件', exact: true }).click()
  assert.equal((await downloaded).suggestedFilename(), '本人材料.txt')
  await page.reload({ waitUntil: 'networkidle' })
  await page.getByRole('heading', { name: '本人思想汇报', exact: true }).waitFor()
  await screenshot('member-materials')
  await page.setViewportSize({ width: 390, height: 844 })
  await page.waitForFunction(() => document.querySelector('#app-rail').getBoundingClientRect().right <= 1)
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1))
  await screenshot('member-materials-mobile')
  console.log('PASS: stored submissions survive reload, original download works, and mobile layout fits')

  linked = false
  await page.reload({ waitUntil: 'networkidle' })
  await page.getByText('尚未关联本人档案', { exact: true }).waitFor()
  assert.equal(await page.getByRole('button', { name: '提交材料', exact: true }).count(), 0)
  assert.deepEqual(errors, [])
  assert.deepEqual(unexpected, [])
  console.log('PASS: unlinked accounts cannot submit; no browser errors or unexpected requests')
} finally {
  await browser?.close()
  await server.close()
}
