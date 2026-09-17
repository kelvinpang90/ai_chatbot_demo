import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import './Admin.css'
import {
  ApiError,
  forgetToken,
  readFoodOrders,
  readHotelBookings,
  readListings,
  readSupportTickets,
  readViewings,
  rememberToken,
  storedToken,
  type FoodOrder,
  type HotelBooking,
  type Listing,
  type SupportTicket,
  type Viewing,
} from '../api'

// Every demo's back office on one page, a tab each (task 38.5; user decision,
// 2026-09-17). Retail is deliberately not here: its records live in the real ERP
// and CRM, which have screens of their own. The tab is in the address -- `#hotel`
// -- so a tab can be bookmarked, and the pages this replaced, `/food-admin` and
// `/vertical-admin`, open on theirs.
const TABS = ['food', 'realestate', 'hotel', 'saas'] as const

export type AdminTab = (typeof TABS)[number]

// How often a tab asks whether anything new came in. The customer does it on
// their phone and looks up at this screen; five seconds is the longest gap that
// still reads as "it just appeared" rather than "someone refreshed the page".
// For the restaurant every poll is also the moment an order moves from "制作中"
// to "配送中", since the backend reads that off the order's own timeline.
const POLL_MS = 5000

// How long a row that has just arrived stays marked. Long enough for a room to
// follow the eye to it, short enough that the screen is not permanently striped
// by the time three bookings are in.
const FRESH_MS = 8000

// --- the words on the page (task 38.7) -------------------------------------------
//
// English or Chinese, picked with the switch in the corner and remembered in this
// browser; English until somebody picks, like the console beside it (user
// decisions, 2026-09-17). Kept here rather than in i18n/strings.ts: that file is
// the customer chat's, in three languages, and shares no words with this screen.
// What the records themselves say -- a name, a dish, a room type, a ticket's
// subject -- is shown as it was written, in either language.

type AdminLang = 'en' | 'zh'

const LANG_STORAGE_KEY = 'admin_lang'

