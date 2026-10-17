/**
 * 角色 × 路由 界面回归检查（Playwright）。
 *
 * 用途：把「每个角色能看到什么、点到哪里、是否报错」固化成一条可重复执行的检查，
 * 避免改动权限或导航后出现"菜单与真实权限不一致""点进去才 403"这类回归。
 *
 * 前置：后端与前端已启动，且已按运行指南初始化测试数据。
 *
 * 用法（仓库根目录）：
 *   npm --prefix frontend ci                       # 首次
 *   node frontend/scripts/check-roles-ui.mjs
 *
 * 环境变量：
 *   PARTY_BASE_URL   前端地址，默认 http://127.0.0.1:5666
 *   PARTY_PASSWORD   测试账号统一密码，默认 Test123456
 *   PARTY_CHROMIUM   Chromium 可执行文件路径（Playwright 自带浏览器版本不匹配时使用）
 */

import { createRequire } from 'node:module'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const require = createRequire(import.meta.url)
const frontendRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const { chromium } = require(resolve(frontendRoot, 'node_modules', 'playwright'))

const BASE = process.env.PARTY_BASE_URL ?? 'http://127.0.0.1:5666'
const PASSWORD = process.env.PARTY_PASSWORD ?? 'Test123456'

/** 侧栏入口与真实可访问性的期望值；allow 为可见菜单，deny 为应被拦截的路由 */
const EXPECTED = [
  {
    username: 'admin',
    role: 'system_admin',
    managesKnowledge: true,
    opsQuery: true,
    confirmDispatch: true,
    auditQuery: true,
    allow: ['/ask', '/knowledge', '/members', '/meeting', '/assessment', '/study', '/governance', '/accounts', '/system'],
    deny: ['/my-archive', '/my-materials'],
  },
  {
    username: 'test-reviewer',
    role: 'school_admin',
    managesKnowledge: true,
    opsQuery: true,
    confirmDispatch: true,
    auditQuery: true,
    allow: ['/ask', '/knowledge', '/members', '/meeting', '/assessment', '/study', '/governance'],
    deny: ['/accounts', '/system', '/my-archive', '/my-materials'],
  },
  {
    username: 'test-dept',
    role: 'department_admin',
    managesKnowledge: true,
    allow: ['/ask', '/knowledge', '/members', '/meeting', '/assessment', '/study', '/governance'],
    deny: ['/accounts', '/system', '/my-archive', '/my-materials'],
  },
  {
    username: 'branch-secretary',
    role: 'branch_secretary',
    managesKnowledge: false,
    allow: ['/ask', '/knowledge', '/members', '/meeting', '/assessment', '/governance'],
    deny: ['/study', '/accounts', '/system', '/my-archive', '/my-materials'],
  },
  {
    username: 'test-organizer',
    role: 'organizer',
    managesKnowledge: false,
    allow: ['/ask', '/knowledge', '/members', '/meeting', '/assessment', '/governance'],
    deny: ['/study', '/accounts', '/system', '/my-archive', '/my-materials'],
  },
  {
    // 党员与申请人必须同权：知识库只读 + 本人档案/材料
    username: 'test-member',
    role: 'member',
    managesKnowledge: false,
    allow: ['/ask', '/knowledge', '/my-archive', '/my-materials'],
    deny: ['/members', '/meeting', '/assessment', '/study', '/governance', '/accounts', '/system'],
  },
  {
    username: 'test-applicant',
    role: 'applicant',
    managesKnowledge: false,
    allow: ['/ask', '/knowledge', '/my-archive', '/my-materials'],
    deny: ['/members', '/meeting', '/assessment', '/study', '/governance', '/accounts', '/system'],
  },
]

/** 组织角色不应出现的个人页路由；基层角色在 allow 中显式列出 */
const failures = []
const notes = []

function fail(message) {
  failures.push(message)
}

/**
 * 登录。
 *
 * 登录接口按 IP 限流（默认每分钟 10 次），连续跑角色检查很容易踩到 429。
 * 这里读取 /auth/login 的响应码：命中限流就按提示等待后重试，
 * 而不是把 429 误报成"权限/页面"回归。
 */
async function login(page, username) {
  for (let attempt = 1; attempt <= 5; attempt += 1) {
    let status = 0
    const watch = (response) => {
      if (new URL(response.url()).pathname.endsWith('/auth/login')) status = response.status()
    }
    page.on('response', watch)
    await page.goto(`${BASE}/login`, { waitUntil: 'domcontentloaded' })
    await page.waitForSelector('#username', { timeout: 20000 })
    await page.locator('#username').fill(username)
    await page.locator('#password').fill(PASSWORD)
    await page.locator('button[type=submit]').click()
    await page.waitForTimeout(2600)
    page.off('response', watch)

    if (!new URL(page.url()).pathname.includes('login')) return true
    if (status === 429) {
      const waitSeconds = 22
      console.log(`[wait] 登录限流，${waitSeconds}s 后重试 ${username}（第 ${attempt} 次）`)
      await page.waitForTimeout(waitSeconds * 1000)
      continue
    }
    return false
  }
  return false
}

