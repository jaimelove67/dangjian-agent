/** Session restoration must distinguish temporary outages from invalid credentials. */
import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'
import { chromium } from 'playwright'

const root = fileURLToPath(new URL('../', import.meta.url))
const server = await createServer({ root, configLoader: 'native', server: { host: '127.0.0.1', port: 0 } })
let browser

try {
  await server.listen()
  const base = `http://127.0.0.1:${server.httpServer.address().port}`
  browser = await chromium.launch({
    headless: true,
    executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ?? process.env.PARTY_CHROMIUM,
  })
  for (const failure of [429, 503, 'network', 401]) {
    const context = await browser.newContext()
    const page = await context.newPage()
    page.setDefaultTimeout(10000)
    const pageErrors = []
    page.on('pageerror', (error) => pageErrors.push(error.message))
    await page.addInitScript(() => {
      if (!sessionStorage.getItem('session-test-initialized')) {
        localStorage.setItem('party.access_token', 'synthetic-session-token')
        sessionStorage.setItem('session-test-initialized', 'yes')
      }
    })
    let outage = failure
    const calls = []
    await page.route(`${base}/api/**`, async (route) => {
      const path = new URL(route.request().url()).pathname.replace(/^\/api(?:\/v1)?/, '')
      calls.push(path)
      if (path === '/auth/me' && outage) {
        if (outage === 'network') return route.abort('connectionfailed')
        return route.fulfill({
          status: outage,
          headers: outage === 429 ? { 'Retry-After': '1' } : {},
          json: { code: outage * 100 + 1, message: `合成会话错误 ${outage}`, trace_id: 'synthetic-session' },
        })
      }
      const data = path === '/auth/me'
        ? { id: 'session-user', username: 'session-user', name: '合成党员', role: 'member', tenant_id: 'session-tenant' }
        : path === '/auth/codes' ? ['qa.ask']
          : path === '/qa/sessions' ? { items: [], total: 0, page: 1, page_size: 8 } : undefined
      assert.notEqual(data, undefined, `Unexpected session recovery API: ${path}`)
      await route.fulfill({ json: { code: 0, message: '成功', data, trace_id: 'synthetic-session' } })
    })
    await page.goto(`${base}/ask`, { waitUntil: 'networkidle' })
    if (failure === 401) {
      assert.equal(await page.evaluate(() => localStorage.getItem('party.access_token')), null)
      assert.equal(new URL(page.url()).pathname, '/login')
      await page.locator('#username').waitFor()
      assert.equal(calls.includes('/qa/sessions'), false)
      console.log('PASS: invalid credentials clear the session and keep business routes protected')
    } else {
      assert.equal(await page.evaluate(() => localStorage.getItem('party.access_token')), 'synthetic-session-token')
      assert.equal(new URL(page.url()).pathname, '/ask')
      await page.getByRole('alert').waitFor()
      assert.equal(calls.includes('/qa/sessions'), false, 'Incomplete authentication must not mount business content')
      outage = null
      const businessReady = page.waitForResponse((response) => new URL(response.url()).pathname === '/api/qa/sessions')
      await page.getByRole('button', { name: '重试恢复会话', exact: true }).click()
      await businessReady
      await page.getByRole('navigation', { name: '主导航' }).waitFor()
      assert.equal(new URL(page.url()).pathname, '/ask')
      assert.equal(calls.includes('/qa/sessions'), true)
      console.log(`PASS: ${failure} preserves credentials, shows the failure, and retries the original route`)
    }
    assert.deepEqual(pageErrors, [], 'No browser runtime errors')
    await context.close()
  }
} finally {
  await browser?.close()
  await server.close()
}
