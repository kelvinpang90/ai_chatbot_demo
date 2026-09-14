import { useCallback, useEffect, useState } from 'react'
import {
  ApiError,
  listConversations,
  listCustomers,
  type ConversationSummary,
  type CustomerSummary,
} from '../api'
import { money } from '../transcript'

// The console's left side (task 37.6, one row per customer since task 37.7).
//
// It used to be a row per conversation, and one number that demoed a dozen times
// filled the list with a dozen rows of the same name. Now a customer is one row,
// and opening it lists their conversations, newest first, a page at a time.

// Ten seconds: the live feed already shows the moment someone starts, so this
// only has to put their row in reach -- the customer who has just picked a demo
// on their phone is the one the operator wants to click.
const LIST_POLL_MS = 10000

// How many of one customer's conversations to show before "加载更早". The owner's
// own number had a dozen within a week of testing; twenty covers a real customer
// whole and keeps a long-lived number from arriving as one enormous list.
const PAGE_SIZE = 20

/** Who to show on the right: everybody's live feed, or one conversation. */
export type ConsoleView =
  | { kind: 'all' }
  | { kind: 'customer'; conversationId: string; keyId: string; name: string }

/** One customer's conversations as far as they have been loaded. */
interface Opened {
  keyId: string
  conversations: ConversationSummary[]
  // Whether the last page came back full, which is the only sign there may be more.
  more: boolean
  loadingOlder: boolean
}

/**
 * Fold a fresh first page into what is already loaded, newest first.
 *
 * The refresh only re-reads the first page, so older pages the operator asked for
 * stay. A conversation that started since pushes the rest down, so the next
 * "加载更早" can return one already shown -- deduplicated here -- but never skips one.
 */
function merged(fresh: ConversationSummary[], loaded: ConversationSummary[]): ConversationSummary[] {
  const byId = new Map<string, ConversationSummary>()
  for (const row of [...loaded, ...fresh]) byId.set(row.conversation_id, row)
  return [...byId.values()].sort((a, b) => b.last_at.localeCompare(a.last_at))
}

