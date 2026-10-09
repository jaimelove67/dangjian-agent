// 视觉验证脚本：截取关键页面，用于人工核对版面与主题是否符合设计意图。
// 运行方式：node screenshot.mjs（工作目录放本文件，node_modules 从全局 playwright 解析）
import { chromium } from 'playwright'

const BASE = 'http://127.0.0.1:5666'
const OUT = process.argv[2] || 'shots'

const pages = [
  { name: '01-login', url: '/login', w: 1440, h: 900 },
  { name: '02-login-mobile', url: '/login', w: 390, h: 844 },
]

// 本机未缓存 playwright 匹配版本的 chromium，直接复用系统已装的 Chrome，
// 避免为了截图再下载一份浏览器。
const browser = await chromium.launch({ channel: 'chrome' })
const consoleErrors = []

for (const p of pages) {
  const ctx = await browser.newContext({
    viewport: { width: p.w, height: p.h },
    deviceScaleFactor: 2,
  })
  const page = await ctx.newPage()

  page.on('console', (msg) => {
    if (msg.type() === 'error') consoleErrors.push(`[${p.name}] ${msg.text()}`)
  })
  page.on('pageerror', (err) => consoleErrors.push(`[${p.name}] PAGEERROR ${err.message}`))

  await page.goto(BASE + p.url, { waitUntil: 'networkidle', timeout: 30000 })
  await page.waitForTimeout(700)
  await page.screenshot({ path: `${OUT}/${p.name}.png`, fullPage: true })

  const title = await page.title()
  const bodyLen = (await page.textContent('body'))?.length ?? 0
  console.log(`${p.name}: title="${title}" bodyChars=${bodyLen}`)

  await ctx.close()
}

await browser.close()

if (consoleErrors.length) {
  console.log('\n--- CONSOLE ERRORS ---')
  consoleErrors.forEach((e) => console.log(e))
} else {
  console.log('\nNo console errors.')
}
