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
  prompt_versions:{}, retention:{file_days:365, audit_days:365, physical_purge:'disabled', evidence:''},
  knowledge_supply:{} }
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
const mutations = [], queries = [], checks = [], errors = []
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
    else queries.push({path,params:Object.fromEntries(url.searchParams)})
    let data
    if (path==='/auth/me') data={id:'viewer',username:'ui-fixture',name:'界面验收账号',
      role:'school_admin',tenant_id:'school',org_unit_id:'root'}
    else if (path==='/auth/codes') data=readonly?['admin.review']:permissions
    else if (path==='/admin/tenants') data={items:[{id:'school',name:'界面验收样例租户',
      tenant_type:'school',parent_id:null,is_active:true,config_version:0}]}
    else if (path==='/admin/organizations') data={items:orgs}
    else if (path==='/admin/users') data={items:[{id:'user',name:'界面验收样例用户',
      username:'fixture-user',role:'member',org_unit_id:'branch',is_active:true}]}
    else if (path==='/admin/governance') data=method==='GET'?config:{...config,
      version:config.version+1, values:body.values}
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
    // 运行日志（T-SYS-06E）：一条正常完成（耗时 / 处理条数）与一条尝试失败（第几次 / 错误类型 / 耗时）
    else if (path==='/admin/run-logs') data={items:[
      {id:'run-log-1',created_at:'2026-10-16T01:10:00',event:'job_completed',event_text:'执行完成',
        result:'success',kind:'member_reminders',status:null,attempt:null,duration_ms:139,
        error_code:null,processed:2,reminder_count:null,resource_id:'job',request_id:'fixture-trace'},
      {id:'run-log-2',created_at:'2026-10-16T01:08:00',event:'job_attempt_failed',
        event_text:'执行失败',result:'denied',kind:'embedding',status:'failed',attempt:1,
        duration_ms:16,error_code:'HTTPException',processed:null,reminder_count:null,
        resource_id:'job-2',request_id:'fixture-trace-2'}],
      total:2,page:1,page_size:40,scope_note:'租户 界面验收样例租户'}
    // 版本留痕（T-SEC-11）：提示词当前值 + 变更历史、工作流契约版本、知识库修订事件
    else if (path==='/admin/version-trail') data={
      prompt:{current:{qa:'v2',rewrite:'v1'},defaults:{qa:'v1',rewrite:'v1'},
        history:[{config_version:3,changed_at:'2026-10-15T02:00:00',actor:'界面验收账号',
          username:'ui-fixture',reason:'调整问答提示词',prompt_versions:{qa:'v2',rewrite:'v1'},
          changes:[{kind:'qa',before:'v1',after:'v2'}]}],
        scope_note:'租户 界面验收样例租户；提示词版本来自租户配置（缺省回落到出厂默认）'},
      workflow:{items:[{workflow:'WF-03',name:'引用核验',version:'wf-03/1'},
        {workflow:'WF-04',name:'敏感信息检查',version:'wf-04/1'}],
        scope_note:'工作流契约版本来自代码常量（app/schemas/wf.py）'},
      knowledge:{items:[{created_at:'2026-10-15T01:00:00',event:'update_content',
        event_text:'内容更新',doc_id:'DOC-1',title:'某制度',revision:3,previous_revision:2,
        actor:'界面验收账号',username:'ui-fixture',resource_id:'doc-1'}],
        total:1,page:1,page_size:20,
        scope_note:'租户 界面验收样例租户；来源为知识条目的入库与内容更新审计'}}
    else if (path==='/admin/notification-channels') data={items:[
      {name:'inapp',description:'站内：投递记录即用户可见提醒，不外发',configured:true}],
      events:['channel_self_test'],routes:{channel_self_test:['inapp']},max_attempts:3}
    else if (path==='/admin/notification-deliveries') data={items:[
      {id:'delivery',event:'channel_self_test',channel:'inapp',recipient_id:null,
        subject:'渠道投递自检',status:'sent',attempts:1,last_error:null,
        delivered_at:'2026-10-11T08:00:00',created_at:'2026-10-11T08:00:00'}],
      statuses:['pending','sent','failed']}
    else if (path==='/admin/notifications/dispatch') data={results:[
      {channel:'inapp',status:'sent',attempts:1,skipped:false,error:null}]}
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
  // 供给机制（T-KB-13）：按权威来源登记责任部门、责任人与更新周期。整行留空的
  // 类别不写入配置；半填的行必须当场拦下，否则学校会以为"登记好了"，而条目
  // 既没有复核责任人也没有到期提醒。
  await tab.getByLabel('党章 · 责任部门',{exact:true}).fill('党委办公室')
  await tab.getByLabel('责任人',{exact:true}).first().fill('李老师')
  await tab.getByLabel('更新周期（天，30–3650）',{exact:true}).first().fill('730')
  await tab.getByLabel('本次变更说明',{exact:true}).fill('登记党章供给机制')
  await tab.getByRole('button',{name:'保存学校配置',exact:true}).click()
  try {
    await tab.getByText('配置已保存，版本',{exact:false}).first().waitFor({timeout:5000})
  } catch {
    // 保存失败时把页面上的错误提示带出来，否则只能看到"等不到成功提示"。
    const failures = await tab.locator('.wb-error').allInnerTexts()
    throw new Error('保存学校配置失败：' + (failures.join(' / ') || '页面没有给出错误提示'))
  }
  const saved = mutations.at(-1).body.values.knowledge_supply
  assert.equal(mutations.at(-1).path,'/admin/governance')
  assert.equal(saved.party_constitution.owner_unit,'党委办公室')
  assert.equal(saved.party_constitution.review_cycle_days,730)
  assert.equal(Object.keys(saved).length,1)
  checks.push('供给机制按权威来源登记，未填写的类别不写入配置')
  // 保存后表单回显服务端值：登记错了必须能看见，而不是刷新后一片空白。
  assert.equal(await tab.getByLabel('党章 · 责任部门',{exact:true}).inputValue(),'党委办公室')
  await tab.screenshot({path:resolve(OUT,'governance-supply-desktop.png'),fullPage:true})
  const sent = mutations.length
  await tab.getByLabel('学校制度 · 责任部门',{exact:true}).fill('党委组织部')
  await tab.getByLabel('本次变更说明',{exact:true}).fill('登记学校制度供给机制')
  await tab.getByRole('button',{name:'保存学校配置',exact:true}).click()
  await tab.getByRole('alert').filter({hasText:'供给机制「学校制度」'}).waitFor()
  assert.equal(mutations.length,sent)
  checks.push('半填的供给机制当场拦下且不发起请求')
  await tab.getByLabel('学校制度 · 责任部门',{exact:true}).fill('')
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
  // 运行日志（T-SYS-06E）：任务"跑成什么样"必须可见——每次尝试的耗时、第几次、失败原因；
  // 时间筛选与审计查询统一按北京时间发出，避免差 8 小时。
  await tab.getByRole('heading',{name:'运行日志',exact:true}).waitFor()
  await tab.getByText('当前口径：租户 界面验收样例租户',{exact:false}).waitFor()
  await tab.getByLabel('开始时间（北京时间）',{exact:true}).last().fill('2026-10-16T09:00')
  const runLogRequest=tab.waitForResponse(r=>r.url().includes('/admin/run-logs'))
  await tab.getByRole('button',{name:'查询运行日志',exact:true}).click()
  await runLogRequest
  const runLogQuery=queries.filter(q=>q.path==='/admin/run-logs').at(-1)
  assert.equal(runLogQuery.params.start_at,'2026-10-16T09:00:00+08:00')
  assert.equal(await tab.getByRole('cell',{name:'139 毫秒',exact:true}).count(),1)
  assert.equal(await tab.getByRole('cell',{name:'HTTPException',exact:true}).count(),1)
  assert.equal(await tab.getByRole('cell',{name:'文档向量化',exact:true}).count(),1)
  assert.equal(await tab.getByText('第 1 页 · 共 2 条',{exact:true}).count(),1)
  checks.push('运行日志可见每次尝试的耗时与失败原因，时间筛选按北京时间发出')
  // 版本留痕（T-SEC-11）：提示词/工作流/知识库三块来源同页可查，
  // 提示词变更要能看出"从什么改成了什么"，知识库要能看出改到第几版。
  await tab.getByRole('heading',{name:'版本留痕',exact:true}).waitFor()
  assert.equal(await tab.getByRole('cell',{name:'问答提示词 v1 → v2',exact:true}).count(),1)
  assert.equal(await tab.getByRole('cell',{name:'wf-03/1',exact:true}).count(),1)
  assert.equal(await tab.getByRole('cell',{name:'第 2 → 3 版',exact:true}).count(),1)
  assert.equal(await tab.getByText('当前生效：问答提示词 v2 / 追问改写 v1',{exact:false}).count(),1)
  // 时间是库里存的 UTC 朴素时间，展示必须走与审计 / 台账同一件钟（+8 小时）；
  // 若界面照原样显示，会把 10:00 显示成 02:00——留痕时间对不上就白留了。
  const promptChangeRow=tab.getByRole('row',{name:/问答提示词 v1 → v2/})
  assert.ok((await promptChangeRow.innerText()).includes('10:00'))
  checks.push('版本留痕可见提示词变更、工作流契约版本与知识库修订，时间按北京时间展示')
  // 通知渠道与投递台账属于运行审计工作区：渠道就绪状态与投递事实都要可见。
  assert.ok(await tab.getByRole('heading',{name:'通知渠道与投递台账',exact:true}).count())
  // inapp 既是已登记渠道，也出现在投递台账的「渠道」列，因此这里只断言存在。
  assert.ok(await tab.getByRole('cell',{name:'inapp',exact:true}).count()>=1)
  assert.equal(await tab.getByRole('cell',{name:'已就绪',exact:true}).count(),1)
  assert.equal(await tab.getByRole('cell',{name:'已投递',exact:true}).count(),1)
  await tab.getByRole('button',{name:'发起渠道自检',exact:true}).click()
  await tab.getByText('自检结果：',{exact:false}).first().waitFor()
  assert.equal(mutations.at(-1).path,'/admin/notifications/dispatch')
  assert.ok(mutations.at(-1).body.dedup_key)
  assert.equal(mutations.at(-1).body.event,'channel_self_test')
  checks.push('通知渠道自检走服务端投递并携带去重键')
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