async function settle(page) {
  for (let i = 0; i < 30; i += 1) {
    if (!(await page.locator('.skel-wrap').count())) break
    await page.waitForTimeout(200)
  }
  await page.waitForTimeout(400)
}

async function checkRole(browser, spec) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } })
  const page = await context.newPage()
  const consoleErrors = []
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text().slice(0, 160))
  })
  const guardRedirects = []
  try {
    if (!(await login(page, spec.username))) {
      fail(`${spec.username}: 登录失败（检查账号是否已初始化）`)
      return
    }
    page.on('response', (response) => {
      const path = new URL(response.url()).pathname
      // viewer 自己触发的 4xx 才算问题；健康检查 503 属正常
      if (response.status() >= 400 && !path.endsWith('/health/ready')) {
        guardRedirects.push(`${response.status()} ${path}`)
      }
    })

    const nav = await page.locator('.rail__link').allInnerTexts()
    notes.push(`${spec.username}(${spec.role}) 菜单: ${nav.join(' / ')}`)

    for (const route of [...spec.allow, ...spec.deny]) {
      // 接口限流（默认 120 次/分钟）会让整轮检查误报；命中就等窗口过去再复核一次。
      let attempt = 0
      let settled = false
      while (!settled && attempt < 3) {
        attempt += 1
        guardRedirects.length = 0
        consoleErrors.length = 0
        await page.goto(`${BASE}${route}`, { waitUntil: 'domcontentloaded' })
        await settle(page)
        const rateLimited = [...guardRedirects, ...consoleErrors].some((line) =>
          line.includes('429'),
        )
        // 前端资源加载失败时整个单页应用白屏，路由守卫根本没运行：
        // 此时把"能打开"当成越权是误报（CI 上表现为 ERR_INSUFFICIENT_RESOURCES）。
        // 先等一下重试，仍挂不上再按真实缺陷上报。
        const shellMissing = (await page.locator('main').count()) === 0
        if ((rateLimited || shellMissing) && attempt < 3) {
          const waitSeconds = rateLimited ? 25 : 5
          console.log(
            `[wait] ${spec.username} ${route} ${rateLimited ? '命中接口限流' : '页面未挂载'}，等待 ${waitSeconds}s 后复核`,
          )
          await page.waitForTimeout(waitSeconds * 1000)
          continue
        }
        settled = true
      }

      const path = new URL(page.url()).pathname
      if (path === '/login') {
        fail(`${spec.username}: 检查 ${route} 时会话失效（多为登录限流），该角色结果不完整`)
        return
      }
      const forbidden = await page.locator('.forbidden').count()
      const shouldAllow = spec.allow.includes(route)
      if (shouldAllow) {
        if (forbidden) fail(`${spec.username}: ${route} 期望可访问，实际被拦截（跳到 ${path}）`)
      } else if (!forbidden) {
        fail(`${spec.username}: ${route} 期望被拦截，实际可访问（${path}）`)
      }
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth > window.innerWidth + 1,
      )
      if (overflow) fail(`${spec.username}: ${route} 出现页面级横向溢出`)
      const mainCount = await page.locator('main').count()
      if (mainCount !== 1) {
        fail(`${spec.username}: ${route} 的主内容地标数量为 ${mainCount}（应为 1）`)
      }
      const unique = [...new Set(guardRedirects)]
      if (unique.length) fail(`${spec.username}: ${route} 出现接口错误 ${unique.join(', ')}`)
      if (consoleErrors.length) {
        fail(`${spec.username}: ${route} 控制台报错 ${[...new Set(consoleErrors)].join(' ~ ')}`)
      }
      // 路由之间留出间隔，避免整轮检查把通用接口限流打满
      await page.waitForTimeout(500)
    }

    await checkKnowledgeTools(page, spec)
    await checkGovernanceIdentity(page, spec)
    await checkOperationsTab(page, spec)
    await checkQaRecordsAccess(page, spec)
    await checkMeetingFrequency(page, spec)
    await checkMemberReviews(page, spec)
    await checkMemberTransfers(page, spec)
    await checkRosterOrgFilter(page, spec)
    await checkUpperReports(page, spec)
    await checkMemberSelection(page, spec)
  } finally {
    await context.close()
  }
}

/**
 * 知识库详情面板必须挂载「处理与原件」工具。
 *
 * DocumentTools 曾实现完整但没有任何页面引用，导致后端能下载原件、用户却拿不到，
 * 而接口清单仍显示「已接入」。这里显式断言入口存在，并按权限区分：
 * 只读角色只能刷新状态与下载原件，不应出现元数据修正表单。
 */
