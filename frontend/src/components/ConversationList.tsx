import { useEffect, useState } from 'react'
import { ApiError, listConversations, type ConversationSummary } from '../api'
import { money } from '../transcript'

// Moved here from pages/History.tsx (task 37.6). On the console it has to keep up:
// the customer who has just picked a demo on their phone is the one the operator
// wants to click on, and a list that only changed on a search would not have them.
// Ten seconds because the live feed already shows the moment they start -- this
// only has to put their row in reach.
const LIST_POLL_MS = 10000

/** Who to show on the right: everybody's live feed, or one conversation. */
export type ConsoleView =
  | { kind: 'all' }
  | { kind: 'customer'; conversationId: string; keyId: string; name: string }

export function ConversationList({
  token,
  view,
  onSelect,
  onRefused,
}: {
  token: string
  view: ConsoleView
  onSelect: (view: ConsoleView) => void
  // The token was not accepted. The console owns the gate, so it decides.
  onRefused: (status: number) => void
}) {
  const [search, setSearch] = useState('')
  const [conversations, setConversations] = useState<ConversationSummary[]>([])
  const [error, setError] = useState('')
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    let stale = false
    const load = () =>
      listConversations(token, search)
        .then((page) => {
          if (stale) return
          setConversations(page.conversations)
          setError('')
        })
        .catch((failure: unknown) => {
          if (stale) return
          const status = failure instanceof ApiError ? failure.status : 0
          if (status === 401 || status === 503) {
            onRefused(status)
            return
          }
          // Kept, not cleared: a refresh that failed once should not empty a list
          // the operator is about to click on.
          setError(failure instanceof ApiError ? failure.message : '读不到记录')
        })
        .finally(() => !stale && setLoaded(true))
    load()
    const timer = window.setInterval(load, LIST_POLL_MS)
    return () => {
      stale = true
      window.clearInterval(timer)
    }
    // `onRefused` must be stable (useCallback in the console): a fresh one per
    // render would restart this polling every time a live event arrived.
  }, [token, search, onRefused])

  return (
    <aside className="history-list">
      <button
        className={`history-row ${view.kind === 'all' ? 'active' : ''}`}
        onClick={() => onSelect({ kind: 'all' })}
      >
        <div className="history-row-top">
          <strong>全部 · 实时流</strong>
        </div>
        <div className="history-row-meta">所有顾客的工具调用混在一起，投屏用</div>
      </button>

      <form
        className="history-search"
        onSubmit={(e) => {
          e.preventDefault()
          const term = new FormData(e.currentTarget).get('term')
          setSearch(String(term ?? ''))
        }}
      >
        <input name="term" placeholder="手机号，任意写法" defaultValue={search} />
        <button type="submit">查</button>
      </form>

      {!loaded && <p className="history-note">读取中…</p>}
      {error && <p className="history-note error">{error}</p>}
      {loaded && !error && conversations.length === 0 && (
        <p className="history-note">没有记录。</p>
      )}

      {conversations.map((row) => (
        <button
          key={row.conversation_id}
          className={`history-row ${
            view.kind === 'customer' && view.conversationId === row.conversation_id ? 'active' : ''
          }`}
          onClick={() =>
            onSelect({
              kind: 'customer',
              conversationId: row.conversation_id,
              keyId: row.key_id,
              name: row.display_name || row.key_id,
            })
          }
        >
          <div className="history-row-top">
            <strong>{row.display_name || row.key_id}</strong>
            <span className="pill">{row.channel}</span>
          </div>
          <div className="history-row-meta">
            {row.last_at.slice(0, 16)} · {row.bot_id}
          </div>
          <div className="history-row-meta">
            {row.messages} 条 · {row.tool_calls} 次工具 · {money(row.cost_myr)}
          </div>
        </button>
      ))}
    </aside>
  )
}
