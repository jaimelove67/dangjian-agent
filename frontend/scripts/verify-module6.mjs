// 治理界面交互验收。全部API在浏览器内拦截，样例不生成正式学校配置或调用模型。
import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { spawn } from 'node:child_process'
import { chromium } from 'playwright'
const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const index = process.argv.indexOf('--out')
const OUT = resolve(index >= 0 ? process.argv[index + 1] : resolve(ROOT, '../tmp/module6-ui'))
const BASE = 'http://127.0.0.1:5689'
await mkdir(OUT, { recursive: true })
let server
if (process.argv.includes('--serve')) {
  server = spawn(process.execPath, [resolve(ROOT, 'node_modules/vite/bin/vite.js'),
    'preview', '--host', '127.0.0.1', '--port', '5689', '--strictPort'], { cwd: ROOT, stdio: 'ignore' })
  for (let attempt = 0; attempt < 80; attempt++) {
    if (server.exitCode !== null) throw new Error('预览进程未启动')
    try { if ((await fetch(BASE)).ok) break } catch {}
    await new Promise(resolve => setTimeout(resolve, 100))
  }
}
const permissions = ['admin.identity', 'admin.config', 'admin.review',
  'admin.ops', 'admin.audit', 'knowledge.manage', 'member.query', 'member.scoring']
const approval = { status: 'pending', evidence: '' }
const values = { registration: {...approval}, organization_approval: {...approval},
  it_approval: {...approval}, secrecy_approval: {...approval}, pilot_scope: '',
  model_policy: {external_enabled:false, internal_approved:false, local_sensitive_enabled:false,
    allowed_hosts:[], local_hosts:[], evidence:''}, model_routes:{}, scoring_weights:{},
  prompt_versions:{}, retention:{file_days:365, audit_days:365, physical_purge:'disabled', evidence:''} }
const config = {version:0, values, inherited:{}, model_catalog:[],
  admission:{status:'pending', pending:['registration','organization_approval','it_approval',
    'secrecy_approval','pilot_scope'], electronic_archive:'pending'},
  archive_policy:{enabled:false, revision:0}}
const orgs = [
  {id:'root', name:'界面验收样例根组织', org_type:'school', parent_id:null, path:'/root', is_active:true},
  {id:'branch', name:'界面验收样例支部', org_type:'branch', parent_id:'root',
    path:'/root/branch', is_active:true},
]
const review = {id:'review', source_kind:'score', source_id:'profile', source_version:'a'.repeat(64),
  status:'pending', effective_status:'pending', stale:false, submitted_by:'other', reviewed_by:null,
  reviewed_at:null, opinion:null, created_at:'2026-10-11T08:00:00',
  snapshot:{weighted_score:null, notice:'界面验收材料，不作为组织认定依据。'}}
