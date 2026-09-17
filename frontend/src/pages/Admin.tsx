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
const TABS = [
  { id: 'food', label: '🍜 点餐' },
  { id: 'realestate', label: '🏡 房产看房' },
  { id: 'hotel', label: '🏨 酒店预订' },
  { id: 'saas', label: '🛠️ SaaS 工单' },
] as const

export type AdminTab = (typeof TABS)[number]['id']

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

const BAD_TOKEN_NOTE =
  'token 不对。如果是从服务器 .env 复制的，注意值两边不要带引号——docker compose 会把引号也当成 token 的一部分。'

/** The token box.
 *
 * Deliberately not shared with the console's (`Console.tsx` has its own): the
 * part worth sharing -- where the token is kept, and the URL-to-storage hop --
 * is already one implementation in `api.ts`. What is left is a form that has to
 * look like the screen it stands in front of, and this screen is the client's
 * own back office rather than the operator's dark console. The web chat stands
 * behind it too.
 */
export function TokenGate({
  note,
  onUnlocked,
  title,
  blurb,
}: {
  note: string
  onUnlocked: () => void
  title: string
  blurb: string
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
      <button type="submit">进入</button>
    </form>
  )
}

interface Poll<T> {
  data: T | null
  error: string
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
  // Named in the 503 note: "the 酒店 database".
  store: string,
  onBadToken: () => void,
): Poll<T> {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState('')
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
      setError(
        status === 503
          ? `后台暂不可用：${store}数据库连不上，或者后端没配 CONSOLE_TOKEN。`
          : '后台暂不可用：读不到列表。',
      )
    }
  }, [read, ids, store, onBadToken])

  useEffect(() => {
    void load()
    const timer = window.setInterval(() => void load(), POLL_MS)
    return () => window.clearInterval(timer)
  }, [load])

  return { data, error, checkedAt, fresh, reload: () => void load() }
}

function Head<T>({ brand, what, poll }: { brand: string; what: string; poll: Poll<T> }) {
  return (
    <header className="va-head">
      <div>
        <h1>{brand}</h1>
        <p className="va-dim">{what} · 演示后台</p>
      </div>
      <div className="va-status">
        {poll.error ? (
          <span className="va-error">{poll.error}</span>
        ) : (
          <span className="va-dim">{poll.checkedAt ? `已更新 ${poll.checkedAt}` : '读取中…'}</span>
        )}
        <button type="button" onClick={poll.reload}>
          刷新
        </button>
      </div>
    </header>
  )
}

/** The table, or why there is none: still loading, unreachable, or truly empty. */
function Rows<T>({
  poll,
  count,
  empty,
  children,
}: {
  poll: Poll<T>
  count: number
  empty: string
  children: ReactNode
}) {
  if (count > 0) return <div className="va-scroll">{children}</div>
  if (poll.error) return <p className="va-empty va-error">{poll.error}</p>
  return <p className="va-empty">{poll.data === null ? '读取中…' : empty}</p>
}

// --- 点餐 ----------------------------------------------------------------------

