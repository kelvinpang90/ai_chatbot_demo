import { useEffect, useState } from 'react'
import { readFoodOrders, readViewings, type FoodOrder, type Viewing } from '../api'
import { klEpoch, klTime, type Write } from '../consoleCards'

// The console's lower right (task 27, layout B): what the back office looks like
// now, for this conversation only. Food and property are read from their own
// back offices, so a row moving from 制作中 to 配送中 is the database's word, not
// the bot's. Retail has no endpoint of its own here -- its ERP and CRM changes
// are only what the tool calls wrote, and that is what the list shows.

const POLL_MS = 5000
// An order or viewing belongs to this conversation if it was made after the
// conversation's first message. A minute of slack for the gap between the
// audit log's clock and the vertical's, which are separate writes.
const SLACK_SECONDS = 60

const STAGES: { status: FoodOrder['status']; label: string; at: keyof FoodOrder }[] = [
  { status: 'received', label: '已接单', at: 'placed_at' },
  { status: 'preparing', label: '制作中', at: 'preparing_at' },
  { status: 'on_the_way', label: '配送中', at: 'ready_at' },
  { status: 'delivered', label: '已送达', at: 'delivered_at' },
]

const TITLES: Record<string, string> = {
  food: '后台 · 餐厅订单',
  realestate: '后台 · 看房预约与 CRM',
  retail: '后台 · ERP 与 CRM 写入',
  hotel: '后台 · 订房',
  saas: '后台 · 工单',
}

/** The last nine digits: enough to tell two Malaysian numbers apart in any spelling. */
function tail(phone: string): string {
  return phone.replace(/\D/g, '').slice(-9)
}

function useBackOffice<T>(
  enabled: boolean,
  token: string,
  read: (token: string) => Promise<T[]>,
): { rows: T[]; failed: boolean } {
  const [rows, setRows] = useState<T[]>([])
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    if (!enabled) return
    let stale = false
    const load = () =>
      read(token)
        .then((got) => {
          if (stale) return
          setRows(got)
          setFailed(false)
        })
        // Kept, not cleared: a blip should not empty a table the room is reading.
        .catch(() => !stale && setFailed(true))
    load()
    const timer = window.setInterval(load, POLL_MS)
    return () => {
      stale = true
      window.clearInterval(timer)
    }
  }, [enabled, token, read])
  return { rows, failed }
}

export function BackOffice({
  token,
  botId,
  keyId,
  startedAt,
  writes,
}: {
  token: string
  botId: string
  keyId: string
  // Epoch seconds of the conversation's first message.
  startedAt: number
  writes: (Write & { at: number })[]
}) {
  const food = useBackOffice(botId === 'food', token, readFoodOrders)
  const viewings = useBackOffice(botId === 'realestate', token, readViewings)
  const since = startedAt - SLACK_SECONDS

  const orders = food.rows.filter(
    (order) => order.customer_key === keyId && klEpoch(order.placed_at) >= since,
  )
  const booked = viewings.rows.filter(
    (viewing: Viewing) =>
      tail(viewing.phone) !== '' &&
      tail(viewing.phone) === tail(keyId) &&
      klEpoch(viewing.created_at) >= since,
  )
  const failed = food.failed || viewings.failed
  const empty = orders.length === 0 && booked.length === 0 && writes.length === 0

  return (
    <section className="cx-backoffice">
      <div className="cx-pane-label">{TITLES[botId] ?? '后台 · 数据变化'}</div>
      {failed && <p className="cx-note">读不到后台，下面是上一次读到的</p>}
      {empty && <p className="cx-empty">这段对话还没有改动后台数据</p>}

      {orders.length > 0 && (
        <div className="cx-table-scroll">
          <table className="cx-table">
            <thead>
              <tr>
                <th>单号</th>
                <th>菜品</th>
                <th>金额</th>
                <th>状态流转</th>
              </tr>
            </thead>
            <tbody>
              {orders.map((order) => {
                const reached = STAGES.findIndex((stage) => stage.status === order.status)
                return (
                  <tr key={order.id}>
                    <td className="cx-ref">{order.order_no}</td>
                    <td>{order.lines.map((line) => `${line.name} ×${line.quantity}`).join('、')}</td>
                    <td className="cx-num">RM {order.total_rm.toFixed(2)}</td>
                    <td>
                      <span className="cx-stages">
                        {STAGES.map((stage, i) => (
                          <span
                            key={stage.status}
                            className="cx-stage"
                            data-state={i < reached ? 'past' : i === reached ? 'now' : 'next'}
                            data-status={stage.status}
                          >
                            {stage.label}
                            {i <= reached && order[stage.at] && (
                              <small>{klTime(klEpoch(String(order[stage.at])))}</small>
                            )}
                          </span>
                        ))}
                      </span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {booked.length > 0 && (
        <div className="cx-table-scroll">
          <table className="cx-table">
            <thead>
              <tr>
                <th>预约</th>
                <th>客户</th>
                <th>房源</th>
                <th>看房时间</th>
                <th>登记于</th>
              </tr>
            </thead>
            <tbody>
              {booked.map((viewing) => (
                <tr key={viewing.id}>
                  <td className="cx-ref">#{viewing.id}</td>
                  <td>{viewing.customer_name}</td>
                  <td>
                    {viewing.listing_id}
                    <div className="cx-dim">
                      {viewing.property_type ? `${viewing.property_type} · ${viewing.area}` : '房源已下架'}
                    </div>
                  </td>
                  <td>
                    {viewing.viewing_date} {viewing.preferred_time}
                  </td>
                  <td className="cx-time">{klTime(klEpoch(viewing.created_at))}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {writes.length > 0 && (
        <ul className="cx-writes">
          {writes.map((write, i) => (
            <li key={`${write.ref}:${i}`}>
              <span className="cx-plus">新增</span>
              <span className="cx-sysname">{write.system}</span>
              <span className="cx-ref">{write.ref}</span>
              <span className="cx-dim">{write.detail}</span>
              <span className="cx-time">{klTime(write.at)}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
