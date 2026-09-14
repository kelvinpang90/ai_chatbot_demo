// What the director's console says about one tool call (task 27).
//
// The owner watched the console beside a real phone on 2026-09-14 and decided:
// by default the screen tells the business story ("Added to cart: …", "Told
// the customer"), and the function name, arguments and timing only appear
// behind a switch. The instruction text a tool hands back to the model is shown
// in neither mode -- `request_human_help` put it on the projector that day.
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

/** "0.004 s", "12.3 s". */
export function seconds(ms: number): string {
  return `${(ms / 1000).toFixed(ms < 10000 ? 3 : 1)} s`
}

/** "1 min 16 s", "45 s". */
export function span(totalSeconds: number): string {
  const s = Math.max(0, Math.round(totalSeconds))
  return s < 60 ? `${s} s` : `${Math.floor(s / 60)} min ${s % 60} s`
}

// What the customer's phone shows in bold. The bot's **markdown** goes out as
// WhatsApp's *bold* (backend/app/services/whatsapp.py) but is logged as written,
// and a push can carry *bold* of its own. Like WhatsApp: no space just inside
// the stars, and never across a line -- so "* item" stays a plain line.
const BOLD = /\*\*(\S(?:.*?\S)?)\*\*|\*(\S(?:[^*\n]*?\S)?)\*/g