async function checkKnowledgeTools(page, spec) {
  if (!spec.allow.includes('/knowledge')) return
  await page.goto(`${BASE}/knowledge`, { waitUntil: 'domcontentloaded' })
  await settle(page)
  const rows = await page.locator('table.table tbody tr').count()
  if (!rows) {
    notes.push(`${spec.username}: 知识库无数据，跳过原件下载入口检查`)
    return
  }
  await page.locator('table.table tbody tr').first().click()
  await page.waitForTimeout(1200)
  if (!(await page.locator('.document-tools').count())) {
    fail(`${spec.username}: 知识库详情面板未挂载「处理与原件」工具（原件下载入口缺失）`)
    return
  }
  const download = page.locator('.document-tools .wb-actions:has(input[type=number]) button')
  if (!(await download.count())) {
    fail(`${spec.username}: 知识库详情面板缺少「下载原件」按钮`)
  }
  const metadataForm = await page.locator('.document-tools details.wb-disclosure').count()
  if (spec.managesKnowledge && !metadataForm) {
    fail(`${spec.username}: 具备 knowledge.manage 却看不到元数据修正表单`)
  }
  if (!spec.managesKnowledge && metadataForm) {
    fail(`${spec.username}: 不具备 knowledge.manage 却出现元数据修正表单`)
  }
  if (await page.locator('.document-tools .state.err').count()) {
    fail(`${spec.username}: 知识库工具区出现错误态`)
  }
}

/**
 * 治理页「组织与账号」的新增入口必须与服务端权限一致。
 *
 * POST /admin/users（开户）与「登记租户」在服务端只允许平台系统管理员，页面却曾按
 * IDENTITY_MANAGE 显示按钮：学校管理员点下去必然 403「权限不足」，看得到、点不通。
 * 这里按角色断言入口显隐，避免这类"死入口"再回来。
 */
async function checkGovernanceIdentity(page, spec) {
  if (!spec.allow.includes('/governance')) return
  await page.goto(`${BASE}/governance`, { waitUntil: 'domcontentloaded' })
  await settle(page)
  const identityTab = page.getByRole('tab', { name: '组织与账号' })
  if (!(await identityTab.count())) {
    notes.push(`${spec.username}: 治理页无「组织与账号」标签，跳过身份入口检查`)
    return
  }
  await identityTab.first().click()
  await page.waitForTimeout(1000)
  const createUser = await page.getByRole('button', { name: '新增用户' }).count()
  const registerTenant = await page.getByRole('button', { name: '登记租户' }).count()
  if (spec.role === 'system_admin') {
    if (!(createUser && registerTenant)) {
      fail(`${spec.username}: 平台系统管理员应看到「新增用户」与「登记租户」入口`)
    }
  } else if (createUser || registerTenant) {
    fail(`${spec.username}: 非平台系统管理员却出现「新增用户/登记租户」入口（点击必然 403）`)
  }
}

/**
 * 「运行审计」页必须能看见通知渠道与投递台账，以及审计条件检索与对账包导出。
 *
 * 渠道抽象层只放在后端，运维就没有地方确认“配了哪些渠道、哪个渠道还没凭据、
 * 最近一次投递为什么失败”；审计导出同理——只开放后端导出、界面没有入口，
 * 运维照样只能手工拼 SQL。这里一次断言具备 ops.query 的角色看得到这些入口，
 * 不具备的角色连标签都不该出现——运行审计不是普通业务页。
 */