const TEXT = {
  en: {
    tabs: {
      food: '🍜 Food orders',
      realestate: '🏡 Property viewings',
      hotel: '🏨 Hotel bookings',
      saas: '🛠️ SaaS tickets',
    },
    gate: {
      title: '🗂️ Demo back office',
      blurb:
        'The back offices of the food, property, hotel and SaaS demos. Needs the console token (CONSOLE_TOKEN on the server).',
      enter: 'Enter',
      badToken:
        'Wrong token. If you copied it from the server .env, leave out the quotes around the value -- docker compose counts them as part of the token.',
    },
    backOffice: 'Demo back office',
    updated: (at: string) => `Updated ${at}`,
    loading: 'Loading…',
    refresh: 'Refresh',
    storeDown: (store: string) =>
      `Back office unavailable: the ${store} database cannot be reached, or the backend has no CONSOLE_TOKEN.`,
    listDown: 'Back office unavailable: the list could not be read.',
    stores: { food: 'food', realestate: 'property', hotel: 'hotel', saas: 'ticket' },
    food: {
      what: 'Delivery orders',
      heading: 'Orders',
      empty: 'No orders yet. When a customer confirms an order on WhatsApp, it appears at the top by itself.',
      columns: ['Order', 'Customer', 'Dishes', 'Amount', 'Status'],
      stages: { received: 'Received', preparing: 'Preparing', on_the_way: 'On the way', delivered: 'Delivered' },
      delivery: (fee: string) => `incl. delivery ${fee}`,
      timeline: (placed: string, ready: string, delivered: string) =>
        `In ${placed} · Ready ${ready} · Delivered ${delivered}`,
    },
    realestate: {
      what: 'Viewing requests',
      heading: 'Viewing requests',
      empty: 'No viewings yet. When a customer fills in the form on WhatsApp, it appears at the top by itself.',
      columns: ['Received', 'Customer', 'Property', 'Price', 'Viewing'],
      withdrawn: 'Listing withdrawn',
      listings: 'Listings for sale',
      noListings: 'No listings.',
      listingColumns: ['ID', 'Type', 'Area', 'Size', 'Bedrooms', 'Price', 'Status'],
    },
    hotel: {
      what: 'Room bookings',
      heading: 'Bookings',
      empty: 'No bookings yet. When a guest confirms a room on WhatsApp, it appears at the top by itself.',
      columns: ['Booking', 'Guest', 'Room', 'Stay', 'Amount', 'Status'],
      stay: (nights: number, guests: number) =>
        `${nights} ${nights === 1 ? 'night' : 'nights'} · ${guests} ${guests === 1 ? 'guest' : 'guests'}`,
      perNight: (rate: string) => `${rate} / night`,
      confirmed: 'Confirmed',
      changed: (at: string) => `Changed ${at}`,
    },
    saas: {
      what: 'Support tickets',
      heading: 'Tickets',
      empty: 'No tickets yet. When a customer asks support to open one on WhatsApp, it appears at the top by itself.',
      columns: ['Ticket', 'Customer', 'Issue', 'Priority', 'Status'],
      priorities: { urgent: 'Urgent', high: 'High', normal: 'Normal', low: 'Low' } as Record<string, string>,
      open: 'Open',
    },
  },
  zh: {
    tabs: {
      food: '🍜 点餐',
      realestate: '🏡 房产看房',
      hotel: '🏨 酒店预订',
      saas: '🛠️ SaaS 工单',
    },
    gate: {
      title: '🗂️ 演示后台',
      blurb: '点餐、看房、酒店、SaaS 工单的演示后台。需要 console token（服务器上的 CONSOLE_TOKEN）。',
      enter: '进入',
      badToken:
        'token 不对。如果是从服务器 .env 复制的，注意值两边不要带引号——docker compose 会把引号也当成 token 的一部分。',
    },
    backOffice: '演示后台',
    updated: (at: string) => `已更新 ${at}`,
    loading: '读取中…',
    refresh: '刷新',
    storeDown: (store: string) => `后台暂不可用：${store}数据库连不上，或者后端没配 CONSOLE_TOKEN。`,
    listDown: '后台暂不可用：读不到列表。',
    stores: { food: '餐饮', realestate: '房产', hotel: '酒店', saas: '工单' },
    food: {
      what: '外卖订单',
      heading: '订单',
      empty: '还没有订单。客户在 WhatsApp 里确认下单后，这一行会自己出现在最上面。',
      columns: ['单号', '客户', '菜品', '金额', '状态'],
      stages: { received: '已接单', preparing: '制作中', on_the_way: '配送中', delivered: '已送达' },
      delivery: (fee: string) => `含配送 ${fee}`,
      timeline: (placed: string, ready: string, delivered: string) =>
        `接单 ${placed} · 出餐 ${ready} · 送达 ${delivered}`,
    },
    realestate: {
      what: '看房预约',
      heading: '看房预约',
      empty: '还没有预约。客户在 WhatsApp 里填完表单后，这一行会自己出现在最上面。',
      columns: ['收到', '客户', '房源', '报价', '看房时间'],
      withdrawn: '房源已下架',
      listings: '在售房源',
      noListings: '没有房源。',
      listingColumns: ['编号', '户型', '地区', '面积', '房间', '价格', '状态'],
    },
    hotel: {
      what: '客房预订',
      heading: '预订',
      empty: '还没有预订。客人在 WhatsApp 里确认订房后，这一行会自己出现在最上面。',
      columns: ['编号', '客人', '房型', '入住', '金额', '状态'],
      stay: (nights: number, guests: number) => `${nights} 晚 · ${guests} 位`,
      perNight: (rate: string) => `${rate} / 晚`,
      confirmed: '已确认',
      changed: (at: string) => `改过 ${at}`,
    },
    saas: {
      what: '支持工单',
      heading: '工单',
      empty: '还没有工单。客户在 WhatsApp 里让客服开单后，这一行会自己出现在最上面。',
      columns: ['编号', '客户', '问题', '优先级', '状态'],
      priorities: { urgent: '紧急', high: '高', normal: '普通', low: '低' } as Record<string, string>,
      open: '待处理',
    },
  },
}

