import { useCallback, useEffect, useRef, useState } from 'react'
import './VerticalAdmin.css'
import {
  ApiError,
  forgetToken,
  readListings,
  readViewings,
  rememberToken,
  storedToken,
  type Listing,
  type Viewing,
} from '../api'

// How often the back office asks whether anything new came in. The customer
// fills the form in on their phone and looks up at this screen; five seconds is
// the longest gap that still reads as "it just appeared" rather than "someone
// refreshed the page".
const POLL_MS = 5000

// How long a row that has just arrived stays marked. Long enough for a room to
// follow the eye to it, short enough that the screen is not permanently striped
// by the time three bookings are in.
const FRESH_MS = 8000

const BAD_TOKEN_NOTE =
  'token 不对。如果是从服务器 .env 复制的，注意值两边不要带引号——docker compose 会把引号也当成 token 的一部分。'
// 503 is two different things -- the console has no token configured at all, or
// the verticals database is down -- and from out here they are indistinguishable.
// Both leave this screen with nothing on it, and nothing on it during a demo must
// never be mistaken for "no bookings yet", so the message names both.
const STORE_DOWN_NOTE = '读不到后台：房产数据库连不上，或者后端没配 CONSOLE_TOKEN。'

/** The token box.
 *
 * Deliberately not shared with the console's (`History.tsx` has its own): the
 * part worth sharing -- where the token is kept, and the URL-to-storage hop --
 * is already one implementation in `api.ts`. What is left is a form that has to
 * look like the screen it stands in front of, and this screen is the client's
 * own back office rather than the operator's dark console.
 */
function TokenGate({ note, onUnlocked }: { note: string; onUnlocked: () => void }) {
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
      <h2>🏡 KL Homes Realty</h2>
      <p>看房预约后台。需要 console token（服务器上的 CONSOLE_TOKEN）。</p>
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

function money(rm: number | null): string {
  // Grouped, no cents: every listing is a round number of ringgit and "RM
  // 850,000.00" on a wall is two characters of noise per row.
  return rm == null ? '—' : `RM ${Math.round(rm).toLocaleString('en-MY')}`
}

function ViewingRow({ viewing, fresh }: { viewing: Viewing; fresh: boolean }) {
  return (
    <tr className={fresh ? 'va-row fresh' : 'va-row'}>
      {/* Sliced, never parsed: the backend sends local time with no offset, and
          `new Date()` would read it as if it were UTC. See the note on
          `Viewing.created_at` in api.ts. */}
      <td className="va-dim">{viewing.created_at.slice(5, 16)}</td>
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
      <td>{money(viewing.price_rm)}</td>
      <td>
        {viewing.viewing_date}
        {viewing.preferred_time && <div className="va-dim">{viewing.preferred_time}</div>}
      </td>
    </tr>
  )
}

export default function VerticalAdmin() {
  const [unlocked, setUnlocked] = useState(() => storedToken() !== '')
  const [gateNote, setGateNote] = useState('')
  const [viewings, setViewings] = useState<Viewing[]>([])
  const [listings, setListings] = useState<Listing[]>([])
  const [error, setError] = useState('')
  const [checkedAt, setCheckedAt] = useState('')
  const [fresh, setFresh] = useState<Set<number>>(new Set())

  // Which bookings this screen has already shown. A ref rather than state
  // because it must not be what decides to re-render -- and because the first
  // load has to fill it without marking eight old rows as new.
  const seen = useRef<Set<number> | null>(null)

  const load = useCallback(async () => {
    const token = storedToken()
    try {
      const [booked, onBooks] = await Promise.all([readViewings(token), readListings(token)])
      setViewings(booked)
      setListings(onBooks)
      setError('')
      setCheckedAt(new Date().toLocaleTimeString('en-GB'))

      const ids = new Set(booked.map((row) => row.id))
      if (seen.current === null) {
        seen.current = ids
        return
      }
      const arrived = booked.filter((row) => !seen.current!.has(row.id)).map((row) => row.id)
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
        // The one error worth forgetting the token over, so the gate comes back
        // instead of a screen that keeps failing with no way to fix it.
        forgetToken()
        setUnlocked(false)
        setGateNote(BAD_TOKEN_NOTE)
        return
      }
      setError(status === 503 ? STORE_DOWN_NOTE : '读不到预约列表。')
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
          <h1>🏡 KL Homes Realty</h1>
          <p className="va-dim">看房预约 · 演示后台</p>
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
          看房预约 <span className="va-count">{viewings.length}</span>
        </h2>
        {viewings.length === 0 && !error ? (
          <p className="va-empty">
            还没有预约。客户在 WhatsApp 里填完表单后，这一行会自己出现在最上面。
          </p>
        ) : (
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
                <ViewingRow key={viewing.id} viewing={viewing} fresh={fresh.has(viewing.id)} />
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="va-panel">
        <h2>
          在售房源 <span className="va-count">{listings.length}</span>
        </h2>
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
                <td>{money(listing.price_rm)}</td>
                <td>
                  <span className={listing.status === 'Available' ? 'va-tag ok' : 'va-tag'}>
                    {listing.status}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  )
}