async function checkOperationsTab(page, spec) {
  if (!spec.allow.includes('/governance')) return
  await page.goto(`${BASE}/governance`, { waitUntil: 'domcontentloaded' })
  await settle(page)
  const opsTab = page.getByRole('tab', { name: '运行审计' })
  if (!spec.opsQuery) {
    if (await opsTab.count()) {
      fail(`${spec.username}: 不具备 ops.query 却出现「运行审计」标签`)
    } else {
      notes.push(`${spec.username}: 无「运行审计」标签（不具备 ops.query），跳过运行审计检查`)
    }
    return
  }
  if (!(await opsTab.count())) {
    fail(`${spec.username}: 具备 ops.query 却看不到「运行审计」标签`)
    return
  }
  await opsTab.first().click()
  await page.waitForTimeout(2500)
  if (!(await page.getByRole('heading', { name: '通知渠道与投递台账' }).count())) {
    fail(`${spec.username}: 运行审计页缺少「通知渠道与投递台账」区块`)
    return
  }
  if (!(await page.getByRole('cell', { name: 'inapp', exact: true }).count())) {
    fail(`${spec.username}: 通知渠道表未列出出厂登记的站内渠道 inapp`)
  }
  const selfTest = await page.getByRole('button', { name: /发起渠道自检|投递中/ }).count()
  if (spec.confirmDispatch && !selfTest) {
    fail(`${spec.username}: 具备 config.manage 却看不到「发起渠道自检」按钮`)
  }
  if (!spec.confirmDispatch && selfTest) {
    fail(`${spec.username}: 不具备 config.manage 却能看到「发起渠道自检」按钮`)
  }
  for (const label of ['对象类型', '数据级别', '开始时间（北京时间）']) {
    if (!(await page.getByText(label, { exact: true }).count())) {
      fail(`${spec.username}: 审计查询缺少「${label}」筛选`)
    }
  }
  if (!(await page.getByRole('button', { name: /导出当前筛选/ }).count())) {
    fail(`${spec.username}: 审计查询缺少对账包导出入口`)
  }
  if (!(await page.getByText('当前口径：').count())) {
    fail(`${spec.username}: 审计查询未渲染可核对的口径说明（列表未查到或接口报错）`)
  }
  // 运行日志（T-SYS-06E）：任务执行与定时扫描的经过要能查，不能只有"任务现在什么状态"
  if (!(await page.getByRole('heading', { name: '运行日志' }).count())) {
    fail(`${spec.username}: 运行审计页缺少「运行日志」区块`)
  }
  if (!(await page.getByRole('button', { name: '查询运行日志' }).count())) {
    fail(`${spec.username}: 运行日志缺少查询入口`)
  }
  if (!(await page.getByText('任务类型', { exact: true }).count())) {
    fail(`${spec.username}: 运行日志缺少任务类型筛选`)
  }
  if (!(await page.getByText(/失败只记错误类型与状态/).count())) {
    fail(`${spec.username}: 运行日志未说明失败记录口径（不记供应商错误正文）`)
  }
  // 版本留痕（T-SEC-11）：提示词版本、工作流契约版本、知识库版本三块都要能查。
  // 只答"现在用的是哪个版本"不够——答不了"这条答案是哪个版本产出的"。
  if (!(await page.getByRole('heading', { name: '版本留痕' }).count())) {
    fail(`${spec.username}: 运行审计页缺少「版本留痕」区块`)
  }
  if (!(await page.getByText(/当前生效：/).count())) {
    fail(`${spec.username}: 版本留痕未给出当前生效的提示词版本`)
  }
  if (!(await page.getByRole('heading', { name: '工作流契约版本' }).count())) {
    fail(`${spec.username}: 版本留痕缺少工作流契约版本清单`)
  }
  if (!(await page.getByRole('heading', { name: '知识库版本' }).count())) {
    fail(`${spec.username}: 版本留痕缺少知识库版本区块`)
  }
  if (!(await page.getByText(/不另起一张登记表/).count())) {
    fail(`${spec.username}: 版本留痕未说明三块来源口径（凭空另立登记表会与事实对不上）`)
  }
  // 跨租户检索入口只对平台系统管理员出现：其他角色显示了就是必然 403 的假入口
  const tenantField = await page.getByText('租户编号（跨租户）', { exact: true }).count()
  if (spec.role === 'system_admin' && !tenantField) {
    fail(`${spec.username}: 平台系统管理员看不到跨租户检索入口`)
  }
  if (spec.role !== 'system_admin' && tenantField) {
    fail(`${spec.username}: 非平台系统管理员却能看到跨租户检索入口`)
  }
  // 异常活动提示也用 wb-error（无 role），这里按真正的错误态（role=alert）判断
  if (await page.getByRole('alert').count()) {
    fail(`${spec.username}: 运行审计页出现错误态`)
  }
}

/**
 * 「问答记录」集中查看必须与 admin.audit 一致。
 *
 * 本人档案口径（/qa/sessions）人人都有，集中查看却是治理与审计能力：不具备该权限的角色
 * 连标签都不该出现；具备的角色要能看到按条件查询与导出入口，否则学校复核时无从查证。
 */
async function checkQaRecordsAccess(page, spec) {
  if (!spec.allow.includes('/governance')) return
  await page.goto(`${BASE}/governance`, { waitUntil: 'domcontentloaded' })
  await settle(page)
  const tab = page.getByRole('tab', { name: '问答记录' })
  if (!spec.auditQuery) {
    if (await tab.count()) {
      fail(`${spec.username}: 不具备 admin.audit 却出现「问答记录」标签`)
    } else {
      notes.push(`${spec.username}: 无「问答记录」标签（不具备 admin.audit），跳过集中查看检查`)
    }
    return
  }
  if (!(await tab.count())) {
    fail(`${spec.username}: 具备 admin.audit 却看不到「问答记录」标签`)
    return
  }
  await tab.first().click()
  await page.waitForTimeout(2000)
  if (!(await page.getByRole('button', { name: '查询问答记录' }).count())) {
    fail(`${spec.username}: 问答记录页缺少按条件查询入口`)
  }
  if (!(await page.getByRole('button', { name: /导出当前筛选|导出中/ }).count())) {
    fail(`${spec.username}: 问答记录页缺少筛选结果导出入口`)
  }
  // 版本留痕（T-SEC-11）：列表要能看出"这条答案由哪个版本产出"，否则可追溯只做了一半。
  // 当前范围没有记录时列表根本不渲染，这种租户按空状态断言，别把"没数据"误报成"缺列"。
  if (await page.locator('.wb-table').count()) {
    if (!(await page.getByText('版本', { exact: true }).count())) {
      fail(`${spec.username}: 问答记录列表缺少「版本」列`)
    }
  } else if (!(await page.getByText('当前范围没有问答记录').count())) {
    fail(`${spec.username}: 问答记录页既无列表也无空状态说明`)
  }
  if (!(await page.getByText(/不按当前配置倒推/).count())) {
    fail(`${spec.username}: 问答记录未说明历史记录不按当前版本倒推`)
  }
  if (await page.locator('.wb-error').count()) {
    fail(`${spec.username}: 问答记录页出现错误态`)
  }
}

