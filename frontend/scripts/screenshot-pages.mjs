// 带接口拦截的页面截图：伪造后端响应，验证各主界面在数据就绪时的真实版面。
// 运行：node screenshot-pages.mjs <输出目录>
import { chromium } from 'playwright'

const BASE = 'http://127.0.0.1:5666'
const OUT = process.argv[2] || 'shots'

/** 构造标准包裹体 */
function ok(data) {
  return { status: 200, contentType: 'application/json', body: JSON.stringify({ code: 0, message: 'success', data, trace_id: 'shot-trace-0001' }) }
}

const USER = {
  id: 'u-001',
  username: 'organizer_wang',
  name: '王砚秋',
  role: 'organizer',
  tenant_id: 'tenant-main',
  org_unit_id: 'org-jisuanji',
  email: 'w***@example.edu.cn',
  phone: '138****0000',
}

const PERMISSIONS = ['qa.ask', 'knowledge.query', 'knowledge.manage', 'member.query', 'member.stage_transition']

/** 问答接口：返回一份与真实结构一致的回答 + 引用 */
const QA_RESPONSE = {
  answer:
    '入党积极分子确定后，党组织应当指定一至两名正式党员作为培养联系人，对其进行培养教育和考察。[1]\n\n' +
    '培养教育考察期一般不少于一年。期间，入党积极分子应当定期向党组织汇报思想，党组织每半年至少对其进行一次考察并形成考察记录。[1][2]\n\n' +
    '确定为发展对象，应当经支部委员会讨论并听取党小组和培养联系人的意见，同时进行政治审查。[2]',
  citations: [
    {
      title: '中国共产党发展党员工作细则',
      issuer: '中共中央办公厅',
      doc_number: '中办发〔2014〕34号',
      article: '第九条',
      content:
        '党组织应当指定一至两名正式党员作为入党积极分子的培养联系人。培养联系人的主要任务是：向入党积极分子介绍党的基本知识，了解其思想、工作、学习情况，及时向党组织反映，并对其进行培养教育和考察。',
      score: 0.87,
    },
    {
      title: '中国共产党发展党员工作细则',
      issuer: '中共中央办公厅',
      doc_number: '中办发〔2014〕34号',
      article: '第十六条',
      content:
        '党组织每半年对入党积极分子进行一次考察。基层党支部每年对入党积极分子队伍状况作一次分析，掌握其成熟程度，把经过一年以上培养教育和考察、基本具备党员条件的入党积极分子，列为发展对象。',
      score: 0.74,
    },
    {
      title: '关于加强高校学生党员教育管理的实施意见',
      issuer: '中共某某大学委员会组织部',
      doc_number: '校党组〔2023〕15号',
      article: null,
      content:
        '各院系党组织应当结合学生实际，健全入党积极分子培养考察档案，做到一人一档、动态更新，考察记录须由培养联系人和支部书记共同签字确认。',
      score: 0.43,
    },
  ],
  retrieved_count: 20,
  used_count: 3,
  has_sufficient_evidence: true,
}

const routes = [
  { url: '**/api/auth/me', body: USER },
  { url: '**/api/auth/codes', body: PERMISSIONS },
  { url: '**/api/user/info', body: USER },
  { url: '**/api/qa', body: QA_RESPONSE },
]

const pages = [
  { name: '03-ask', url: '/ask', w: 1440, h: 900 },
  { name: '04-knowledge', url: '/knowledge', w: 1440, h: 900 },
  { name: '05-members', url: '/members', w: 1440, h: 900 },
  { name: '06-system', url: '/system', w: 1440, h: 900 },
  { name: '07-ask-mobile', url: '/ask', w: 390, h: 844 },
]

const browser = await chromium.launch({ channel: 'chrome' })
const consoleErrors = []

for (const p of pages) {
  const ctx = await browser.newContext({ viewport: { width: p.w, height: p.h }, deviceScaleFactor: 2 })
  // 在任何页面脚本执行前注入令牌，避免与路由守卫竞争
  await ctx.addInitScript(() => localStorage.setItem('party.access_token', 'shot-token'))
  const page = await ctx.newPage()

  page.on('console', (m) => m.type() === 'error' && consoleErrors.push(`[${p.name}] ${m.text()}`))
  page.on('pageerror', (e) => consoleErrors.push(`[${p.name}] PAGEERROR ${e.message}`))

  // Playwright 后注册的路由优先级更高：先注册兜底 401，再注册具体接口。
  // 注意不能用 **/api/**，否则会拦截 Vite 的 /src/api/*.ts 模块请求。
  await page.route('http://127.0.0.1:5666/api/**', (route) =>
    route.fulfill({ status: 401, contentType: 'application/json', body: JSON.stringify({ code: 40101, message: '未登录', data: null, trace_id: 'shot-401' }) }),
  )
  for (const r of routes) await page.route(r.url, (route) => route.fulfill(ok(r.body)))

  await page.goto(BASE + p.url, { waitUntil: 'networkidle', timeout: 30000 })
  await page.waitForTimeout(800)
  await page.screenshot({ path: `${OUT}/${p.name}.png`, fullPage: true })

  console.log(`${p.name}: title="${await page.title()}" bodyChars=${(await page.textContent('body'))?.length ?? 0}`)
  await ctx.close()
}

await browser.close()
console.log(consoleErrors.length ? `\n--- CONSOLE ERRORS ---\n${consoleErrors.join('\n')}` : '\nNo console errors.')
