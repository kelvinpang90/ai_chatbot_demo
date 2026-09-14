import { useCallback, useEffect, useRef, useState } from 'react'
import './VerticalAdmin.css'
import { TokenGate } from './VerticalAdmin'
import { ApiError, forgetToken, readFoodOrders, storedToken, type FoodOrder } from '../api'

// Same cadence as the property back office, and here it does a second job: the
// status is read off each order's timeline by the backend, so every poll is also
// the moment a row can move from "制作中" to "配送中" -- ideally just before the
// customer's phone buzzes with the same news.
const POLL_MS = 5000
const FRESH_MS = 8000

const BAD_TOKEN_NOTE =
  'token 不对。如果是从服务器 .env 复制的，注意值两边不要带引号——docker compose 会把引号也当成 token 的一部分。'
const STORE_DOWN_NOTE = '读不到后台：餐饮数据库连不上，或者后端没配 CONSOLE_TOKEN。'

const STAGES: Record<FoodOrder['status'], { label: string; tag: string }> = {
  received: { label: '已接单', tag: 'va-tag' },
  preparing: { label: '制作中', tag: 'va-tag busy' },
  on_the_way: { label: '配送中', tag: 'va-tag moving' },
  delivered: { label: '已送达', tag: 'va-tag ok' },
}

function money(rm: number): string {
  // Cents shown, unlike the property page: RM 35.30 is a bill, and a bill rounded
  // to the ringgit is a different number from the one the bot just quoted.
  return `RM ${rm.toFixed(2)}`
}

/** "14:03:11" out of "2026-09-14 14:03:11.842". Sliced, never parsed. */
function clock(at: string): string {
  return at.slice(11, 19)
}

function OrderRow({ order, fresh }: { order: FoodOrder; fresh: boolean }) {
  const stage = STAGES[order.status]
  return (
    <tr className={fresh ? 'va-row fresh' : 'va-row'}>
      <td>
        <strong>{order.order_no}</strong>
        <div className="va-dim">{order.placed_at.slice(5, 16)}</div>
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
        <strong>{money(order.total_rm)}</strong>
        <div className="va-dim">含配送 {money(order.delivery_fee_rm)}</div>
      </td>
      <td>
        <span className={stage.tag}>{stage.label}</span>
        {/* The whole timeline, so the room can see the kitchen was not a person
            pressing a button: each stage's time was fixed when the order came in. */}
        <div className="va-dim">
          接单 {clock(order.placed_at)} · 出餐 {clock(order.ready_at)} · 送达{' '}
          {clock(order.delivered_at)}
        </div>
      </td>
    </tr>
  )
}

export default function FoodAdmin() {
  const [unlocked, setUnlocked] = useState(() => storedToken() !== '')
  const [gateNote, setGateNote] = useState('')
  const [orders, setOrders] = useState<FoodOrder[]>([])
  const [error, setError] = useState('')
  const [checkedAt, setCheckedAt] = useState('')
  const [fresh, setFresh] = useState<Set<number>>(new Set())
  // Which orders this screen has already shown; see the same ref in VerticalAdmin.
  const seen = useRef<Set<number> | null>(null)

  const load = useCallback(async () => {
    try {
      const rows = await readFoodOrders(storedToken())
      setOrders(rows)
      setError('')
      setCheckedAt(new Date().toLocaleTimeString('en-GB'))

      const ids = new Set(rows.map((row) => row.id))
      if (seen.current === null) {
        seen.current = ids
        return
      }
      const arrived = rows.filter((row) => !seen.current!.has(row.id)).map((row) => row.id)
      seen.current = ids
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
        forgetToken()
        setUnlocked(false)
        setGateNote(BAD_TOKEN_NOTE)
        return
      }
      setError(status === 503 ? STORE_DOWN_NOTE : '读不到订单列表。')
    }
  }, [])

  useEffect(() => {
    if (!unlocked) return
    void load()
    const timer = window.setInterval(() => void load(), POLL_MS)
    return () => window.clearInterval(timer)
  }, [unlocked, load])

  if (!unlocked) {
    return (
      <TokenGate
        title="🍜 Nasi Lemak Express"
        blurb="外卖订单后台。需要 console token（服务器上的 CONSOLE_TOKEN）。"
        note={gateNote}
        onUnlocked={() => {
          setGateNote('')
          seen.current = null
          setUnlocked(true)
        }}
      />
    )
  }

  return (
    <div className="va">
      <header className="va-head">
        <div>
          <h1>🍜 Nasi Lemak Express</h1>
          <p className="va-dim">外卖订单 · 演示后台</p>
        </div>
        <div className="va-status">
          {error ? (
            <span className="va-error">{error}</span>
          ) : (
            <span className="va-dim">{checkedAt ? `已更新 ${checkedAt}` : '读取中…'}</span>
          )}
          <button type="button" onClick={() => void load()}>
            刷新
          </button>
        </div>
      </header>

      <section className="va-panel">
        <h2>
          订单 <span className="va-count">{orders.length}</span>
        </h2>
        {orders.length === 0 && !error ? (
          <p className="va-empty">还没有订单。客户在 WhatsApp 里确认下单后，这一行会自己出现在最上面。</p>
        ) : (
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
              {orders.map((order) => (
                <OrderRow key={order.id} order={order} fresh={fresh.has(order.id)} />
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  )
}