/**
 * 「年度统计」必须挂载组织生活频次合规提醒。
 *
 * T-ORG-10 的落点是"按制度频次生成提醒"：接口有了、页面没有，支部书记还是得靠脑子记
 * 本季度党课讲没讲。这里同时钉住三件事：周期要求（不是只有年度数字）、"已召开没审"
 * 与"没开"的区分、以及缺口独立成区（否则上季度没达标会被当成再补一次就行）。
 */
async function checkMeetingFrequency(page, spec) {
  if (!spec.allow.includes('/meeting')) return
  const apiErrors = []
  const listener = (response) => {
    const path = new URL(response.url()).pathname
    if (response.status() >= 400 && path.endsWith('/meeting/frequency')) {
      apiErrors.push(`${response.status()} ${path}`)
    }
  }
  page.on('response', listener)
  try {
    await page.goto(`${BASE}/meeting`, { waitUntil: 'domcontentloaded' })
    await settle(page)
    const statsTab = page.getByRole('tab', { name: '年度统计' })
    if (!(await statsTab.count())) {
      notes.push(`${spec.username}: 组织生活页没有「年度统计」标签，跳过频次提醒检查`)
      return
    }
    await statsTab.first().click()
    await page.waitForTimeout(1500)
    const panel = page.locator('.meeting-frequency')
    if (!(await panel.count())) {
      fail(`${spec.username}: 年度统计未挂载「组织生活频次合规」提醒（提醒只在接口里，用户看不到）`)
      return
    }
    const text = await panel.innerText()
    if (!/本周期各支部组织生活均已达标|本周期需处理|没有可提示的支部/.test(text)) {
      fail(`${spec.username}: 频次提醒区块没有给出本周期结论`)
    }
    if (!/至少 1 次|不设固定频次/.test(text)) {
      fail(`${spec.username}: 频次提醒区块没有显示周期要求（只剩年度数字）`)
    }
    if (!/人工审核通过/.test(text)) {
      fail(`${spec.username}: 频次提醒缺少"完成认定以人工审核通过为准"的口径`)
    }
    if (apiErrors.length) fail(`${spec.username}: 频次接口报错 ${[...new Set(apiErrors)].join(', ')}`)
  } finally {
    page.off('response', listener)
  }
}

/**
 * 「民主评议党员」工作区必须真的挂载并给出年度结论。
 *
 * T-ORG-11 要求"可按年度发起、记录流程与意见、人工审核与留痕"：接口有了、页面没有，
 * 支部书记还是不知道谁没评、缺什么、能不能送审。这里钉住：年度工作区能打开、名单与
 * 进度（含"未发起"）给得出来、以及"等次由人工审定、不按票数排名"的口径在页面上。
 */
async function checkMemberReviews(page, spec) {
  if (!spec.allow.includes('/meeting')) return
  const apiErrors = []
  const listener = (response) => {
    const path = new URL(response.url()).pathname
    if (response.status() >= 400 && path.endsWith('/meeting/member-reviews/workspace')) {
      apiErrors.push(`${response.status()} ${path}`)
    }
  }
  page.on('response', listener)
  try {
    await page.goto(`${BASE}/meeting`, { waitUntil: 'domcontentloaded' })
    await settle(page)
    const reviewsTab = page.getByRole('tab', { name: '民主评议党员' })
    if (!(await reviewsTab.count())) {
      fail(`${spec.username}: 组织生活页没有「民主评议党员」工作区（功能只在接口里，用户看不到）`)
      return
    }
    await reviewsTab.first().click()
    await page.waitForTimeout(1500)
    const panel = page.locator('.review')
    if (!(await panel.count())) {
      fail(`${spec.username}: 「民主评议党员」没有挂载工作区面板`)
      return
    }
    const text = await panel.innerText()
    if (!/年度民主评议党员/.test(text)) fail(`${spec.username}: 民主评议没有给出年度工作区标题`)
    if (!/应评议党员/.test(text)) fail(`${spec.username}: 民主评议没有给出应评议名单口径`)
    if (!/未发起|已通过审核/.test(text)) fail(`${spec.username}: 民主评议没有给出进度（谁还没评）`)
    if (!/系统不按票数排名、不自动定等次/.test(text)) {
      fail(`${spec.username}: 民主评议缺少"等次由人工审定"的口径`)
    }
    if (!/优秀等次比例上限/.test(text)) {
      fail(`${spec.username}: 民主评议缺少优秀比例与不合格处置的边界说明`)
    }
    if (apiErrors.length) {
      fail(`${spec.username}: 民主评议接口报错 ${[...new Set(apiErrors)].join(', ')}`)
    }
  } finally {
    page.off('response', listener)
  }
}