type Text = (typeof TEXT)['en']

function storedLang(): AdminLang {
  try {
    return window.localStorage.getItem(LANG_STORAGE_KEY) === 'zh' ? 'zh' : 'en'
  } catch {
    return 'en'
  }
}

function storeLang(lang: AdminLang): void {
  try {
    window.localStorage.setItem(LANG_STORAGE_KEY, lang)
  } catch {
    // A browser refusing storage still switches; it forgets on reload.
  }
}

function LangSwitch({ lang, onChange }: { lang: AdminLang; onChange: (lang: AdminLang) => void }) {
  return (
    <div className="va-lang" role="group" aria-label="Language">
      {(
        [
          ['en', 'EN'],
          ['zh', '中文'],
        ] as const
      ).map(([code, label]) => (
        <button
          key={code}
          type="button"
          className={code === lang ? 'active' : undefined}
          aria-pressed={code === lang}
          onClick={() => onChange(code)}
        >
          {label}
        </button>
      ))}
    </div>
  )
}

/** The token box.
 *
 * Deliberately not shared with the console's (`Console.tsx` has its own): the
 * part worth sharing -- where the token is kept, and the URL-to-storage hop --
 * is already one implementation in `api.ts`. What is left is a form that has to
 * look like the screen it stands in front of, and this screen is the client's
 * own back office rather than the operator's dark console. The web chat stands
 * behind it too, which is why the button's word and the language switch are
 * optional: the chat passes neither and stays as it was.
 */
export function TokenGate({
  note,
  onUnlocked,
  title,
  blurb,
  enter = '进入',
  aside,
}: {
  note: string
  onUnlocked: () => void
  title: string
  blurb: string
  enter?: string
  aside?: ReactNode
}) {
  const [value, setValue] = useState('')
  return (
    <form
      className="va-gate"
      onSubmit={(e) => {
        e.preventDefault()
        if (!value.trim()) return
        rememberToken(value.trim())
        onUnlocked()
      }}
    >
      {aside}
      <h2>{title}</h2>
      <p>{blurb}</p>
      {note && <p className="va-gate-note">{note}</p>}
      <input
        type="password"
        value={value}
        autoFocus
        placeholder="console token"
        onChange={(e) => setValue(e.target.value)}
      />
      <button type="submit">{enter}</button>
    </form>
  )
}

// Why a tab has nothing to show. Kept as a kind rather than a sentence, so the
// sentence follows the language switch instead of staying in whichever language
// the failure happened in.
type Failure = '' | 'store' | 'list'

interface Poll<T> {
  data: T | null
  error: Failure
  checkedAt: string
  fresh: Set<number>
  reload: () => void
}

function idsOf(rows: { id: number }[]): number[] {
  return rows.map((row) => row.id)
}

/** One tab's list: read now, read again every few seconds, mark what is new.
 *
 * `read` and `ids` must not change between renders -- they are module-level
 * functions below -- or the polling restarts on every render.
 */
function useBackOffice<T>(
  read: (token: string) => Promise<T>,
  ids: (data: T) => number[],
  onBadToken: () => void,
): Poll<T> {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<Failure>('')
  const [checkedAt, setCheckedAt] = useState('')
  const [fresh, setFresh] = useState<Set<number>>(new Set())

  // Which rows this tab has already shown. A ref rather than state because it
  // must not be what decides to re-render -- and because the first load has to
  // fill it without marking eight old rows as new. Switching tabs unmounts the
  // tab, so coming back starts it empty again rather than lighting up whatever
  // arrived while another tab was open.
  const seen = useRef<Set<number> | null>(null)

  const load = useCallback(async () => {
    try {
      const got = await read(storedToken())
      setData(got)
      setError('')
      setCheckedAt(new Date().toLocaleTimeString('en-GB'))

      const now = ids(got)
      if (seen.current === null) {
        seen.current = new Set(now)
        return
      }
      const arrived = now.filter((id) => !seen.current!.has(id))
      seen.current = new Set(now)
      if (arrived.length) {
        setFresh((was) => new Set([...was, ...arrived]))
        window.setTimeout(
          () => setFresh((was) => new Set([...was].filter((id) => !arrived.includes(id)))),
          FRESH_MS,
        )
      }
    } catch (failure) {
      const status = failure instanceof ApiError ? failure.status : 0
      if (status === 401) {
        // The one error worth forgetting the token over, so the gate comes back
        // instead of a screen that keeps failing with no way to fix it.
        forgetToken()
        onBadToken()
        return
      }
      // 503 is two different things -- the console has no token configured at
      // all, or the verticals database is down -- and from out here they are
      // indistinguishable. Both leave this screen with nothing on it, and nothing
      // on it during a demo must never be mistaken for "nothing yet".
      setError(status === 503 ? 'store' : 'list')
    }
  }, [read, ids, onBadToken])

  useEffect(() => {
    void load()
    const timer = window.setInterval(() => void load(), POLL_MS)
    return () => window.clearInterval(timer)
  }, [load])

  return { data, error, checkedAt, fresh, reload: () => void load() }
}

