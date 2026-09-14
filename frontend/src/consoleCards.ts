// What the director's console says about one tool call (task 27).
//
// The owner watched the console beside a real phone on 2026-09-14 and decided:
// by default the screen tells the business story ("放进购物车：…", "主动通知客户"),
// and the function name, arguments and timing only appear behind a switch. The
// instruction text a tool hands back to the model is shown in neither mode --
// `request_human_help` put it on the projector that day.
//
// Two facts about the outputs drive everything below (see backend/app/tools):
// a tool that did its job returns JSON; a tool that refused, or found the back
// office down, returns an English sentence addressed to the model -- with
// status "ok". So non-JSON output is never displayed, only summarised.

// Malaysia keeps one offset all year, and the audit log's DATETIME columns are
// written in it (backend/app/services/clock.py), so a fixed +08:00 is exact.
const KL_OFFSET = '+08:00'
const KL_ZONE = 'Asia/Kuala_Lumpur'

const klClock = new Intl.DateTimeFormat('en-GB', {
  timeZone: KL_ZONE,
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
})

/** Epoch seconds as Kuala Lumpur `HH:MM:SS`, whatever this laptop's clock says. */
export function klTime(at: number): string {
  return klClock.format(new Date(at * 1000))
}

/** A naive audit-log timestamp ("2026-09-14 17:56:48.123") as epoch seconds. */
export function klEpoch(naive: string): number {
  const ms = Date.parse(`${naive.replace(' ', 'T')}${KL_OFFSET}`)
  return Number.isNaN(ms) ? 0 : ms / 1000
}

/** "0.004 秒", "12.3 秒". */
export function seconds(ms: number): string {
  return `${(ms / 1000).toFixed(ms < 10000 ? 3 : 1)} 秒`
}

/** "1 分 16 秒", "45 秒". */
export function span(totalSeconds: number): string {
  const s = Math.max(0, Math.round(totalSeconds))
  return s < 60 ? `${s} 秒` : `${Math.floor(s / 60)} 分 ${s % 60} 秒`
}

/** One tool call as the console knows it, from the live feed or the audit log. */
export interface Call {
  tool: string
  input: Record<string, unknown> | null
  output: string | null
  status: 'ok' | 'error' | 'running' | 'note'
  durationMs: number | null
}

export type CardKind =
  | 'cart'
  | 'order'
  | 'lookup'
  | 'write'
  | 'push'
  | 'hand'
  | 'back'
  | 'media'
  | 'refused'
  | 'fail'
  | 'note'

export interface Card {
  kind: CardKind
  icon: string
  title: string
  detail: string
  badge?: string
}

/** A row the back-office panel lists under "写入了什么". */
export interface Write {
  system: string
  ref: string
  detail: string
}

const NAMES: Record<string, string> = {
  food_update_cart: '更新购物车',
  food_place_order: '下单',
  food_order_status: '查订单',
  erp_search_sku: '查商品',
  erp_get_inventory: '查库存',
  erp_find_customer: '查 ERP 客户',
  erp_create_customer: '建 ERP 客户',
  erp_list_orders: '查历史订单',
  erp_create_sales_order: '开销售单',
  erp_generate_einvoice: '开电子发票',
  erp_find_order_by_sku: '找购买记录',
  erp_create_credit_note: '开退货单',
  crm_lookup_customer: '查 CRM 客户',
  crm_create_lead: '写入 CRM 商机',
  offer_viewing_form: '发看房表单',
  book_property_viewing: '登记看房',
  hotel_search_rooms: '查空房',
  hotel_create_booking: '订房',
  hotel_get_booking: '查订房',
  hotel_modify_booking: '改订房',
  saas_search_known_issues: '查已知问题',
  saas_create_ticket: '开工单',
  saas_get_tickets: '查工单',
  request_human_help: '转给同事',
  handover: '人工接管',
  'notify.push': '主动通知客户',
  'human.reply': '同事的回复',
  'voice.transcribe': '听语音',
  'image.download': '收图片',
  'document.download': '收文件',
  'whatsapp.send': '回复',
  'whatsapp.receive': '收消息',
}

export function toolName(tool: string): string {
  return NAMES[tool] ?? tool
}

const FOOD_STATUS: Record<string, string> = {
  received: '已接单',
  preparing: '制作中',
  on_the_way: '配送中',
  delivered: '已送达',
}