export function CustomerList({
  token,
  view,
  onSelect,
  onRefused,
}: {
  token: string
  view: ConsoleView
  onSelect: (view: ConsoleView) => void
  // The token was not accepted. The console owns the gate, so it decides.
  // Must be stable (useCallback): the polling below restarts when it changes.
  onRefused: (status: number) => void
}) {
  const [search, setSearch] = useState('')
  const [customers, setCustomers] = useState<CustomerSummary[]>([])
  const [error, setError] = useState('')
  const [loaded, setLoaded] = useState(false)
  const [opened, setOpened] = useState<Opened | null>(null)
  const openedKey = opened?.keyId ?? null

  // Stable as long as `onRefused` is, so the polling below keys on it honestly.
  const failed = useCallback(
    (failure: unknown) => {
      const status = failure instanceof ApiError ? failure.status : 0
      if (status === 401 || status === 503) {
        onRefused(status)
        return
      }
      // Kept, not cleared: a refresh that failed once should not empty a list the
      // operator is about to click on.
      setError(failure instanceof ApiError ? failure.message : '读不到记录')
    },
    [onRefused],
  )

  useEffect(() => {
    let stale = false
    const load = () =>
      listCustomers(token, search)
        .then((page) => {
          if (stale) return
          setCustomers(page.customers)
          setError('')
        })
        .catch((failure: unknown) => !stale && failed(failure))
        .finally(() => !stale && setLoaded(true))
    load()
    const timer = window.setInterval(load, LIST_POLL_MS)
    return () => {
      stale = true
      window.clearInterval(timer)
    }
  }, [token, search, failed])

  // The opened customer's newest page, on the same beat: a demo they start while
  // the operator is looking should appear at the top without closing and reopening.
  useEffect(() => {
    if (!openedKey) return
    let stale = false
    const refresh = () =>
      listConversations(token, openedKey, 0, PAGE_SIZE)
        .then((page) => {
          if (stale) return
          setOpened((current) =>
            current && current.keyId === openedKey
              ? {
                  ...current,
                  conversations: merged(page.conversations, current.conversations),
                  // Only a first read decides "more"; after that, "加载更早" does.
                  more:
                    current.conversations.length === 0
                      ? page.conversations.length === PAGE_SIZE
                      : current.more,
                }
              : current,
          )
        })
        .catch((failure: unknown) => !stale && failed(failure))
    refresh()
    const timer = window.setInterval(refresh, LIST_POLL_MS)
    return () => {
      stale = true
      window.clearInterval(timer)
    }
  }, [token, openedKey, failed])

  function toggle(customer: CustomerSummary) {
    setOpened((current) =>
      current?.keyId === customer.key_id
        ? null
        : { keyId: customer.key_id, conversations: [], more: false, loadingOlder: false },
    )
  }

  function loadOlder() {
    if (!opened || opened.loadingOlder) return
    const { keyId, conversations } = opened
    setOpened({ ...opened, loadingOlder: true })
    listConversations(token, keyId, conversations.length, PAGE_SIZE)
      .then((page) =>
        setOpened((current) =>
          current && current.keyId === keyId
            ? {
                ...current,
                conversations: merged(page.conversations, current.conversations),
                more: page.conversations.length === PAGE_SIZE,
                loadingOlder: false,
              }
            : current,
        ),
      )
      .catch((failure: unknown) => {
        setOpened((current) => (current ? { ...current, loadingOlder: false } : current))
        failed(failure)
      })
  }

  return (
    <aside className="history-list">
      <button
        className={`history-row ${view.kind === 'all' ? 'active' : ''}`}
        onClick={() => onSelect({ kind: 'all' })}
      >
        <div className="history-row-top">
          <strong>跟随最新对话</strong>
        </div>
        <div className="history-row-meta">谁最近在聊就显示谁，投屏用</div>
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
      {loaded && !error && customers.length === 0 && <p className="history-note">没有记录。</p>}

      {customers.map((customer) => {
        const isOpen = openedKey === customer.key_id
        const name = customer.display_name || customer.key_id
        return (
          <div key={customer.key_id} className="history-customer">
            <button
              className={`history-row ${
                view.kind === 'customer' && view.keyId === customer.key_id ? 'active' : ''
              }`}
              aria-expanded={isOpen}
              onClick={() => toggle(customer)}
            >
              <div className="history-row-top">
                <strong>{name}</strong>
                {customer.channels.map((channel) => (
                  <span key={channel} className="pill">
                    {channel}
                  </span>
                ))}
                <span className="history-caret">{isOpen ? '▾' : '▸'}</span>
              </div>
              <div className="history-row-meta">
                {customer.last_at.slice(0, 16)} · {customer.conversations} 通对话 ·{' '}
                {customer.bots.join(' / ')}
              </div>
              <div className="history-row-meta">
                {customer.messages} 条 · {customer.tool_calls} 次工具 · {money(customer.cost_myr)}
              </div>
            </button>

            {isOpen && opened && (
              <div className="history-conversations">
                {opened.conversations.length === 0 && (
                  <p className="history-note">读取对话…</p>
                )}
                {opened.conversations.map((row) => (
                  <button
                    key={row.conversation_id}
                    className={`history-conversation ${
                      view.kind === 'customer' && view.conversationId === row.conversation_id
                        ? 'active'
                        : ''
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
                      <span>{row.last_at.slice(5, 16)}</span>
                      <span className="pill">{row.bot_id}</span>
                    </div>
                    <div className="history-row-meta">
                      {row.messages} 条 · {row.tool_calls} 次工具 · {money(row.cost_myr)}
                    </div>
                  </button>
                ))}
                {opened.more && (
                  <button
                    className="history-more"
                    disabled={opened.loadingOlder}
                    onClick={loadOlder}
                  >
                    {opened.loadingOlder ? '读取中…' : '加载更早'}
                  </button>
                )}
              </div>
            )}
          </div>
        )
      })}
    </aside>
  )
}