/** What a tab says when its list could not be read. */
function failureText(t: Text, tab: AdminTab, error: Failure): string {
  return error === 'store' ? t.storeDown(t.stores[tab]) : t.listDown
}

interface BoardProps {
  t: Text
  onBadToken: () => void
}

function Head<T>({ t, tab, brand, what, poll }: { t: Text; tab: AdminTab; brand: string; what: string; poll: Poll<T> }) {
  return (
    <header className="va-head">
      <div>
        <h1>{brand}</h1>
        <p className="va-dim">
          {what} · {t.backOffice}
        </p>
      </div>
      <div className="va-status">
        {poll.error ? (
          <span className="va-error">{failureText(t, tab, poll.error)}</span>
        ) : (
          <span className="va-dim">{poll.checkedAt ? t.updated(poll.checkedAt) : t.loading}</span>
        )}
        <button type="button" onClick={poll.reload}>
          {t.refresh}
        </button>
      </div>
    </header>
  )
}

/** The table, or why there is none: still loading, unreachable, or truly empty. */
function Rows<T>({
  t,
  tab,
  poll,
  count,
  empty,
  children,
}: {
  t: Text
  tab: AdminTab
  poll: Poll<T>
  count: number
  empty: string
  children: ReactNode
}) {
  if (count > 0) return <div className="va-scroll">{children}</div>
  if (poll.error) return <p className="va-empty va-error">{failureText(t, tab, poll.error)}</p>
  return <p className="va-empty">{poll.data === null ? t.loading : empty}</p>
}

function HeaderRow({ columns }: { columns: string[] }) {
  return (
    <thead>
      <tr>
        {columns.map((column) => (
          <th key={column}>{column}</th>
        ))}
      </tr>
    </thead>
  )
}

// --- 点餐 ----------------------------------------------------------------------

const STAGE_TAGS: Record<FoodOrder['status'], string> = {
  received: 'va-tag',
  preparing: 'va-tag busy',
  on_the_way: 'va-tag moving',
  delivered: 'va-tag ok',
}

function bill(rm: number): string {
  // Cents shown: RM 35.30 is a bill, and a bill rounded to the ringgit is a
  // different number from the one the bot just quoted.
  return `RM ${rm.toFixed(2)}`
}

/** "14:03:11" out of "2026-09-14 14:03:11.842". Sliced, never parsed: the backend
 * sends local time with no offset, and `new Date()` would read it as if it were
 * UTC. See the note on `Viewing.created_at` in api.ts. */
function clock(at: string): string {
  return at.slice(11, 19)
}

/** "09-14 14:03" out of the same. */
function when(at: string): string {
  return at.slice(5, 16)
}