// Prefixes of the fixed sentences some tools answer with. Matched on the start
// only, so a reworded tail in the backend does not silently change the card.
const HANDED_OVER = 'A colleague has been brought in'
const FORM_SENT = 'A booking form is being sent'
const NO_FORM = 'There is no form available'
const VIEWING_SAVED = 'IS ALREADY SAVED'
const CONSOLE_TAKEOVER = 'taken over from the console'
// The demo summary goes out through the same push as everything else; its text
// is what tells it apart (backend/app/console/summary.py).
const SUMMARY_MARK = '📋'

type Json = Record<string, unknown>

function parse(output: string | null): unknown {
  if (!output) return undefined
  try {
    return JSON.parse(output)
  } catch {
    return undefined
  }
}

function str(value: unknown): string {
  return value === null || value === undefined ? '' : String(value)
}

function list(value: unknown): Json[] {
  return Array.isArray(value) ? (value as Json[]) : []
}

/** ERP money arrives as "328.9000"; food money is already "RM 35.30". */
function rm(value: unknown): string {
  const text = str(value)
  if (!text) return ''
  if (text.startsWith('RM')) return text
  const n = Number(text)
  return Number.isFinite(n) ? `RM ${n.toFixed(2)}` : text
}

/** "2 x Nasi Lemak Special" -> "Nasi Lemak Special ×2". */
function dish(line: unknown): string {
  const match = /^(\d+) x (.+)$/.exec(str(line))
  return match ? `${match[2]} ×${match[1]}` : str(line)
}

function joined(parts: string[]): string {
  return parts.filter(Boolean).join(' · ')
}

function firstLine(text: string | null): string {
  return str(text).split('\n').find((line) => line.trim())?.trim() ?? ''
}

function card(kind: CardKind, icon: string, title: string, detail = '', badge?: string): Card {
  return { kind, icon, title, detail, badge }
}

/**
 * The card for one call, or null for what the console shows elsewhere (a
 * colleague's reply is already a bubble on the phone side).
 */