const STAGES: Record<FoodOrder['status'], { label: string; tag: string }> = {
  received: { label: '已接单', tag: 'va-tag' },
  preparing: { label: '制作中', tag: 'va-tag busy' },
  on_the_way: { label: '配送中', tag: 'va-tag moving' },
  delivered: { label: '已送达', tag: 'va-tag ok' },
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

function FoodBoard({ onBadToken }: { onBadToken: () => void }) {
  const poll = useBackOffice(readFoodOrders, idsOf, '餐饮', onBadToken)
  const orders = poll.data ?? []
  return (
    <>
      <Head brand="🍜 Nasi Lemak Express" what="外卖订单" poll={poll} />
      <section className="va-panel">
        <h2>
          订单 <span className="va-count">{orders.length}</span>
        </h2>
        <Rows
          poll={poll}
          count={orders.length}
          empty="还没有订单。客户在 WhatsApp 里确认下单后，这一行会自己出现在最上面。"
        >
          <table>
            <thead>
              <tr>
                <th>单号</th>
                <th>客户</th>
                <th>菜品</th>
                <th>金额</th>
                <th>状态</th>
              </tr>
            </thead>
            <tbody>
              {orders.map((order) => {
                const stage = STAGES[order.status]
                return (
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
                      <div className="va-dim">含配送 {bill(order.delivery_fee_rm)}</div>
                    </td>
                    <td>
                      <span className={stage.tag}>{stage.label}</span>
                      {/* The whole timeline, so the room can see the kitchen was not
                          a person pressing a button: each stage's time was fixed
                          when the order came in. */}
                      <div className="va-dim">
                        接单 {clock(order.placed_at)} · 出餐 {clock(order.ready_at)} · 送达{' '}
                        {clock(order.delivered_at)}
                      </div>
                    </td>
                  </tr>
                )
              })}
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

function RealEstateBoard({ onBadToken }: { onBadToken: () => void }) {
  const poll = useBackOffice(readAgency, idsOfViewings, '房产', onBadToken)
  const viewings = poll.data?.viewings ?? []
  const listings = poll.data?.listings ?? []
  return (
    <>
      <Head brand="🏡 KL Homes Realty" what="看房预约" poll={poll} />
      <section className="va-panel">
        <h2>
          看房预约 <span className="va-count">{viewings.length}</span>
        </h2>
        <Rows
          poll={poll}
          count={viewings.length}
          empty="还没有预约。客户在 WhatsApp 里填完表单后，这一行会自己出现在最上面。"
        >
          <table>
            <thead>
              <tr>
                <th>收到</th>
                <th>客户</th>
                <th>房源</th>
                <th>报价</th>
                <th>看房时间</th>
              </tr>
            </thead>
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
                      {viewing.property_type ?? '房源已下架'}
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
          在售房源 <span className="va-count">{listings.length}</span>
        </h2>
        <Rows poll={poll} count={listings.length} empty="没有房源。">
          <table>
            <thead>
              <tr>
                <th>编号</th>
                <th>户型</th>
                <th>地区</th>
                <th>面积</th>
                <th>房间</th>
                <th>价格</th>
                <th>状态</th>
              </tr>
            </thead>
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

function HotelBoard({ onBadToken }: { onBadToken: () => void }) {
  const poll = useBackOffice(readHotelBookings, idsOf, '酒店', onBadToken)
  const bookings: HotelBooking[] = poll.data ?? []
  return (
    <>
      <Head brand="🏨 Langkawi Breeze Resort" what="客房预订" poll={poll} />
      <section className="va-panel">
        <h2>
          预订 <span className="va-count">{bookings.length}</span>
        </h2>
        <Rows
          poll={poll}
          count={bookings.length}
          empty="还没有预订。客人在 WhatsApp 里确认订房后，这一行会自己出现在最上面。"
        >
          <table>
            <thead>
              <tr>
                <th>编号</th>
                <th>客人</th>
                <th>房型</th>
                <th>入住</th>
                <th>金额</th>
                <th>状态</th>
              </tr>
            </thead>
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
                    <div className="va-dim">
                      {booking.nights} 晚 · {booking.guests} 位
                    </div>
                  </td>
                  <td>
                    <strong>{rate(booking.total_rm)}</strong>
                    <div className="va-dim">{rate(booking.rate_per_night_rm)} / 晚</div>
                  </td>
                  <td>
                    <span className={booking.status === 'Confirmed' ? 'va-tag ok' : 'va-tag'}>
                      {booking.status === 'Confirmed' ? '已确认' : booking.status}
                    </span>
                    {/* A change of dates or room keeps the booking's row and number,
                        so without this a changed booking looks untouched. */}
                    {booking.updated_at && (
                      <div className="va-dim">改过 {when(booking.updated_at)}</div>
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

const PRIORITIES: Record<string, { label: string; tag: string }> = {
  urgent: { label: '紧急', tag: 'va-tag urgent' },
  high: { label: '高', tag: 'va-tag busy' },
  normal: { label: '普通', tag: 'va-tag' },
  low: { label: '低', tag: 'va-tag' },
}

function SaasBoard({ onBadToken }: { onBadToken: () => void }) {
  const poll = useBackOffice(readSupportTickets, idsOf, '工单', onBadToken)
  const tickets: SupportTicket[] = poll.data ?? []
  return (
    <>
      <Head brand="🛠️ CloudDesk Support" what="支持工单" poll={poll} />
      <section className="va-panel">
        <h2>
          工单 <span className="va-count">{tickets.length}</span>
        </h2>
        <Rows
          poll={poll}
          count={tickets.length}
          empty="还没有工单。客户在 WhatsApp 里让客服开单后，这一行会自己出现在最上面。"
        >
          <table>
            <thead>
              <tr>
                <th>编号</th>
                <th>客户</th>
                <th>问题</th>
                <th>优先级</th>
                <th>状态</th>
              </tr>
            </thead>
            <tbody>
              {tickets.map((ticket) => {
                const level = PRIORITIES[ticket.priority] ?? {
                  label: ticket.priority,
                  tag: 'va-tag',
                }
                return (
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
                      <span className={level.tag}>{level.label}</span>
                    </td>
                    <td>
                      <span className="va-tag moving">
                        {ticket.status === 'open' ? '待处理' : ticket.status}
                      </span>
                    </td>
                  </tr>
                )
              })}
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
  return TABS.some((tab) => tab.id === id) ? (id as AdminTab) : null
}

export default function Admin({ initial = 'food' }: { initial?: AdminTab }) {
  const [tab, setTab] = useState<AdminTab>(() => tabIn(window.location.hash) ?? initial)
  const [unlocked, setUnlocked] = useState(() => storedToken() !== '')
  const [gateNote, setGateNote] = useState('')

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
    setGateNote(BAD_TOKEN_NOTE)
    setUnlocked(false)
  }, [])

  if (!unlocked) {
    return (
      <TokenGate
        title="🗂️ 演示后台"
        blurb="点餐、看房、酒店、SaaS 工单的演示后台。需要 console token（服务器上的 CONSOLE_TOKEN）。"
        note={gateNote}
        onUnlocked={() => {
          setGateNote('')
          setUnlocked(true)
        }}
      />
    )
  }

  return (
    <div className="va">
      <nav className="va-tabs">
        {TABS.map(({ id, label }) => (
          <a
            key={id}
            href={`#${id}`}
            className={id === tab ? 'active' : undefined}
            aria-current={id === tab ? 'page' : undefined}
          >
            {label}
          </a>
        ))}
      </nav>
      {tab === 'food' && <FoodBoard onBadToken={badToken} />}
      {tab === 'realestate' && <RealEstateBoard onBadToken={badToken} />}
      {tab === 'hotel' && <HotelBoard onBadToken={badToken} />}
      {tab === 'saas' && <SaasBoard onBadToken={badToken} />}
    </div>
  )
}