function FoodBoard({ t, onBadToken }: BoardProps) {
  const poll = useBackOffice(readFoodOrders, idsOf, onBadToken)
  const orders = poll.data ?? []
  return (
    <>
      <Head t={t} tab="food" brand="🍜 Nasi Lemak Express" what={t.food.what} poll={poll} />
      <section className="va-panel">
        <h2>
          {t.food.heading} <span className="va-count">{orders.length}</span>
        </h2>
        <Rows t={t} tab="food" poll={poll} count={orders.length} empty={t.food.empty}>
          <table>
            <HeaderRow columns={t.food.columns} />
            <tbody>
              {orders.map((order) => (
                <tr key={order.id} className={poll.fresh.has(order.id) ? 'va-row fresh' : 'va-row'}>
                  <td>
                    <strong>{order.order_no}</strong>
                    <div className="va-dim">{when(order.placed_at)}</div>
                  </td>
                  <td>
                    <strong>{order.customer_name || '—'}</strong>
                    {order.phone && <div className="va-dim">{order.phone}</div>}
                    <div className="va-dim">{order.delivery_address}</div>
                  </td>
                  <td>
                    {order.lines.map((line) => (
                      <div key={line.item_id}>
                        {line.quantity} × {line.name}
                      </div>
                    ))}
                  </td>
                  <td>
                    <strong>{bill(order.total_rm)}</strong>
                    <div className="va-dim">{t.food.delivery(bill(order.delivery_fee_rm))}</div>
                  </td>
                  <td>
                    <span className={STAGE_TAGS[order.status]}>{t.food.stages[order.status]}</span>
                    {/* The whole timeline, so the room can see the kitchen was not
                        a person pressing a button: each stage's time was fixed
                        when the order came in. */}
                    <div className="va-dim">
                      {t.food.timeline(clock(order.placed_at), clock(order.ready_at), clock(order.delivered_at))}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Rows>
      </section>
    </>
  )
}

// --- 房产看房 ------------------------------------------------------------------

function price(rm: number | null): string {
  // Grouped, no cents: every listing is a round number of ringgit and "RM
  // 850,000.00" on a wall is two characters of noise per row.
  return rm == null ? '—' : `RM ${Math.round(rm).toLocaleString('en-MY')}`
}

interface Agency {
  viewings: Viewing[]
  listings: Listing[]
}

async function readAgency(token: string): Promise<Agency> {
  const [viewings, listings] = await Promise.all([readViewings(token), readListings(token)])
  return { viewings, listings }
}

function idsOfViewings(agency: Agency): number[] {
  return idsOf(agency.viewings)
}

function RealEstateBoard({ t, onBadToken }: BoardProps) {
  const poll = useBackOffice(readAgency, idsOfViewings, onBadToken)
  const viewings = poll.data?.viewings ?? []
  const listings = poll.data?.listings ?? []
  return (
    <>
      <Head t={t} tab="realestate" brand="🏡 KL Homes Realty" what={t.realestate.what} poll={poll} />
      <section className="va-panel">
        <h2>
          {t.realestate.heading} <span className="va-count">{viewings.length}</span>
        </h2>
        <Rows t={t} tab="realestate" poll={poll} count={viewings.length} empty={t.realestate.empty}>
          <table>
            <HeaderRow columns={t.realestate.columns} />
            <tbody>
              {viewings.map((viewing) => (
                <tr
                  key={viewing.id}
                  className={poll.fresh.has(viewing.id) ? 'va-row fresh' : 'va-row'}
                >
                  <td className="va-dim">{when(viewing.created_at)}</td>
                  <td>
                    <strong>{viewing.customer_name}</strong>
                    {viewing.phone && <div className="va-dim">{viewing.phone}</div>}
                  </td>
                  <td>
                    <strong>{viewing.listing_id}</strong>
                    <div className="va-dim">
                      {viewing.property_type ?? t.realestate.withdrawn}
                      {viewing.area ? ` · ${viewing.area}` : ''}
                    </div>
                  </td>
                  <td>{price(viewing.price_rm)}</td>
                  <td>
                    {viewing.viewing_date}
                    {viewing.preferred_time && (
                      <div className="va-dim">{viewing.preferred_time}</div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Rows>
      </section>

      <section className="va-panel">
        <h2>
          {t.realestate.listings} <span className="va-count">{listings.length}</span>
        </h2>
        <Rows t={t} tab="realestate" poll={poll} count={listings.length} empty={t.realestate.noListings}>
          <table>
            <HeaderRow columns={t.realestate.listingColumns} />
            <tbody>
              {listings.map((listing) => (
                <tr key={listing.listing_id} className="va-row">
                  <td>
                    <strong>{listing.listing_id}</strong>
                  </td>
                  <td>{listing.property_type}</td>
                  <td>{listing.area}</td>
                  <td>{listing.size_sqft.toLocaleString('en-MY')} sqft</td>
                  <td>{listing.bedrooms}</td>
                  <td>{price(listing.price_rm)}</td>
                  <td>
                    <span className={listing.status === 'Available' ? 'va-tag ok' : 'va-tag'}>
                      {listing.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Rows>
      </section>
    </>
  )
}

// --- 酒店预订 ------------------------------------------------------------------

function rate(rm: number): string {
  // Room rates are whole ringgit, so no cents; a rate that is not still shows
  // what it is rather than being rounded into a different bill.
  return `RM ${rm.toLocaleString('en-MY', { maximumFractionDigits: 2 })}`
}

function HotelBoard({ t, onBadToken }: BoardProps) {
  const poll = useBackOffice(readHotelBookings, idsOf, onBadToken)
  const bookings: HotelBooking[] = poll.data ?? []
  return (
    <>
      <Head t={t} tab="hotel" brand="🏨 Langkawi Breeze Resort" what={t.hotel.what} poll={poll} />
      <section className="va-panel">
        <h2>
          {t.hotel.heading} <span className="va-count">{bookings.length}</span>
        </h2>
        <Rows t={t} tab="hotel" poll={poll} count={bookings.length} empty={t.hotel.empty}>
          <table>
            <HeaderRow columns={t.hotel.columns} />
            <tbody>
              {bookings.map((booking) => (
                <tr
                  key={booking.id}
                  className={poll.fresh.has(booking.id) ? 'va-row fresh' : 'va-row'}
                >
                  <td>
                    <strong>{booking.booking_id}</strong>
                    <div className="va-dim">{when(booking.booked_at)}</div>
                  </td>
                  <td>
                    <strong>{booking.customer_name || '—'}</strong>
                    {booking.phone && <div className="va-dim">{booking.phone}</div>}
                  </td>
                  <td>
                    <strong>{booking.room_type}</strong>
                    <div className="va-dim">{booking.location}</div>
                  </td>
                  <td>
                    {booking.check_in} → {booking.check_out.slice(5)}
                    <div className="va-dim">{t.hotel.stay(booking.nights, booking.guests)}</div>
                  </td>
                  <td>
                    <strong>{rate(booking.total_rm)}</strong>
                    <div className="va-dim">{t.hotel.perNight(rate(booking.rate_per_night_rm))}</div>
                  </td>
                  <td>
                    <span className={booking.status === 'Confirmed' ? 'va-tag ok' : 'va-tag'}>
                      {booking.status === 'Confirmed' ? t.hotel.confirmed : booking.status}
                    </span>
                    {/* A change of dates or room keeps the booking's row and number,
                        so without this a changed booking looks untouched. */}
                    {booking.updated_at && (
                      <div className="va-dim">{t.hotel.changed(when(booking.updated_at))}</div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Rows>
      </section>
    </>
  )
}

// --- SaaS 工单 -----------------------------------------------------------------

const PRIORITY_TAGS: Record<string, string> = {
  urgent: 'va-tag urgent',
  high: 'va-tag busy',
  normal: 'va-tag',
  low: 'va-tag',
}

function SaasBoard({ t, onBadToken }: BoardProps) {
  const poll = useBackOffice(readSupportTickets, idsOf, onBadToken)
  const tickets: SupportTicket[] = poll.data ?? []
  return (
    <>
      <Head t={t} tab="saas" brand="🛠️ CloudDesk Support" what={t.saas.what} poll={poll} />
      <section className="va-panel">
        <h2>
          {t.saas.heading} <span className="va-count">{tickets.length}</span>
        </h2>
        <Rows t={t} tab="saas" poll={poll} count={tickets.length} empty={t.saas.empty}>
          <table>
            <HeaderRow columns={t.saas.columns} />
            <tbody>
              {tickets.map((ticket) => (
                <tr
                  key={ticket.id}
                  className={poll.fresh.has(ticket.id) ? 'va-row fresh' : 'va-row'}
                >
                  <td>
                    <strong>{ticket.ticket_id}</strong>
                    <div className="va-dim">{when(ticket.opened_at)}</div>
                  </td>
                  <td>
                    <strong>{ticket.customer_name || '—'}</strong>
                    {ticket.phone && <div className="va-dim">{ticket.phone}</div>}
                  </td>
                  <td className="va-wide">
                    <strong>{ticket.subject}</strong>
                    <div className="va-dim">{ticket.description}</div>
                  </td>
                  <td>
                    <span className={PRIORITY_TAGS[ticket.priority] ?? 'va-tag'}>
                      {t.saas.priorities[ticket.priority] ?? ticket.priority}
                    </span>
                  </td>
                  <td>
                    <span className="va-tag moving">
                      {ticket.status === 'open' ? t.saas.open : ticket.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Rows>
      </section>
    </>
  )
}

// --- the page --------------------------------------------------------------------

function tabIn(hash: string): AdminTab | null {
  const id = hash.replace(/^#/, '')
  return (TABS as readonly string[]).includes(id) ? (id as AdminTab) : null
}

export default function Admin({ initial = 'food' }: { initial?: AdminTab }) {
  const [tab, setTab] = useState<AdminTab>(() => tabIn(window.location.hash) ?? initial)
  const [unlocked, setUnlocked] = useState(() => storedToken() !== '')
  // Whether the gate should say the last token was refused. A flag rather than
  // the sentence, so the note is in whichever language is picked when it shows.
  const [refused, setRefused] = useState(false)
  const [lang, setLang] = useState<AdminLang>(storedLang)
  const t = TEXT[lang]

  const chooseLang = useCallback((next: AdminLang) => {
    storeLang(next)
    setLang(next)
  }, [])

  useEffect(() => {
    document.documentElement.lang = lang === 'zh' ? 'zh-CN' : 'en'
  }, [lang])

  // The address always says where the page is: an old `/food-admin` becomes
  // `/admin#food`, so what gets bookmarked from here on is the new one.
  useEffect(() => {
    if (window.location.pathname !== '/admin' || tabIn(window.location.hash) !== tab) {
      window.history.replaceState(null, '', `/admin${window.location.search}#${tab}`)
    }
  }, [tab])

  // The tabs are links to `#hotel` and the like, so the back button and an edited
  // address move between tabs the same way a click does.
  useEffect(() => {
    const follow = () => {
      const next = tabIn(window.location.hash)
      if (next) setTab(next)
    }
    window.addEventListener('hashchange', follow)
    return () => window.removeEventListener('hashchange', follow)
  }, [])

  const badToken = useCallback(() => {
    setRefused(true)
    setUnlocked(false)
  }, [])

  if (!unlocked) {
    return (
      <TokenGate
        title={t.gate.title}
        blurb={t.gate.blurb}
        enter={t.gate.enter}
        note={refused ? t.gate.badToken : ''}
        aside={<LangSwitch lang={lang} onChange={chooseLang} />}
        onUnlocked={() => {
          setRefused(false)
          setUnlocked(true)
        }}
      />
    )
  }

  return (
    <div className="va">
      <nav className="va-tabs">
        {TABS.map((id) => (
          <a
            key={id}
            href={`#${id}`}
            className={id === tab ? 'active' : undefined}
            aria-current={id === tab ? 'page' : undefined}
          >
            {t.tabs[id]}
          </a>
        ))}
        <LangSwitch lang={lang} onChange={chooseLang} />
      </nav>
      {tab === 'food' && <FoodBoard t={t} onBadToken={badToken} />}
      {tab === 'realestate' && <RealEstateBoard t={t} onBadToken={badToken} />}
      {tab === 'hotel' && <HotelBoard t={t} onBadToken={badToken} />}
      {tab === 'saas' && <SaasBoard t={t} onBadToken={badToken} />}
    </div>
  )
}