/** A message cut into plain and bold runs, the way the phone renders it. */
export function boldRuns(text: string): { text: string; bold: boolean }[] {
  const runs: { text: string; bold: boolean }[] = []
  let last = 0
  for (const match of text.matchAll(BOLD)) {
    if (match.index > last) runs.push({ text: text.slice(last, match.index), bold: false })
    runs.push({ text: match[1] ?? match[2], bold: true })
    last = match.index + match[0].length
  }
  if (last < text.length) runs.push({ text: text.slice(last), bold: false })
  return runs
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

/** A row the back-office panel lists under what was written. */
export interface Write {
  system: string
  ref: string
  detail: string
}

const NAMES: Record<string, string> = {
  food_update_cart: 'Update cart',
  food_place_order: 'Place order',
  food_order_status: 'Check order',
  erp_search_sku: 'Search products',
  erp_get_inventory: 'Check stock',
  erp_find_customer: 'Find ERP customer',
  erp_create_customer: 'Create ERP customer',
  erp_list_orders: 'List past orders',
  erp_create_sales_order: 'Create sales order',
  erp_generate_einvoice: 'Issue e-invoice',
  erp_find_order_by_sku: 'Find purchase',
  erp_create_credit_note: 'Issue credit note',
  crm_lookup_customer: 'Find CRM customer',
  crm_create_lead: 'Create CRM lead',
  offer_viewing_form: 'Send viewing form',
  book_property_viewing: 'Book viewing',
  hotel_search_rooms: 'Search rooms',
  hotel_create_booking: 'Book room',
  hotel_get_booking: 'Look up booking',
  hotel_modify_booking: 'Change booking',
  saas_search_known_issues: 'Search known issues',
  saas_create_ticket: 'Open ticket',
  saas_get_tickets: 'Look up tickets',
  request_human_help: 'Hand to a colleague',
  handover: 'Human takeover',
  'notify.push': 'Message the customer',
  'human.reply': "Colleague's reply",
  'voice.transcribe': 'Transcribe voice note',
  'image.download': 'Receive image',
  'document.download': 'Receive document',
  'whatsapp.send': 'Reply',
  'whatsapp.receive': 'Receive message',
}

export function toolName(tool: string): string {
  return NAMES[tool] ?? tool
}

const FOOD_STATUS: Record<string, string> = {
  received: 'Received',
  preparing: 'Preparing',
  on_the_way: 'On the way',
  delivered: 'Delivered',
}

// Prefixes of the fixed sentences some tools answer with. Matched on the start
// only, so a reworded tail in the backend does not silently change the card.
const HANDED_OVER = 'A colleague has been brought in'
const FORM_SENT = 'A booking form is being sent'
const NO_FORM = 'There is no form available'
const VIEWING_SAVED = 'IS ALREADY SAVED'
const OUTAGE = 'could not be reached'
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

  if (status === 'note') return card('note', '⏻', tool)

  if (tool === 'handover') {
    const reason = str(input?.reason)
    const why = reason === CONSOLE_TAKEOVER ? 'Taken over from the console' : reason && `Reason: ${reason}`
    return status === 'running'
      ? card('hand', 'H', 'Human has the conversation', joined([why, 'bot is silent']))
      : card('back', '↩', 'Human takeover · handed back to bot', joined([why, `a person handled it for ${span((call.durationMs ?? 0) / 1000)}`]))
  }

  if (tool === 'human.reply') {
    return status === 'error' ? card('fail', '!', "Colleague's reply did not arrive", firstLine(output)) : null
  }

  if (status === 'error') {
    // A send that never reached the phone is the one thing worth stopping a demo
    // for: on the customer's side it looks exactly like a pause.
    if (tool === 'notify.push' || tool === 'whatsapp.send') {
      return card('fail', '!', `${name} did not arrive -- the customer got nothing`, firstLine(output))
    }
    return card('fail', '!', `${name} failed`, 'System error -- the bot will not make a result up')
  }

  if (status === 'running') {
    return card(kindOf(tool), iconOf(tool), name, 'Running…')
  }

  const data = parse(output)
  const obj = data && typeof data === 'object' && !Array.isArray(data) ? (data as Json) : null
  const rows = Array.isArray(data) ? (data as Json[]) : null
  const refused = (detail = 'Did not go through -- the bot will tell the customer as it is') =>
    card('refused', '×', name, detail)

  // An outage is not a "no": the per-tool wording below ("No such product",
  // "No orders found") would claim the back office answered. Every back office
  // words its outage this way (erp.py / crm.py / food.py UNAVAILABLE), and the
  // failure drill (task 27.1) puts exactly this on screen.
  if (!data && str(output).includes(OUTAGE)) {
    return refused('System unreachable -- nothing looked up, nothing made up')
  }

  switch (tool) {
    case 'food_update_cart': {
      if (!obj) return refused()
      const cart = list(obj.cart)
      if (cart.length === 0) return card('cart', 'C', 'Emptied the cart')
      return card(
        'cart',
        'C',
        'Added to cart',
        joined([...cart.map((l) => `${str(l.name)} ×${str(l.quantity)}`), `total ${str(obj.total)}`]),
      )
    }
    case 'food_place_order':
      if (!obj) return refused()
      return card(
        'order',
        'O',
        `Order ${str(obj.order_no)} placed`,
        joined([list(obj.items).map(dish).join(', '), str(obj.total), `to ${str(obj.delivery_address)}`]),
      )
    case 'food_order_status': {
      const order = obj ? list(obj.orders)[0] : undefined
      if (!order) return refused('No order found')
      const eta = order.arrives_in_minutes
      return card(
        'lookup',
        '?',
        `Checked order ${str(order.order_no)}`,
        joined([FOOD_STATUS[str(order.status)] ?? str(order.status), eta != null ? `arrives in ~${str(eta)} min` : '']),
      )
    }
    case 'erp_search_sku': {
      if (!obj) return refused('No such product')
      const products = list(obj.products)
      return card(
        'lookup',
        '?',
        `Searched products for "${str(input?.keyword)}"`,
        joined([
          `${str(obj.total_matches ?? products.length)} found`,
          products.slice(0, 3).map((p) => `${str(p.name)} ${rm(p.unit_price_incl_tax)}`).join(', '),
        ]),
      )
    }
    case 'erp_get_inventory': {
      const sku = rows?.[0]
      if (!sku) return refused('No stock record')
      const where = list(sku.by_warehouse).map((w) => `${str(w.warehouse)} ${str(w.available)}`)
      return card('lookup', '?', `Checked stock of ${str(sku.code)}`, joined([`${str(sku.name)}: ${str(sku.total_available)} available`, where.join(', ')]))
    }
    case 'erp_find_customer':
    case 'crm_lookup_customer': {
      if (!rows) return refused('No record of this customer')
      const who = rows[0]
      const history =
        tool === 'crm_lookup_customer' && who
          ? `${str(who.deal_count)} deals · ${rm(who.total_deal_amount)}`
          : ''
      return card('lookup', '?', name, joined([`${rows.length} found`, str(who?.name), str(who?.company), history]))
    }
    case 'erp_list_orders':
    case 'erp_find_order_by_sku': {
      if (!rows) return refused('No orders found')
      const latest = rows[0]
      return card('lookup', '?', name, joined([`${rows.length} orders`, str(latest?.order_no), str(latest?.status)]))
    }
    case 'erp_create_customer':
      if (!obj) return refused()
      return card(
        'write',
        '+',
        obj.created ? 'Created ERP customer' : 'ERP customer already existed',
        joined([str(obj.code), str(obj.name), str(obj.phone)]),
      )
    case 'erp_create_sales_order':
      if (!obj) return refused()
      return card(
        'order',
        'O',
        `Sales order ${str(obj.order_no)} created`,
        joined([
          list(obj.lines).map((l) => `${str(l.name)} ×${str(l.qty)}`).join(', '),
          rm(obj.total_incl_tax),
          str(obj.warehouse),
        ]),
      )
    case 'erp_generate_einvoice':
      if (!obj) return refused()
      return card(
        'write',
        '+',
        `E-invoice ${str(obj.invoice_no)} issued`,
        joined([str(obj.order_no), str(obj.status), rm(obj.total_incl_tax), obj.pdf_sent ? 'PDF sent to phone' : 'PDF not sent']),
      )
    case 'erp_create_credit_note': {
      if (!obj) return refused()
      const item = (obj.item ?? {}) as Json
      return card(
        'write',
        '+',
        `Credit note ${str(obj.credit_note_no)} issued`,
        joined([`${str(item.name)} ×${str(item.qty_returned)}`, rm(obj.total_incl_tax), `order ${str(obj.order_no)}`]),
      )
    }
    case 'crm_create_lead':
      if (!obj) return refused()
      return card('write', '+', 'Created CRM lead', joined([str(obj.contact_name), str(obj.title), rm(obj.amount)]))
    case 'offer_viewing_form':
      if (str(output).startsWith(FORM_SENT)) return card('push', 'F', 'Sent the viewing form')
      if (str(output).startsWith(NO_FORM)) return card('note', 'F', 'No form on this channel', 'Asking for name, listing and date in the chat')
      return refused('Listings unreadable -- form not sent')
    case 'book_property_viewing': {
      if (!str(output).includes(VIEWING_SAVED)) return refused('Not booked')
      const id = /#(\d+)/.exec(str(output))?.[1]
      return card(
        'write',
        '+',
        `Viewing${id ? ` #${id}` : ''} booked`,
        joined([str(input?.customer_name), str(input?.listing_id), `${str(input?.viewing_date)} ${str(input?.preferred_time)}`.trim()]),
      )
    }
    case 'hotel_search_rooms':
    case 'hotel_get_booking':
    case 'saas_search_known_issues':
    case 'saas_get_tickets':
      if (!rows) return refused('Nothing found')
      return card('lookup', '?', name, `${rows.length} results`)
    case 'hotel_create_booking':
    case 'hotel_modify_booking':
      if (!obj) return refused()
      return card(
        'write',
        '+',
        `${name} ${str(obj.booking_id)}`,
        joined([str(obj.room_type), `${str(obj.check_in)} → ${str(obj.check_out)}`, `${str(obj.nights)} nights`, rm(obj.total_rm)]),
      )
    case 'saas_create_ticket':
      if (!obj) return refused()
      return card('write', '+', `Ticket ${str(obj.ticket_id)} opened`, joined([str(obj.subject), str(obj.priority)]))
    case 'request_human_help':
      return str(output).startsWith(HANDED_OVER)
        ? card('hand', 'H', 'Bot judged it out of scope and handed to a colleague', `Reason: ${str(input?.reason)}`)
        : card('refused', 'H', 'Wanted a colleague, but nobody is on this channel', 'The bot stays and takes contact details instead')
    case 'notify.push':
      if (str(output).startsWith(SUMMARY_MARK)) {
        return card('push', '↗', 'Sent the demo summary', firstLine(output).replace(SUMMARY_MARK, '').trim())
      }
      return card('push', '↗', 'Messaged the customer first', `"${firstLine(output)}"`, 'unasked')
    case 'voice.transcribe':
      return card('media', '♪', 'Understood a voice note', `"${str(output)}"`)
    case 'image.download':
      return card('media', '▣', 'Received an image')
    case 'document.download':
      return card('media', '▤', 'Received a document', str(input?.filename))
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
  return { request_human_help: 'H', 'notify.push': '↗', 'voice.transcribe': '♪' }[tool] ?? '…'
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
      return obj.created ? { system: 'ERP customer', ref: str(obj.code), detail: joined([str(obj.name), str(obj.phone)]) } : null
    case 'erp_create_sales_order':
      return {
        system: 'ERP sales order',
        ref: str(obj.order_no),
        detail: joined([str(obj.status), rm(obj.total_incl_tax), str(obj.warehouse)]),
      }
    case 'erp_generate_einvoice':
      return {
        system: 'ERP e-invoice',
        ref: str(obj.invoice_no),
        detail: joined([str(obj.order_no), str(obj.status), str(obj.lhdn_uin)]),
      }
    case 'erp_create_credit_note':
      return { system: 'ERP credit note', ref: str(obj.credit_note_no), detail: joined([str(obj.status), rm(obj.total_incl_tax)]) }
    case 'crm_create_lead':
      return { system: 'CRM lead', ref: str(obj.contact_name), detail: joined([str(obj.title), rm(obj.amount), str(obj.status)]) }
    case 'hotel_create_booking':
    case 'hotel_modify_booking':
      return { system: 'Booking', ref: str(obj.booking_id), detail: joined([str(obj.room_type), str(obj.status), rm(obj.total_rm)]) }
    case 'saas_create_ticket':
      return { system: 'Ticket', ref: str(obj.ticket_id), detail: joined([str(obj.subject), str(obj.status)]) }
    default:
      return null
  }
}