export function describe(call: Call): Card | null {
  const { tool, input, output, status } = call
  const name = toolName(tool)

  if (status === 'note') return card('note', '关', tool)

  if (tool === 'handover') {
    const reason = str(input?.reason)
    const why = reason === CONSOLE_TAKEOVER ? '在导演台手动接管' : reason && `原因：${reason}`
    return status === 'running'
      ? card('hand', '人', '人工接管中', joined([why, 'bot 已静默']))
      : card('back', '回', '人工接管 · 已交回 bot', joined([why, `人工处理了 ${span((call.durationMs ?? 0) / 1000)}`]))
  }

  if (tool === 'human.reply') {
    return status === 'error' ? card('fail', '!', '同事的回复没送达', firstLine(output)) : null
  }

  if (status === 'error') {
    // A send that never reached the phone is the one thing worth stopping a demo
    // for: on the customer's side it looks exactly like a pause.
    if (tool === 'notify.push' || tool === 'whatsapp.send') {
      return card('fail', '!', `${name}没送达，客户什么都没收到`, firstLine(output))
    }
    return card('fail', '!', `${name}出错`, '系统异常，bot 不会编一个结果出来')
  }

  if (status === 'running') {
    return card(kindOf(tool), iconOf(tool), name, '进行中…')
  }

  const data = parse(output)
  const obj = data && typeof data === 'object' && !Array.isArray(data) ? (data as Json) : null
  const rows = Array.isArray(data) ? (data as Json[]) : null
  const refused = (detail = '没办成，bot 会照实告诉客户') => card('refused', '×', name, detail)

  switch (tool) {
    case 'food_update_cart': {
      if (!obj) return refused()
      const cart = list(obj.cart)
      if (cart.length === 0) return card('cart', '车', '清空购物车')
      return card(
        'cart',
        '车',
        '放进购物车',
        joined([...cart.map((l) => `${str(l.name)} ×${str(l.quantity)}`), `合计 ${str(obj.total)}`]),
      )
    }
    case 'food_place_order':
      if (!obj) return refused()
      return card(
        'order',
        '单',
        `下单 ${str(obj.order_no)}`,
        joined([list(obj.items).map(dish).join('、'), str(obj.total), `送往 ${str(obj.delivery_address)}`]),
      )
    case 'food_order_status': {
      const order = obj ? list(obj.orders)[0] : undefined
      if (!order) return refused('没查到订单')
      const eta = order.arrives_in_minutes
      return card(
        'lookup',
        '查',
        `查订单 ${str(order.order_no)}`,
        joined([FOOD_STATUS[str(order.status)] ?? str(order.status), eta != null ? `预计 ${str(eta)} 分钟送达` : '']),
      )
    }
    case 'erp_search_sku': {
      if (!obj) return refused('没找到这款商品')
      const products = list(obj.products)
      return card(
        'lookup',
        '查',
        `查商品「${str(input?.keyword)}」`,
        joined([
          `找到 ${str(obj.total_matches ?? products.length)} 款`,
          products.slice(0, 3).map((p) => `${str(p.name_zh || p.name)} ${rm(p.unit_price_incl_tax)}`).join('、'),
        ]),
      )
    }
    case 'erp_get_inventory': {
      const sku = rows?.[0]
      if (!sku) return refused('没查到库存')
      const where = list(sku.by_warehouse).map((w) => `${str(w.warehouse)} ${str(w.available)}`)
      return card('lookup', '查', `查库存 ${str(sku.code)}`, joined([`${str(sku.name)} 可售 ${str(sku.total_available)}`, where.join('、')]))
    }
    case 'erp_find_customer':
    case 'crm_lookup_customer': {
      if (!rows) return refused('没有这位客户的档案')
      const who = rows[0]
      const history =
        tool === 'crm_lookup_customer' && who
          ? `成交 ${str(who.deal_count)} 笔 · ${rm(who.total_deal_amount)}`
          : ''
      return card('lookup', '查', name, joined([`找到 ${rows.length} 位`, str(who?.name), str(who?.company), history]))
    }
    case 'erp_list_orders':
    case 'erp_find_order_by_sku': {
      if (!rows) return refused('没有找到订单')
      const latest = rows[0]
      return card('lookup', '查', name, joined([`${rows.length} 张单`, str(latest?.order_no), str(latest?.status)]))
    }
    case 'erp_create_customer':
      if (!obj) return refused()
      return card(
        'write',
        '写',
        obj.created ? 'ERP 新建客户' : 'ERP 已有这位客户',
        joined([str(obj.code), str(obj.name), str(obj.phone)]),
      )
    case 'erp_create_sales_order':
      if (!obj) return refused()
      return card(
        'order',
        '单',
        `开销售单 ${str(obj.order_no)}`,
        joined([
          list(obj.lines).map((l) => `${str(l.name)} ×${str(l.qty)}`).join('、'),
          rm(obj.total_incl_tax),
          str(obj.warehouse),
        ]),
      )
    case 'erp_generate_einvoice':
      if (!obj) return refused()
      return card(
        'write',
        '票',
        `开电子发票 ${str(obj.invoice_no)}`,
        joined([str(obj.order_no), str(obj.status), rm(obj.total_incl_tax), obj.pdf_sent ? 'PDF 已发到手机' : 'PDF 未发出']),
      )
    case 'erp_create_credit_note': {
      if (!obj) return refused()
      const item = (obj.item ?? {}) as Json
      return card(
        'write',
        '退',
        `开退货单 ${str(obj.credit_note_no)}`,
        joined([`${str(item.name)} ×${str(item.qty_returned)}`, rm(obj.total_incl_tax), `原单 ${str(obj.order_no)}`]),
      )
    }
    case 'crm_create_lead':
      if (!obj) return refused()
      return card('write', '写', '写入 CRM 商机', joined([str(obj.contact_name), str(obj.title), rm(obj.amount)]))
    case 'offer_viewing_form':
      if (str(output).startsWith(FORM_SENT)) return card('push', '表', '发出看房表单')
      if (str(output).startsWith(NO_FORM)) return card('note', '表', '这条线发不了表单', '改在聊天里问姓名、房源、日期')
      return refused('读不到房源，表单没发')
    case 'book_property_viewing': {
      if (!str(output).includes(VIEWING_SAVED)) return refused('没登记上')
      const id = /#(\d+)/.exec(str(output))?.[1]
      return card(
        'write',
        '约',
        `登记看房${id ? ` #${id}` : ''}`,
        joined([str(input?.customer_name), str(input?.listing_id), `${str(input?.viewing_date)} ${str(input?.preferred_time)}`.trim()]),
      )
    }
    case 'hotel_search_rooms':
    case 'hotel_get_booking':
    case 'saas_search_known_issues':
    case 'saas_get_tickets':
      if (!rows) return refused('没有结果')
      return card('lookup', '查', name, `${rows.length} 条结果`)
    case 'hotel_create_booking':
    case 'hotel_modify_booking':
      if (!obj) return refused()
      return card(
        'write',
        '订',
        `${name} ${str(obj.booking_id)}`,
        joined([str(obj.room_type), `${str(obj.check_in)} → ${str(obj.check_out)}`, `${str(obj.nights)} 晚`, rm(obj.total_rm)]),
      )
    case 'saas_create_ticket':
      if (!obj) return refused()
      return card('write', '单', `开工单 ${str(obj.ticket_id)}`, joined([str(obj.subject), str(obj.priority)]))
    case 'request_human_help':
      return str(output).startsWith(HANDED_OVER)
        ? card('hand', '人', 'bot 判断超出范围，转给同事', `原因：${str(input?.reason)}`)
        : card('refused', '人', '想转同事，但这条线没人可接', 'bot 留在对话里，改为记下联系方式')
    case 'notify.push':
      if (str(output).startsWith(SUMMARY_MARK)) {
        return card('push', '推', '发出演示总结', firstLine(output).replace(SUMMARY_MARK, '').trim())
      }
      return card('push', '推', '主动通知客户', `「${firstLine(output)}」`, '客户没问')
    case 'voice.transcribe':
      return card('media', '听', '听懂一条语音', `「${str(output)}」`)
    case 'image.download':
      return card('media', '图', '收到一张图片')
    case 'document.download':
      return card('media', '文', '收到一份文件', str(input?.filename))
    default:
      return card('lookup', '·', name)
  }
}