/**
 * 「组织关系接转」工作区必须真的挂载，且写入入口与权限一致（T-MEM-14）。
 *
 * 接转是独立台账：接口有了、页面没有，支部书记还是得线下记介绍信；反过来，若给
 * 没有 member.stage_transition 的角色显示「登记转出/登记转入」，就是必然 403 的假入口。
 * 这里钉住三件事：工作区挂载并给出「开了介绍信不等于转出完成」的口径、写入入口与
 * 权限一致、以及接转接口没有报错（含迁移未执行导致的 500）。
 */
async function checkMemberTransfers(page, spec) {
  if (!spec.allow.includes('/members')) return
  const apiErrors = []
  const listener = (response) => {
    const path = new URL(response.url()).pathname
    if (response.status() >= 400 && path.includes('/member-full/transfers')) {
      apiErrors.push(`${response.status()} ${path}`)
    }
  }
  page.on('response', listener)
  try {
    await page.goto(`${BASE}/members`, { waitUntil: 'domcontentloaded' })
    await settle(page)
    // 名册筛选在默认的「人员档案」工作区，先断言它，再切到接转工作区
    const includeTransferred = page.getByRole('checkbox', { name: '含组织关系已转出人员' })
    await includeTransferred.waitFor({ timeout: 15000 }).catch(() => {})
    if (!(await includeTransferred.count())) {
      fail(`${spec.username}: 名册没有「含组织关系已转出人员」筛选（已转出人员无从核对）`)
    }
    const transfersTab = page.getByRole('tab', { name: '组织关系接转' })
    await transfersTab.first().waitFor({ timeout: 15000 }).catch(() => {})
    if (!(await transfersTab.count())) {
      fail(`${spec.username}: 人员档案页没有「组织关系接转」工作区（功能只在接口里，用户看不到）`)
      return
    }
    await transfersTab.first().click()
    await page.waitForTimeout(1500)
    const panel = page.locator('.tr-summary')
    await panel.waitFor({ timeout: 15000 }).catch(() => {})
    if (!(await panel.count())) {
      fail(`${spec.username}: 「组织关系接转」没有挂载台账（转出待回执/转入待核对汇总缺失）`)
      return
    }
    const text = await page.locator('main').innerText()
    if (!/转出开了介绍信不等于转出完成/.test(text)) {
      fail(`${spec.username}: 接转未说明"开了介绍信不等于转出完成"的口径`)
    }
    if (!/已超过有效期|转出待回执/.test(text)) {
      fail(`${spec.username}: 接转台账没有给出汇总口径`)
    }
    // 能看到 /members 的角色都具备 member.stage_transition，写入入口就该在
    for (const entry of ['登记转出', '登记转入']) {
      if (!(await page.getByRole('button', { name: entry, exact: true }).count())) {
        fail(`${spec.username}: 具备 member.stage_transition 却看不到「${entry}」入口`)
      }
    }
    if (apiErrors.length) {
      fail(`${spec.username}: 接转接口报错 ${[...new Set(apiErrors)].join(', ')}`)
    }
    if (await page.getByRole('alert').count()) {
      fail(`${spec.username}: 接转工作区出现错误态`)
    }
  } finally {
    page.off('response', listener)
  }
}

/**
 * 名册要能按支部看，名册统计要真的挂在页面上（T-MEM-02）。
 *
 * 这一屏最容易出现两种"假功能"：① 只按年度 / 批次筛，能看到多个支部的账号只能把几个
 * 支部的人混在一张表里翻；② `/member-full/stats` 接口早就实现了，但页面从不引用，
 * 用户拿不到名册统计。这里钉住：支部筛选挂载、选了支部后名册列表与名册统计带**同一个**
 * org_unit_id（只看列表筛、统计还是整个院系就是假筛选）、统计口径文案可见且接口不报错。
 */
async function checkRosterOrgFilter(page, spec) {
  if (!spec.allow.includes('/members')) return
  const apiErrors = []
  const calls = []
  const listener = (response) => {
    const url = new URL(response.url())
    if (!/\/member\/roster$|\/member-full\/stats$/.test(url.pathname)) return
    calls.push({ path: url.pathname, org: url.searchParams.get('org_unit_id') })
    if (response.status() >= 400) apiErrors.push(`${response.status()} ${url.pathname}`)
  }
  page.on('response', listener)
  try {
    await page.goto(`${BASE}/members`, { waitUntil: 'domcontentloaded' })
    await settle(page)
    const select = page.locator('#roster-org')
    await select.waitFor({ timeout: 15000 }).catch(() => {})
    if (!(await select.count())) {
      fail(`${spec.username}: 名册没有支部筛选（能看到多个支部时只能混在一张表里翻）`)
      return
    }
    const statsLine = page.getByText('当前筛选共')
    await statsLine.first().waitFor({ timeout: 8000 }).catch(() => {})
    if (!(await statsLine.count())) {
      fail(`${spec.username}: 名册统计没有挂到页面上（接口有、用户看不到）`)
    }
    const options = await select.locator('option').count()
    if (options > 1) {
      const value = await select.locator('option').nth(1).getAttribute('value')
      calls.length = 0
      await select.selectOption(value)
      await page.waitForTimeout(1500)
      if (!calls.some((call) => call.path.endsWith('/member/roster') && call.org === value)) {
        fail(`${spec.username}: 选了支部但名册请求没带 org_unit_id（筛了等于没筛）`)
      }
      if (!calls.some((call) => call.path.endsWith('/member-full/stats') && call.org === value)) {
        fail(`${spec.username}: 名册统计没有跟着支部筛选走（列表按支部、统计整个院系）`)
      }
      await select.selectOption('')
      await page.waitForTimeout(1000)
    }
    if (apiErrors.length) {
      fail(`${spec.username}: 名册/名册统计接口报错 ${[...new Set(apiErrors)].join(', ')}`)
    }
    if (await page.getByRole('alert').count()) {
      fail(`${spec.username}: 名册页出现错误态`)
    }
  } finally {
    page.off('response', listener)
  }
}

