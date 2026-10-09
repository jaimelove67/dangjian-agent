// 问答交互验证：填入问题、提交、断言回答与引用渲染，并截图。
import { chromium } from 'playwright'

const BASE = 'http://127.0.0.1:5666'
const OUT = process.argv[2] || 'shots'

function ok(data) {
  return { status: 200, contentType: 'application/json', body: JSON.stringify({ code: 0, message: 'success', data, trace_id: 'shot-trace-0001' }) }
}

const USER = { id: 'u-001', username: 'organizer_wang', name: '王砚秋', role: 'organizer', tenant_id: 'tenant-main', org_unit_id: 'org-x', email: null, phone: null }
const PERMISSIONS = ['qa.ask', 'knowledge.query', 'knowledge.manage', 'member.query', 'member.stage_transition']
const QA_RESPONSE = {
  answer:
    '入党积极分子确定后，党组织应当指定一至两名正式党员作为培养联系人，对其进行培养教育和考察。[1]\n\n培养教育考察期一般不少于一年。党组织每半年至少对其进行一次考察并形成考察记录。[1][2]\n\n确定为发展对象，应当经支部委员会讨论同意，并进行政治审查。[2]',
  citations: [
    { title: '中国共产党发展党员工作细则', issuer: '中共中央办公厅', doc_number: '中办发〔2014〕34号', article: '第九条', content: '党组织应当指定一至两名正式党员作为入党积极分子的培养联系人，对其进行培养教育和考察。', score: 0.87 },
    { title: '中国共产党发展党员工作细则', issuer: '中共中央办公厅', doc_number: '中办发〔2014〕34号', article: '第十六条', content: '党组织每半年对入党积极分子进行一次考察，把经过一年以上培养教育和考察、基本具备党员条件的入党积极分子，列为发展对象。', score: 0.74 },
  ],
  retrieved_count: 20,
  used_count: 2,
  has_sufficient_evidence: true,
}

const browser = await chromium.launch({ channel: 'chrome' })
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 })
await ctx.addInitScript(() => localStorage.setItem('party.access_token', 'shot-token'))
const page = await ctx.newPage()

await page.route('http://127.0.0.1:5666/api/**', (r) => r.fulfill({ status: 401, contentType: 'application/json', body: '{"code":40101,"message":"x","data":null,"trace_id":"x"}' }))
await page.route('**/api/auth/me', (r) => r.fulfill(ok(USER)))
await page.route('**/api/auth/codes', (r) => r.fulfill(ok(PERMISSIONS)))
await page.route('**/api/qa', async (r) => {
  await new Promise((res) => setTimeout(res, 900)) // 停留久一点以截到骨架屏
  return r.fulfill(ok(QA_RESPONSE))
})

await page.goto(`${BASE}/ask`, { waitUntil: 'networkidle' })

await page.fill('#question', '入党积极分子培养考察期最短是多长时间')
await page.click('button[type="submit"]')

// 骨架屏
await page.waitForTimeout(350)
await page.screenshot({ path: `${OUT}/08-ask-loading.png`, fullPage: false })

// 回答落地
await page.waitForSelector('.ref', { timeout: 8000 })
await page.waitForTimeout(500)
await page.screenshot({ path: `${OUT}/09-ask-answer.png`, fullPage: true })

// 点击角标跳转引用
await page.click('.ref >> nth=0')
await page.waitForTimeout(600)
const activeCards = await page.locator('.aside-card__cite.is-active').count()
console.log(`citation highlight after click: ${activeCards}`)

// 复制按钮反馈
await page.click('text=复制全文')
await page.waitForTimeout(200)
const copyLabel = await page.locator('.answer__head button').textContent()
console.log(`copy button after click: ${copyLabel?.trim()}`)

await browser.close()
console.log('done')