function kindOf(tool: string): CardKind {
  if (tool === 'request_human_help') return 'hand'
  if (tool === 'notify.push') return 'push'
  if (tool.endsWith('.transcribe') || tool.endsWith('.download')) return 'media'
  return 'lookup'
}

function iconOf(tool: string): string {
  return { request_human_help: '人', 'notify.push': '推', 'voice.transcribe': '听' }[tool] ?? '…'
}

/**
 * What a call wrote into a back office, for the panel that lists changes.
 * Only writes that succeeded; the food and viewing tables are read from the
 * back office itself, so those tools are not repeated here.
 */
export function written(call: Call): Write | null {
  if (call.status !== 'ok') return null
  const data = parse(call.output)
  const obj = data && typeof data === 'object' && !Array.isArray(data) ? (data as Json) : null
  if (!obj) return null
  switch (call.tool) {
    case 'erp_create_customer':
      return obj.created ? { system: 'ERP 客户', ref: str(obj.code), detail: joined([str(obj.name), str(obj.phone)]) } : null
    case 'erp_create_sales_order':
      return {
        system: 'ERP 销售单',
        ref: str(obj.order_no),
        detail: joined([str(obj.status), rm(obj.total_incl_tax), str(obj.warehouse)]),
      }
    case 'erp_generate_einvoice':
      return {
        system: 'ERP 电子发票',
        ref: str(obj.invoice_no),
        detail: joined([str(obj.order_no), str(obj.status), str(obj.lhdn_uin)]),
      }
    case 'erp_create_credit_note':
      return { system: 'ERP 退货单', ref: str(obj.credit_note_no), detail: joined([str(obj.status), rm(obj.total_incl_tax)]) }
    case 'crm_create_lead':
      return { system: 'CRM 商机', ref: str(obj.contact_name), detail: joined([str(obj.title), rm(obj.amount), str(obj.status)]) }
    case 'hotel_create_booking':
    case 'hotel_modify_booking':
      return { system: '订房', ref: str(obj.booking_id), detail: joined([str(obj.room_type), str(obj.status), rm(obj.total_rm)]) }
    case 'saas_create_ticket':
      return { system: '工单', ref: str(obj.ticket_id), detail: joined([str(obj.subject), str(obj.status)]) }
    default:
      return null
  }
}