/**
 * 「上级审批备案」工作区必须真的挂载，并把边界写开（T-MEM-11）。
 *
 * 这一屏最容易变成反人类设计的做法，是让支部自己点一个"审批通过"——系统里没有上级党组织
 * 的登录身份，审批是上级党组织的权限。这里钉住四件事：工作区挂载并给出"不代替上级审批 / 
 * 回填不改阶段 / 备案类时限按上级党委规定"三条口径、没有"系统自己审批"的假入口、
 * 写入与导出入口在、且接口没有报错（含迁移未执行导致的 500）。
 */
async function checkUpperReports(page, spec) {
  if (!spec.allow.includes('/members')) return
  const apiErrors = []
  const listener = (response) => {
    const path = new URL(response.url()).pathname
    if (response.status() >= 400 && path.includes('/member-full/upper-reports')) {
      apiErrors.push(`${response.status()} ${path}`)
    }
  }
  page.on('response', listener)
  try {
    await page.goto(`${BASE}/members`, { waitUntil: 'domcontentloaded' })
    await settle(page)
    const tab = page.getByRole('tab', { name: '上级审批备案' })
    await tab.first().waitFor({ timeout: 15000 }).catch(() => {})
    if (!(await tab.count())) {
      fail(`${spec.username}: 人员档案页没有「上级审批备案」工作区（功能只在接口里，用户看不到）`)
      return
    }
    await tab.first().click()
    await page.waitForTimeout(1500)
    const panel = page.locator('.up-summary')
    await panel.waitFor({ timeout: 15000 }).catch(() => {})
    if (!(await panel.count())) {
      fail(`${spec.username}: 「上级审批备案」没有挂载台账（已报送待批复 / 超期汇总缺失）`)
      return
    }
    const text = await page.locator('main').innerText()
    if (!/系统不代替上级党组织审批/.test(text)) {
      fail(`${spec.username}: 上级审批备案未说明"系统不代替上级党组织审批"的边界`)
    }
    if (!/不改动党员的阶段/.test(text)) {
      fail(`${spec.username}: 上级审批备案未说明回填批复不改动党员阶段`)
    }
    if (!/备案类时限按上级党委规定/.test(text)) {
      fail(`${spec.username}: 上级审批备案没有把备案类时限交给上级党委规定（容易凭空编一个期限）`)
    }
    // 没有"由系统审批"的假入口：审批是上级党组织的权限
    if (await page.getByRole('button', { name: /系统审批|审批通过|批准入党/ }).count()) {
      fail(`${spec.username}: 上级审批备案出现"系统自己审批"的入口`)
    }
    // 能看到 /members 的角色都具备 member.stage_transition，写入入口就该在
    for (const entry of ['登记报送', '导出台账']) {
      if (!(await page.getByRole('button', { name: entry, exact: true }).count())) {
        fail(`${spec.username}: 看不到「${entry}」入口`)
      }
    }
    if (apiErrors.length) {
      fail(`${spec.username}: 上级审批备案接口报错 ${[...new Set(apiErrors)].join(', ')}`)
    }
    if (await page.getByRole('alert').count()) {
      fail(`${spec.username}: 上级审批备案工作区出现错误态`)
    }
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth > window.innerWidth + 1,
    )
    if (overflow) fail(`${spec.username}: 上级审批备案工作区出现页面级横向溢出`)
  } finally {
    page.off('response', listener)
  }
}

/**
 * 「选优结论（拟推荐名单）+ 团组织推优」必须真的挂载，且不出现假入口（T-MEM-13、T-MEM-06）。
 *
 * 选优这一屏最容易变成反人类设计的地方有三种：**一是"按票数自动生成名单"**（把组织结论
 * 交给系统算）、**二是"谁登记谁点通过"**（自审没拦住）、**三是"用年龄规则编数据"**
 * （名册里根本没有出生年月，却做一个 28 周岁校验，只会逼人编生日）。这里钉住：面板挂载
 * 并给出三条口径、没有"系统自动生成名单"的入口、没有年龄判定字段，且接口不报错
 * （含迁移未执行导致的 500）。
 */