const mutations = [], checks = [], errors = []
let browser
try {
  browser = await chromium.launch({channel:process.env.MODULE6_BROWSER_CHANNEL || undefined})
} catch (error) {
  server?.kill()
  throw error
}
async function page(width=1440, readonly=false) {
  const ctx = await browser.newContext({viewport:{width,height:width<768?844:1000}})
  await ctx.addInitScript(()=>localStorage.setItem('party.access_token','fixture-token'))
  let stale = false, self = false
  await ctx.route(BASE+'/api/**', async route => {
    const req=route.request(), url=new URL(req.url()), path=url.pathname.replace(/^\/api/,'')
    const method=req.method(), body=req.postDataJSON()
    assert.equal(req.headers().authorization,'Bearer fixture-token')
    assert.ok(!url.searchParams.has('access_token'))
    if (method!=='GET') mutations.push({path,method,body})
    let data
    if (path==='/auth/me') data={id:'viewer',username:'ui-fixture',name:'界面验收账号',
      role:'school_admin',tenant_id:'school',org_unit_id:'root'}
    else if (path==='/auth/codes') data=readonly?['admin.review']:permissions
    else if (path==='/admin/tenants') data={items:[{id:'school',name:'界面验收样例租户',
      tenant_type:'school',parent_id:null,is_active:true,config_version:0}]}
    else if (path==='/admin/organizations') data={items:orgs}
    else if (path==='/admin/users') data={items:[{id:'user',name:'界面验收样例用户',
      username:'fixture-user',role:'member',org_unit_id:'branch',is_active:true}]}
    else if (path==='/admin/governance') data=config
    else if (path==='/admin/reviews' && method==='GET') data={items:[review],has_more:false,total:1}
    else if (path==='/admin/reviews/review') data={...review,stale,submitted_by:self?'viewer':'other',
      snapshot:stale?null:review.snapshot}
    else if (path==='/admin/reviews/review/decision') data={...review,status:body.decision,
      effective_status:body.decision,opinion:body.opinion}
    else if (path==='/admin/jobs' && method==='GET') data={items:[]}
    else if (path==='/admin/jobs' && method==='POST') data={id:'job',...body,status:'queued'}
    else if (path==='/admin/operations') data={jobs:{queued:1},reviews:{pending:1},model_usage:[],
      alerts:[{action:'query',result:'denied',count:5,window_hours:24}],audit_spool_pending:0}
    else if (['/audit','/admin/audit','/admin/audit-logs'].includes(path)) data={items:[],total:0}
    else throw new Error('未覆盖的界面请求 '+method+' '+path)
    await route.fulfill({status:200,contentType:'application/json',
      body:JSON.stringify({code:0,message:'success',data,trace_id:'fixture-trace'})})
  })
  const tab=await ctx.newPage()
  tab.on('pageerror',e=>errors.push(e.message))
  await tab.goto(BASE+'/governance')
  await tab.getByRole('heading',{name:'管理与审核',exact:true}).waitFor()
  return {ctx,tab,stale:()=>{stale=true},self:()=>{self=true}}
}
try {
  const {ctx,tab,stale,self}=await page()
  await tab.getByRole('button',{name:'下一页',exact:true}).isDisabled().then(v=>assert.ok(v))
  checks.push('审核分页按服务端has_more终止')
  await tab.getByRole('button',{name:'查看材料',exact:true}).click()
  await tab.getByLabel('审核意见', {exact:true}).fill('已核对界面验收材料。')
  await tab.getByRole('button',{name:'保存人工结论',exact:true}).click()
  assert.equal(mutations.at(-1).body.source_version,'a'.repeat(64))
  assert.equal(mutations.at(-1).body.decision,'approved')
  checks.push('人工结论携带冻结版本和意见')
  stale()
  await tab.getByRole('button',{name:'查看材料',exact:true}).click()
  await tab.getByText('源内容已变化，当前快照不能继续审核，请重新提交。').waitFor()
  assert.equal(await tab.getByRole('button',{name:'保存人工结论',exact:true}).count(),0)
  await tab.getByRole('button',{name:'关闭',exact:true}).last().click()
  checks.push('来源失效不可审核且不显示旧快照')
  self()
  await tab.getByRole('button',{name:'查看材料',exact:true}).click()
  assert.equal(await tab.getByRole('button',{name:'保存人工结论',exact:true}).count(),0)
  await tab.getByRole('button',{name:'关闭',exact:true}).last().click()
  checks.push('提交人不能自审')
  await tab.getByRole('tab',{name:'学校配置',exact:true}).click()
  await tab.getByText('待配置',{exact:false}).first().waitFor()
  assert.equal(await tab.locator('input[type=checkbox]:checked').count(),0)
  await tab.screenshot({path:resolve(OUT,'governance-config-desktop.png'),fullPage:true})
  checks.push('未确认学校、模型和电子归档保持关闭')
  await tab.getByRole('tab',{name:'组织与账号',exact:true}).click()
  await tab.getByRole('button',{name:'新增组织',exact:true}).click()
  await tab.getByLabel('名称',{exact:true}).fill('界面验收样例院系')
  await tab.getByLabel('上级组织',{exact:true}).selectOption('root')
  await tab.getByRole('button',{name:'保存',exact:true}).click()
  assert.equal(mutations.at(-1).body.parent_id,'root')
  assert.equal(mutations.at(-1).body.org_type,'department')
  checks.push('组织创建携带服务端校验所需父级和类型')
  await tab.getByRole('tab',{name:'任务台账',exact:true}).click()
  await tab.getByRole('button',{name:'创建任务',exact:true}).click()
  await tab.getByRole('button',{name:'保存',exact:true}).click()
  assert.equal(mutations.at(-1).path,'/admin/jobs')
  assert.ok(mutations.at(-1).body.dedup_key)
  checks.push('任务创建使用独立去重编号')
  await tab.getByRole('tab',{name:'运行审计',exact:true}).click()
  await tab.getByRole('heading',{name:'审计查询',exact:true}).waitFor()
  await tab.getByLabel('用户编号',{exact:true}).fill('fixture-user-id')
  await tab.getByRole('button',{name:'查询审计记录',exact:true}).click()
  checks.push('运行告警与审计筛选可操作')
  await tab.screenshot({path:resolve(OUT,'governance-audit-desktop.png'),fullPage:true})
  await ctx.close()
  for (const width of [768,390]) {
    const c=await page(width)
    for (const label of ['组织与账号','学校配置','人工审核','任务台账','运行审计']) {
      await c.tab.getByRole('tab',{name:label,exact:true}).click()
      await c.tab.locator('.governance[aria-busy="false"]').waitFor()
      await c.tab.screenshot({path:resolve(OUT,'governance-'+label+'-'+width+'.png'),fullPage:true})
      assert.ok(await c.tab.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+1),
        label+'在'+width+'宽度不能让整页溢出')
    }
    await c.tab.screenshot({path:resolve(OUT,'governance-audit-'+width+'.png'),fullPage:true})
    await c.ctx.close()
  }
  checks.push('768和390宽度五个工作区无整页溢出')
  const restricted=await page(1440,true)
  assert.equal(await restricted.tab.getByRole('tab',{name:'组织与账号'}).count(),0)
  assert.equal(await restricted.tab.getByRole('tab',{name:'学校配置'}).count(),0)
  assert.equal(await restricted.tab.getByRole('tab',{name:'运行审计'}).count(),0)
  await restricted.ctx.close()
  checks.push('受限账号不显示组织、配置及运行审计入口')
  assert.deepEqual(errors,[])
  await writeFile(resolve(OUT,'report.json'),JSON.stringify({status:'passed',checks,
    request_contracts:mutations.length,fixture_only:true},null,2))
  console.log(JSON.stringify({status:'passed',checks:checks.length,request_contracts:mutations.length}))
} finally {
  await browser.close()
  server?.kill()
}
