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
    allow: ['/ask', '/knowledge', '/members', '/meeting', '/assessment', '/study', '/governance', '/accounts', '/system'],
    deny: ['/my-archive', '/my-materials'],
  },
  {
    username: 'test-reviewer',
    role: 'school_admin',
    allow: ['/ask', '/knowledge', '/members', '/meeting', '/assessment', '/study', '/governance'],
    deny: ['/accounts', '/system', '/my-archive', '/my-materials'],
  },
  {
    username: 'test-dept',
    role: 'department_admin',
    allow: ['/ask', '/knowledge', '/members', '/meeting', '/assessment', '/study', '/governance'],
    deny: ['/accounts', '/system', '/my-archive', '/my-materials'],
  },
  {
    username: 'branch-secretary',
    role: 'branch_secretary',
    allow: ['/ask', '/knowledge', '/members', '/meeting', '/assessment', '/governance'],
    deny: ['/study', '/accounts', '/system', '/my-archive', '/my-materials'],
  },
  {
    username: 'test-organizer',
    role: 'organizer',
    allow: ['/ask', '/knowledge', '/members', '/meeting', '/assessment', '/governance'],
    deny: ['/study', '/accounts', '/system', '/my-archive', '/my-materials'],
  },
  {
    // 党员与申请人必须同权：知识库只读 + 本人档案/材料
    username: 'test-member',
    role: 'member',
    allow: ['/ask', '/knowledge', '/my-archive', '/my-materials'],
    deny: ['/members', '/meeting', '/assessment', '/study', '/governance', '/accounts', '/system'],
  },
  {
    username: 'test-applicant',
    role: 'applicant',
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
        if (rateLimited && attempt < 3) {
          console.log(`[wait] ${spec.username} ${route} 命中接口限流，等待 25s 后复核`)
          await page.waitForTimeout(25000)
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
  } finally {
    await context.close()
  }
}

async function main() {
  const launch = process.env.PARTY_CHROMIUM
    ? { executablePath: process.env.PARTY_CHROMIUM }
    : {}
  const browser = await chromium.launch(launch)
  try {
    for (const spec of EXPECTED) {
      await checkRole(browser, spec)
      // 登录接口有每分钟次数限制（默认 10 次），角色之间留出足够间隔
      await new Promise((r) => setTimeout(r, 9000))
    }
  } finally {
    await browser.close()
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