async function checkMemberSelection(page, spec) {
  if (!spec.allow.includes('/members')) return
  const apiErrors = []
  const listener = (response) => {
    const path = new URL(response.url()).pathname
    if (response.status() >= 400 && path.includes('/member-full/selections')) {
      apiErrors.push(`${response.status()} ${path}`)
    }
  }
  page.on('response', listener)
  try {
    await page.goto(`${BASE}/members`, { waitUntil: 'domcontentloaded' })
    await settle(page)
    const votesTab = page.getByRole('tab', { name: '多轮选优' })
    await votesTab.first().waitFor({ timeout: 15000 }).catch(() => {})
    if (!(await votesTab.count())) {
      fail(`${spec.username}: 人员档案页没有「多轮选优」工作区`)
      return
    }
    await votesTab.first().click()
    await page.waitForTimeout(1200)
    // 结论面板按批次归集：先选一个真实存在的年度批次，面板才会挂载
    const batch = page.getByLabel('本年度批次')
    await batch.waitFor({ timeout: 15000 }).catch(() => {})
    if (!(await batch.count())) {
      fail(`${spec.username}: 「多轮选优」没有批次选择器（选优结论按批次与轮次归集）`)
      return
    }
    const options = await (async () => {
      // 批次列表是异步拉的：第一个角色（开发服务器刚起）可能还没回来，
      // 这里等一会儿而不是把"还没加载完"当成"没有批次"。
      for (let attempt = 0; attempt < 8; attempt += 1) {
        const values = await batch
          .locator('option')
          .evaluateAll((nodes) =>
            nodes.map((node) => node.getAttribute('value')).filter((value) => value),
          )
        if (values.length) return values
        await page.waitForTimeout(1000)
      }
      return []
    })()
    if (!options.length) {
      notes.push(`${spec.username}: 当前没有年度批次，选优结论面板未参与本次检查`)
      return
    }
    await batch.selectOption(options[0])
    await page.waitForTimeout(1500)
    const panel = page.locator('.sp-panel')
    await panel.first().waitFor({ timeout: 15000 }).catch(() => {})
    if (!(await panel.count())) {
      fail(`${spec.username}: 「多轮选优」没有挂载选优结论 / 团组织推优面板（功能只在接口里，用户看不到）`)
      return
    }
    const text = await panel.first().innerText()
    if (!/不按票数自动排序、不自动产生名单、不自动定等次/.test(text)) {
      fail(`${spec.username}: 选优结论未说明"系统不按票数自动出结论"的边界`)
    }
    if (!/第二位组织人员审核/.test(text)) {
      fail(`${spec.username}: 选优结论未说明必须由第二位组织人员审核（不许自审）`)
    }
    if (!/系统不判断年龄|系统判不了 28 周岁/.test(text)) {
      fail(`${spec.username}: 团组织推优未把年龄判定交回组织核对`)
    }
    if (await page.getByRole('button', { name: /自动生成|一键生成|系统推荐|按票数/ }).count()) {
      fail(`${spec.username}: 选优结论出现"系统自动生成名单"的入口`)
    }
    if (await page.getByRole('checkbox', { name: /28 周岁|出生年月|年龄/ }).count()) {
      fail(`${spec.username}: 团组织推优出现年龄判定字段（名册里没有出生年月，系统判不了年龄）`)
    }
    if (apiErrors.length) {
      fail(`${spec.username}: 选优结论接口报错 ${[...new Set(apiErrors)].join(', ')}`)
    }
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth > window.innerWidth + 1,
    )
    if (overflow) fail(`${spec.username}: 选优结论面板出现页面级横向溢出`)
  } finally {
    page.off('response', listener)
  }
}

async function main() {
  const launch = process.env.PARTY_CHROMIUM
    ? { executablePath: process.env.PARTY_CHROMIUM }
    : {}
  // 每个角色单独起一个浏览器进程：7 个角色共用同一浏览器时，前面的上下文
  // 会累积内存与连接，后段角色容易整体白屏（ERR_INSUFFICIENT_RESOURCES），
  // 把环境问题误报成权限回归。重启进程的代价远低于一次误判。
  for (const spec of EXPECTED) {
    const browser = await chromium.launch(launch)
    try {
      await checkRole(browser, spec)
    } finally {
      await browser.close()
    }
    // 登录接口有每分钟次数限制（默认 10 次），角色之间留出足够间隔
    await new Promise((r) => setTimeout(r, 9000))
  }

  for (const note of notes) console.log(`[info] ${note}`)
  if (failures.length) {
    console.log('\n[FAIL] 角色界面回归未通过：')
    for (const item of failures) console.log(`  - ${item}`)
    process.exitCode = 1
    return
  }
  console.log(`\n[ok] ${EXPECTED.length} 个角色的菜单与路由访问性检查通过。`)
}

await main()
