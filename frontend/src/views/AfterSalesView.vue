<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { api, type User, type Order, type Policy, type Ticket, type Conversation, type ChatMessage, type Audit } from '@/api/sales'
const user = ref<User | null>(null), username = ref('user'), password = ref('123456')
const busy = ref(false), error = ref(''), success = ref(''), tab = ref('概览')
const orders = ref<Order[]>([]), tickets = ref<Ticket[]>([]), policies = ref<Policy[]>([]), conversations = ref<Conversation[]>([]), audits = ref<Audit[]>([])
const selectedOrder = ref(''), kind = ref('return'), reason = ref(''), requestId = ref(crypto.randomUUID()), confirmed = ref(false), showApplication = ref(false)
const question = ref(''), mode = ref('local'), chatId = ref(''), messages = ref<ChatMessage[]>([])
const opinions = ref<Record<string, string>>({}), drafts = ref<Record<string, string>>({}), versions = ref<Policy[]>([]), historyPolicy = ref('')
const merchant = computed(() => user.value?.role === 'merchant')
const nav = computed(() => merchant.value ? ['概览', '工单审核', '政策管理', '操作记录'] : ['概览', '订单', '咨询', '我的申请', '服务政策'])
const active = computed(() => tickets.value.filter(t => ['pending', 'approved'].includes(t.status)).length)
const labels: Record<string,string> = { pending: '待人工审核', approved: '已受理', rejected: '未通过', completed: '处理完成', local: '本地检索与规则', llm: '大模型依据回答', local_fallback: '本地回答 · 模型失败已降级' }
const date = (v: string) => new Date(v).toLocaleString('zh-CN')
async function run(action: () => Promise<void>) {
  if (busy.value) return
  busy.value = true; error.value = ''; success.value = ''
  try { await action() } catch (e) { error.value = e instanceof Error ? e.message : '操作失败，请重试' } finally { busy.value = false }
}
async function load() {
  const [ts, ps] = await Promise.all([api<Ticket[]>('/tickets'), api<Policy[]>('/policies')])
  tickets.value = ts; policies.value = ps; drafts.value = Object.fromEntries(ps.map(p => [p.id, p.body]))
  if (merchant.value) audits.value = await api<Audit[]>('/audit')
  else {
    const [os, cs] = await Promise.all([api<Order[]>('/orders'), api<Conversation[]>('/conversations')])
    orders.value = os; conversations.value = cs
    if (!selectedOrder.value) selectedOrder.value = os[0]?.id || ''
  }
}
async function login() { await run(async () => {
  const result = await api<{token: string; user: User}>('/auth/login', 'POST', {username: username.value, password: password.value})
  sessionStorage.setItem('sales-token', result.token); user.value = result.user; tab.value = '概览'; await load()
}) }
function clear() { sessionStorage.removeItem('sales-token'); user.value = null; orders.value = []; tickets.value = []; messages.value = []; conversations.value = []; chatId.value = ''; selectedOrder.value = ''; showApplication.value = false; tab.value = '概览' }
async function logout() { await run(async () => { await api('/auth/logout', 'POST'); clear() }) }
function expired() { clear(); error.value = '会话已失效，请重新登录' }
function apply(order: Order) { selectedOrder.value = order.id; reason.value = ''; kind.value = 'return'; requestId.value = crypto.randomUUID(); confirmed.value = false; showApplication.value = true }
async function submit() { await run(async () => {
  if (!confirmed.value) throw new Error('请确认模拟申请说明')
  await api('/tickets', 'POST', { order_id: selectedOrder.value, kind: kind.value, reason: reason.value, request_id: requestId.value })
  showApplication.value = false; tab.value = '我的申请'; await load(); success.value = '申请已提交，等待商家人工审核。'
}) }
async function review(t: Ticket, status: string) { await run(async () => {
  await api('/tickets/' + t.id + '/review', 'POST', { status, opinion: opinions.value[t.id] || '' }); await load(); success.value = '处理结果已保存。'
}) }
async function savePolicy(p: Policy) { await run(async () => {
  await api('/policies/' + p.id, 'PUT', { version: p.version, body: drafts.value[p.id] }); await load(); success.value = '新版本已保存，下次咨询立即生效。'
}) }
async function history(p: Policy) { await run(async () => { versions.value = await api<Policy[]>('/policies/' + p.id + '/versions'); historyPolicy.value = p.title }) }
async function openChat(c: Conversation) { await run(async () => { const data = await api<Conversation>('/conversations/' + c.id); chatId.value = c.id; selectedOrder.value = data.order_id || ''; messages.value = data.messages || []; tab.value = '咨询' }) }
function newChat() { chatId.value = ''; messages.value = [] }
async function send() { await run(async () => {
  if (!question.value.trim()) return
  if (!chatId.value) { const c = await api<Conversation>('/conversations', 'POST', { order_id: selectedOrder.value || null }); chatId.value = c.id }
  await api('/conversations/' + chatId.value + '/messages', 'POST', { message: question.value, order_id: selectedOrder.value || null, mode: mode.value })
  const c = await api<Conversation>('/conversations/' + chatId.value)
  messages.value = c.messages || []; question.value = ''; conversations.value = await api<Conversation[]>('/conversations')
}) }
onMounted(async () => { window.addEventListener('sales-expired', expired); if (sessionStorage.getItem('sales-token')) await run(async () => { user.value = await api<User>('/auth/me'); await load() }) })
onUnmounted(() => window.removeEventListener('sales-expired', expired))
</script>

<template>
  <div class="sales-app">
    <div v-if="!user" class="login-page">
      <section class="login-story"><div class="wordmark">N / CARE <span>数码售后服务</span></div><div class="eyebrow">SINGLE MERCHANT · DEMO 01</div><h1>每一次售后，<br>都有据可循。</h1><p>从咨询到申请，从人工审核到处理完成。<br>让服务的每一步都清晰可见。</p><div class="story-foot">01 / 单商家　02 / 数码商品　03 / 人工审核</div></section>
      <section class="login-card"><div class="eyebrow">WELCOME BACK</div><h2>登录服务空间</h2><p>消费者与商家使用同一入口，按角色进入工作台。</p><form @submit.prevent="login"><label>账号<input v-model="username" autocomplete="username" required aria-label="账号"></label><label>密码<input v-model="password" type="password" autocomplete="current-password" required aria-label="密码"></label><button class="primary" :disabled="busy">{{ busy ? '正在登录…' : '登录 →' }}</button></form><div v-if="error" class="error" role="alert">{{ error }}</div><div class="demo-note">本地演示账号<br><b>user / 123456</b> 消费者<br><b>admin / 123456</b> 商家管理员</div><small>全部订单、物流与售后处理均为模拟数据。</small></section>
    </div>
    <template v-else>
      <aside class="sidebar"><div class="wordmark">N / CARE</div><span class="space-label">{{ merchant ? '商家管理工作台' : '消费者服务空间' }}</span><nav><button v-for="(item, i) in nav" :key="item" :class="{selected:tab===item}" @click="tab=item"><span>0{{ i+1 }}</span>{{ item }}<span class="nav-arrow">↗</span></button></nav><div class="sidebar-bottom">● 单商家 · 数码售后<br><small>本地演示 / V1.0</small></div></aside>
      <main><header><span>服务中心 <span class="muted">/ {{ tab }}</span></span><div><span class="account">{{ user.username }} · {{ merchant ? '商家' : '消费者' }}</span><button :disabled="busy" @click="logout">退出</button></div></header><div class="simulation">演示环境 <span>订单、物流均为模拟数据；受理与完成不代表实际退款到账。</span></div>
        <section class="workspace"><div class="page-heading"><div><div class="eyebrow">{{ merchant ? 'MERCHANT OPERATIONS' : 'AFTER-SALES SERVICE' }}</div><h1>{{ tab === '概览' ? (merchant ? '服务工作，一目了然。' : '你好，今天需要什么帮助？') : tab }}</h1></div><button :disabled="busy" @click="run(load)">{{ busy ? '加载中…' : '刷新数据 ↻' }}</button></div>
          <div v-if="error" class="error" role="alert">{{ error }}</div><div v-if="success" class="success" role="status">{{ success }}</div><div v-if="busy" class="loading" role="status">正在处理，请稍候…</div>
          <template v-if="tab==='概览'"><div class="hero"><div><span class="eyebrow">{{ merchant ? 'HUMAN IN THE LOOP' : 'EVIDENCE BEFORE ANSWERS' }}</span><h2>{{ merchant ? '让每一个申请，得到明确回应。' : '售后有问题，先聊一聊。' }}</h2><p>{{ merchant ? '查看规则预检与提交时的政策依据，填写意见后完成审核。' : '选择你的订单，查询政策与进度。需要申请时，由你确认提交。' }}</p><button class="primary" @click="tab=merchant?'工单审核':'咨询'">{{ merchant ? '进入工单审核 →' : '开始咨询 →' }}</button></div><div class="hero-mark">{{ merchant ? '↗' : '◎' }}</div></div><div class="stats"><article><span>{{ merchant ? '全部工单' : '我的订单' }}</span><strong>{{ merchant ? tickets.length : orders.length }}</strong><small>明确标注的模拟业务</small></article><article><span>处理中申请</span><strong>{{ active }}</strong><small>待审核 / 已受理</small></article><article><span>服务政策</span><strong>{{ policies.length }}</strong><small>当前有效版本，可追溯依据</small></article></div><h2 class="section-title">服务流程 <span>每一步，进度可查</span></h2><div class="process"><span>01　选择订单 / 咨询</span><span>02　确认申请</span><span>03　商家人工审核</span><span>04　记录处理完成</span></div></template>
          <template v-if="tab==='订单'"><div class="order-grid"><article v-for="o in orders" :key="o.id" class="card order"><div class="card-top"><span class="tag">模拟订单</span><small>{{ o.id }}</small></div><div class="product-icon">{{ o.product.includes('耳机')?'◉':o.product.includes('键盘')?'▤':'▣' }}</div><h2>{{ o.product }}</h2><strong class="price">¥{{ (o.amount/100).toFixed(2) }}</strong><p>{{ o.logistics }}</p><p class="muted">签收时间：{{ date(o.signed_at) }}</p><div class="actions"><button :disabled="busy" @click="selectedOrder=o.id;newChat();tab='咨询'">咨询此订单</button><button class="primary" :disabled="busy || tickets.some(t=>t.order_id===o.id && ['pending','approved'].includes(t.status))" @click="apply(o)">申请售后</button></div></article></div><div v-if="!orders.length" class="empty">暂无订单。</div></template>
          <template v-if="tab==='咨询'"><div class="chat-layout"><aside class="card history"><div class="card-top"><h3>历史会话</h3><button :disabled="busy" @click="newChat">新建</button></div><button v-for="c in conversations" :key="c.id" :class="{selected:chatId===c.id}" :disabled="busy" @click="openChat(c)">{{ c.order_id || '政策咨询' }}<small>{{ c.created_at ? date(c.created_at) : '' }}</small></button><p v-if="!conversations.length" class="muted">暂无会话，从右侧开始。</p></aside><div class="card chat"><div class="chat-options"><label>关联订单<select v-model="selectedOrder" :disabled="busy"><option value="">不选择订单</option><option v-for="o in orders" :key="o.id" :value="o.id">{{ o.id }} · {{ o.product }}</option></select></label><label>请求回答模式<select v-model="mode" :disabled="busy"><option value="local">本地检索与规则（默认）</option><option value="llm">大模型（可失败降级）</option></select></label></div><p class="muted">多轮对话保留关联订单。助手仅查询；申请需在订单页填写表单。</p><div class="messages" aria-live="polite"><div v-if="!messages.length" class="chat-empty"><span>◎</span><h2>有依据的解答，更安心。</h2><p>试试：退货政策是什么？运费由谁承担？我的申请进度？</p></div><article v-for="(m,i) in messages" :key="i" :class="['message',m.role]"><small>{{ m.role==='user'?'你':'售后助手 · '+(labels[m.mode]||m.mode) }}</small><p>{{ m.content }}</p></article></div><form class="composer" @submit.prevent="send"><textarea v-model="question" aria-label="咨询问题" placeholder="输入商品问题、政策或进度问题…" maxlength="2000" required :disabled="busy"></textarea><button class="primary" :disabled="busy || !question.trim()">发送 ↑</button></form></div></div></template>
          <template v-if="tab==='我的申请'||tab==='工单审核'"><p class="muted">受理后仍需后续处理；所有状态为模拟记录，均不代表退款到账。</p><div v-if="!tickets.length" class="empty">暂无售后申请。{{ merchant ? '消费者提交后，工单会显示在这里。' : '可前往订单页提交申请。' }}</div><article v-for="t in tickets" :key="t.id" class="card ticket"><div class="card-top"><div><span :class="['status',t.status]">{{ labels[t.status] }}</span><span class="ticket-id">{{ t.id }}</span></div><small>{{ date(t.created_at) }}</small></div><h3>{{ t.order_id }} · {{ t.kind==='return'?'退货':'换货' }}申请</h3><p>申请原因：{{ t.reason }}</p><div class="precheck">规则预检：{{ t.precheck.result }}（{{ t.precheck.rule_days }}天窗口 / 已签收{{ t.precheck.elapsed_days }}天）</div><p><b>商家处理意见：</b>{{ t.opinion || '等待商家审核' }}</p><details><summary>查看提交时政策快照</summary><div v-for="p in t.snapshot" :key="p.id"><h4>{{ p.title }} · v{{ p.version }}</h4><p>{{ p.body }}</p></div></details><div v-if="merchant && ['pending','approved'].includes(t.status)" class="review-form"><label>处理意见<textarea v-model="opinions[t.id]" placeholder="请填写受理、拒绝或完成的具体意见" maxlength="2000" :disabled="busy"></textarea></label><div class="actions"><template v-if="t.status==='pending'"><button :disabled="busy || (opinions[t.id]||'').trim().length<2" @click="review(t,'rejected')">拒绝申请</button><button class="primary" :disabled="busy || (opinions[t.id]||'').trim().length<2" @click="review(t,'approved')">受理申请</button></template><button v-else class="primary" :disabled="busy || (opinions[t.id]||'').trim().length<2" @click="review(t,'completed')">记录处理完成</button></div></div></article></template>
          <template v-if="tab==='服务政策'||tab==='政策管理'"><div class="rule-note"><b>演示固定规则：退货7天 / 换货30天</b><p>按签收时刻计算，超期仍可提交人工例外审核。编辑正文不会自动修改代码规则；变更时间规则需同步修改代码。历史申请保留提交时政策快照。</p></div><article v-for="p in policies" :key="p.id" class="card policy"><div class="card-top"><h2>{{ p.title }}</h2><span class="tag">当前 v{{ p.version }}</span></div><template v-if="merchant"><label>政策正文<textarea v-model="drafts[p.id]" rows="5" :disabled="busy" maxlength="10000"></textarea></label><div class="actions"><button :disabled="busy" @click="history(p)">版本历史</button><button class="primary" :disabled="busy || drafts[p.id]===p.body" @click="savePolicy(p)">保存新版本</button></div></template><p v-else>{{ p.body }}</p></article><div v-if="historyPolicy" class="card"><h3>{{ historyPolicy }} · 版本历史</h3><article v-for="p in versions" :key="p.version"><h4>v{{ p.version }} · {{ p.created_at ? date(p.created_at):'' }}</h4><p>{{ p.body }}</p></article></div></template>
          <template v-if="tab==='操作记录'"><div v-if="!audits.length" class="empty">暂无操作记录。</div><div class="audit-list"><article v-for="a in audits" :key="a.id" class="card"><div class="card-top"><b>{{ a.action }}</b><small>{{ date(a.created_at) }}</small></div><p>{{ a.actor }} → {{ a.target }}</p><code>{{ a.detail }}</code></article></div><p class="muted">展示最近500条记录；完整记录保存在数据库。</p></template>
        </section><footer>N / CARE　数码售后平台 <span>单商家 · 演示第一版</span></footer>
      </main>
    </template>
    <div v-if="showApplication" class="modal-backdrop"><section class="modal" role="dialog" aria-modal="true" aria-labelledby="apply-title"><h2 id="apply-title">确认售后申请</h2><p>{{ selectedOrder }} · 全部业务均为模拟</p><form @submit.prevent="submit"><label>申请类型<select v-model="kind" :disabled="busy"><option value="return">退货（7天规则）</option><option value="exchange">换货（30天规则）</option></select></label><label>申请原因<textarea v-model="reason" required minlength="2" maxlength="2000" :disabled="busy" placeholder="描述商品问题与申请原因"></textarea></label><p class="muted">超期仍可提交例外审核。后端将校验归属、重复申请与时间规则，并保存政策快照。</p><label class="checkbox"><input v-model="confirmed" type="checkbox" required :disabled="busy">我确认提交模拟申请，等待人工审核；受理不代表退款到账。</label><div v-if="error" class="error" role="alert">{{ error }}</div><div class="actions"><button type="button" :disabled="busy" @click="showApplication=false">取消</button><button class="primary" :disabled="busy || !confirmed || reason.trim().length<2">{{ busy?'提交中…':'确认提交申请' }}</button></div></form></section></div>
  </div>
</template>

<style src="./after-sales.css"></style>
