import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import './Console.css'
import {
  ApiError,
  consoleStreamUrl,
  forgetToken,
  readConversation,
  readHandovers,
  readToolSwitch,
  rememberToken,
  replyAsHuman,
  sendDemoSummary,
  setHandover,
  setToolSwitch,
  storedToken,
  type ConsoleEvent,
  type ConversationDetail,
  type HandoverCustomer,
} from '../api'
import { ConversationList, type ConsoleView } from '../components/ConversationList'
import { Transcript } from '../components/Transcript'
import { toolUseIds } from '../transcript'

// How many times to let a stream that has never opened fail before giving up on
// it. Once it has opened, failures are the backend's, not the token's.
const MAX_FAILED_ATTEMPTS = 3

// How long to wait before rebuilding a stream the server dropped. Long enough
// not to hammer a backend that is still coming up, short enough that a redeploy
// mid-demo costs a few seconds rather than the operator's attention.
const RECONNECT_DELAY_MS = 3000

// How often the console asks who is in a person's hands. The feed shows the
// moment it happens; this is what keeps the banner honest afterwards, including
// across a reconnect or a redeploy that empties the event buffer.
const HANDOVER_POLL_MS = 5000

// What WhatsApp will carry in one message. The backend clips past it rather than
// refusing, so without this the operator's last sentence would simply not arrive
// and nothing on either screen would say why.
const MAX_REPLY_CHARS = 4096

const POLL_FAILED = '读不到人工接管的状态'

// How often one customer's transcript is read again while they are selected
// (task 37.6). The live feed shows their tool calls the moment they happen; this
// is what brings in what was *said* -- the feed carries no messages -- and what
// the database has priced. Same beat as the handover poll.
const TRANSCRIPT_POLL_MS = 5000

// Carried over from the transcript page this screen absorbed (task 37.6).
const BAD_TOKEN_NOTE =
  'token 不对。如果是从服务器 .env 复制的，注意值两边不要带引号——docker compose 会把引号也当成 token 的一部分。'
const NOT_CONFIGURED_NOTE = '后端没有配 CONSOLE_TOKEN，这个页面打不开。'

// How long the same enquiry takes a person. Not measured, deliberately
// conservative, and on screen because "it is fast" means nothing next to a
// number the owner can compare against a salary.
const HUMAN_MINUTES = 3

type Connection = 'connecting' | 'live' | 'error'

// React needs a key that is unique for the life of the list. The tool_use_id is
// not it: ids come from whichever backend process is running, and one that
// restarts mid-demo can hand out an id a row above already carries.
let nextRowKey = 1

/** One tool call, both halves of it, as a single line on the screen. */
interface ToolRow {
  key: number
  id: string
  seq: number
  at: number
  tool: string
  input: Record<string, unknown> | null
  output: string | null
  durationMs: number | null
  // 'note' is not a call at all: it is the control switch being thrown, which
  // earns a line because the stretch of demo where nothing is called has to be
  // told apart from the stretch where nothing was asked.
  status: 'ok' | 'error' | 'running' | 'note'
  // Whose call it was (task 37.6). Blank for what belongs to nobody, which is
  // then shown on the everybody feed only.
  keyId: string
}

function formatTime(at: number): string {
  return new Date(at * 1000).toLocaleTimeString('en-GB', { hour12: false })
}

function formatRinggit(total: number): string {
  // Below one sen, two decimals reads as free and looks broken. Four decimals
  // reads as a real, very small number, which is the actual point being made.
  return `RM ${total.toFixed(total > 0 && total < 0.01 ? 4 : 2)}`
}

function preview(text: string, limit: number, expanded: boolean): string {
  if (expanded || text.length <= limit) return text
  return `${text.slice(0, limit)}…`
}

/**
 * The director's console: what the bot actually did, while the customer is
 * looking at a chat bubble on their phone.
 */
export default function Console() {
  const [token, setToken] = useState(storedToken)
  const [draftToken, setDraftToken] = useState('')
  const [gateNote, setGateNote] = useState('')
  // Bumped to build a fresh EventSource after the server dropped the old one.
  const [attempt, setAttempt] = useState(0)
  const [connection, setConnection] = useState<Connection>('connecting')
  const [rows, setRows] = useState<ToolRow[]>([])
  const [costMyr, setCostMyr] = useState(0)
  // Whether the bots still have their tools. `null` until the backend says, so
  // the switch cannot start out claiming a position it has not been told.
  const [toolsEnabled, setToolsEnabled] = useState<boolean | null>(null)
  const [switchNote, setSwitchNote] = useState('')
  // Closing the demo off. In flight rather than a plain boolean's worth of
  // "done", because the button sends a real message to a real phone and a
  // nervous double-click would send two.
  const [closing, setClosing] = useState(false)
  const [closingNote, setClosingNote] = useState('')
  // Who a person has taken off the bot, and what they are typing to them.
  const [held, setHeld] = useState<HandoverCustomer[]>([])
  const [draftReply, setDraftReply] = useState('')
  const [sending, setSending] = useState(false)
  const [handoverNote, setHandoverNote] = useState('')
  // Which of several taken-over customers the everybody view's panel is on. Named
  // apart from `view` below: that one is which customer the whole screen is on.
  const [heldPick, setHeldPick] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<Set<number>>(new Set())
  // Everybody's live feed, or one customer's console (task 37.6).
  const [view, setView] = useState<ConsoleView>({ kind: 'all' })
  // That customer's past, as the audit log has it. Re-read while they are on
  // screen; cleared the moment the view changes, so one customer's transcript is
  // never shown under another's name while the next one loads.
  const [detail, setDetail] = useState<ConversationDetail | null>(null)
  const [detailNote, setDetailNote] = useState('')
  const feedRef = useRef<HTMLDivElement>(null)
  // Replay re-sends the whole buffer every time a stream opens, so the same
  // event arrives again after a reconnect. Sequence numbers make that harmless -
  // but only if they outlive the stream that saw them first, or a redeploy
  // mid-demo doubles every row on the screen and every sen on the total.
  const seenRef = useRef<Set<number>>(new Set())
  // Which run of the backend the sequence numbers in `seenRef` came from.
  const bootRef = useRef<string | null>(null)
  // The token this console has actually got a stream out of. Kept outside the
  // effect on purpose: a per-EventSource flag resets on every retry, so a
  // backend down for longer than one retry would look like a bad token again
  // and throw away a token we have proof is good.
  const provenTokenRef = useRef<string | null>(null)

  useEffect(() => {
    if (!token) return

    const seen = seenRef.current
    const proven = () => provenTokenRef.current === token
    let failures = 0
    let retryTimer: number | undefined
    const source = new EventSource(consoleStreamUrl(token))

    // The first frame of every stream names the backend process behind it. A
    // different one means the sequence numbers started over, so what we remember
    // seeing is about a run that no longer exists - keeping it would make every
    // event after a redeploy look like one we had already shown.
    function hello(raw: MessageEvent) {
      const { boot_id } = JSON.parse(raw.data) as { boot_id: string }
      if (bootRef.current !== boot_id) {
        seen.clear()
        bootRef.current = boot_id
      }
    }

    function apply(raw: MessageEvent) {
      const event = JSON.parse(raw.data) as ConsoleEvent
      if (seen.has(event.seq)) return
      seen.add(event.seq)

      if (event.type === 'usage') {
        setCostMyr((total) => total + (event.cost_myr ?? 0))
        return
      }

      // The switch may have been thrown from another screen, or by this one;
      // either way the stream is what says where it now stands. The event also
      // gets a line in the feed below, so read it and carry on.
      if (event.type === 'tools_switched') {
        setToolsEnabled(event.status === 'on')
        setSwitchNote('')
      }

      setRows((current) => mergeEvent(current, event))
    }

    source.onopen = () => {
      failures = 0
      provenTokenRef.current = token
      setConnection('live')
    }
    function giveUp(why: string) {
      source.close()
      // Forget the token too, or a refresh quietly retries the same bad one and
      // lands back here a few seconds later with no explanation.
      forgetToken()
      setGateNote(why)
      setToken('')
    }

    source.onerror = () => {
      setConnection('error')

      // Any non-2xx closes the stream for good - EventSource never retries one,
      // so this fires exactly once and "reconnecting..." would be a lie. But a
      // 401 and the 502 from a backend that is redeploying look identical here,
      // and only one of them is the token's fault. Whether this token has ever
      // got a stream out of the server is what tells them apart: a token that
      // worked a minute ago has not gone bad because the backend restarted.
      if (source.readyState === EventSource.CLOSED) {
        if (!proven()) {
          giveUp('订阅被拒绝：token 不对，或者后端没有配 CONSOLE_TOKEN。')
          return
        }
        source.close()
        retryTimer = window.setTimeout(() => setAttempt((n) => n + 1), RECONNECT_DELAY_MS)
        return
      }

      // Still CONNECTING: the browser is retrying on its own, which is the
      // right thing once we know the token works.
      if (proven()) return
      failures += 1
      if (failures >= MAX_FAILED_ATTEMPTS) {
        giveUp('连不上后端，试了几次都没成。')
      }
    }
    source.addEventListener('hello', hello as EventListener)
    for (const type of ['tool_start', 'tool_end', 'send_failed', 'usage', 'tools_switched']) {
      source.addEventListener(type, apply as EventListener)
    }

    return () => {
      window.clearTimeout(retryTimer)
      source.close()
    }
    // `attempt` is not read here - bumping it is how a dropped stream asks for
    // a whole new EventSource, since a closed one cannot be revived.
  }, [token, attempt])

  useEffect(() => {
    // Where the switch stands right now. The stream only carries it being
    // thrown, so a screen opened after the fact would otherwise have to guess -
    // and guessing "on" while the bots are gagged is the one wrong answer.
    if (!token) return
    let stale = false
    readToolSwitch(token)
      .then(({ enabled }) => !stale && setToolsEnabled(enabled))
      .catch(() => !stale && setSwitchNote('读不到工具开关的状态'))
    return () => {
      stale = true
    }
  }, [token])

  const statusText = useMemo(
    () =>
      ({
        connecting: '连接中…',
        live: '● 实时',
        error: '连接中断，重试中…',
      })[connection],
    [connection],
  )

  function flipTools() {
    if (toolsEnabled === null) return
    const next = !toolsEnabled
    // Not set optimistically: a switch that snaps across and then quietly snaps
    // back is worse than one that takes a moment, and this one is thrown in
    // front of a customer who is being asked to trust what the screen says.
    setToolSwitch(token, next)
      .then(({ enabled }) => {
        setToolsEnabled(enabled)
        setSwitchNote('')
      })
      .catch(() => setSwitchNote('开关没拨动，后端没接受'))
  }

  useEffect(() => {
    if (!token) return
    let stale = false
    const ask = () =>
      readHandovers(token)
        .then(({ customers }) => {
          if (stale) return
          setHeld(customers)
          // A selection that has been handed back stops being a selection. Left
          // set, `holding` silently falls through to whoever is next on the list
          // -- which can happen between a keystroke and Enter, because this runs
          // every five seconds.
          setHeldPick((current) =>
            current && customers.some((c) => c.key_id === current) ? current : null,
          )
          // A poll that worked clears a note left by one that did not, or a
          // single blip pins the error string there for the rest of the session.
          setHandoverNote((note) => (note === POLL_FAILED ? '' : note))
        })
        .catch(() => !stale && setHandoverNote(POLL_FAILED))
    ask()
    const timer = window.setInterval(ask, HANDOVER_POLL_MS)
    return () => {
      stale = true
      window.clearInterval(timer)
    }
  }, [token])

  // Whoever is selected, defaulting to the newest -- the backend sorts them that
  // way now. A picker rather than `held[0]` alone because anybody past the first
  // was silent to the bot and invisible here, which a cold review of task 20
  // pointed out is not hypothetical: one conversation nobody handed back last
  // week is enough to make the default wrong for every demo after it.
  const holdingAny = held.find((c) => c.key_id === heldPick) ?? held[0] ?? null
  // On one customer's console the panel is about that customer and nobody else
  // (task 37.6): replying to "whoever is newest" from a screen headed with this
  // customer's name would put words on the wrong phone.
  const holding =
    view.kind === 'customer' ? (held.find((c) => c.key_id === view.keyId) ?? null) : holdingAny

  // That customer's past, re-read on a beat. See TRANSCRIPT_POLL_MS.
  useEffect(() => {
    if (!token || view.kind !== 'customer') return
    let stale = false
    const read = () =>
      readConversation(token, view.conversationId)
        .then((got) => {
          if (stale) return
          setDetail(got)
          setDetailNote('')
        })
        .catch(() => !stale && setDetailNote('这通对话读不出来'))
    read()
    const timer = window.setInterval(read, TRANSCRIPT_POLL_MS)
    return () => {
      stale = true
      window.clearInterval(timer)
    }
  }, [token, view])

  // Stable, because the list keys its polling on it. Only setters inside.
  const refuse = useCallback((status: number) => {
    // A token the server will not take is the one error worth forgetting, so the
    // gate comes back -- saying why, rather than as an empty box.
    forgetToken()
    setGateNote(status === 503 ? NOT_CONFIGURED_NOTE : BAD_TOKEN_NOTE)
    setToken('')
  }, [])

  const pastIds = useMemo(() => toolUseIds(detail), [detail])
  // What the feed area shows. On one customer's console: their calls from the
  // live stream that the transcript above does not already have -- a call can be
  // in both when the screen is opened mid-turn, and the transcript catches up on
  // its next read.
  const liveRows = useMemo(
    () =>
      view.kind === 'customer'
        ? rows.filter((row) => row.keyId === view.keyId && !pastIds.has(row.id))
        : rows,
    [rows, view, pastIds],
  )

  // Newest at the bottom, like every other console; follow it down. Keyed on how
  // much there is rather than on the objects themselves: the transcript is re-read
  // every few seconds, and snapping to the bottom on a read that brought nothing
  // new would yank an operator who had scrolled up to read.
  const contentSize = liveRows.length + (detail?.messages.length ?? 0)
  useEffect(() => {
    feedRef.current?.scrollTo({ top: feedRef.current.scrollHeight })
  }, [contentSize, view])

  function chooseView(next: ConsoleView) {
    setView(next)
    setDetail(null)
    setDetailNote('')
    setClosingNote('')
  }

  function takeOver() {
    if (view.kind !== 'customer') return
    setHandover(token, view.keyId, true)
      .then(({ customers }) => {
        setHeld(customers)
        setHandoverNote('')
      })
      .catch(() => setHandoverNote('接管不了，后端没接受'))
  }

  function sendReply() {
    if (!holding || sending) return
    const text = draftReply.trim()
    if (!text) return
    setSending(true)
    replyAsHuman(token, holding.key_id, text)
      .then(() => {
        // Cleared only once it has actually gone: the operator is typing in
        // front of a customer who is waiting, and a box that empties on a send
        // that failed loses what they wrote.
        setDraftReply('')
        setHandoverNote('')
      })
      .catch((failure: unknown) => {
        setHandoverNote(
          failure instanceof ApiError ? `没发出去：${failure.message}` : '没发出去，后端没接受',
        )
      })
      .finally(() => setSending(false))
  }

  function releaseHandover() {
    if (!holding) return
    setHandover(token, holding.key_id, false)
      .then(({ customers }) => {
        setHeld(customers)
        setHandoverNote('')
      })
      .catch(() => setHandoverNote('交不回去，后端没接受'))
  }

  function closeDemo() {
    if (closing) return
    setClosing(true)
    setClosingNote('')
    // On one customer's console, to that customer. On the everybody feed the
    // backend still picks the most recent conversation, as it always has.
    sendDemoSummary(token, view.kind === 'customer' ? view.keyId : undefined)
      .then((sent) => {
        const who = sent.display_name ?? sent.key_id
        // Who it went to, said out loud: on the everybody feed the screen does
        // not choose, the backend picks the most recent conversation. In a room
        // with three customers in it, this line is the difference between right
        // and lucky.
        setClosingNote(`已发给 ${who} · ${sent.minutes} 分钟 · ${sent.tool_calls} 次真实调用`)
      })
      .catch((failure: unknown) => {
        setClosingNote(
          failure instanceof ApiError ? `没发出去：${failure.message}` : '没发出去，后端没接受',
        )
      })
      .finally(() => setClosing(false))
  }

  function saveToken() {
    const value = draftToken.trim()
    if (!value) return
    rememberToken(value)
    setGateNote('')
    setToken(value)
    setConnection('connecting')
  }

  if (!token) {
    return (
      <div className="console">
        <div className="console-gate">
          <h1>导演台</h1>
          {gateNote && <p className="console-gate-note">{gateNote}</p>}
          <p>
            这条流里有真实的订单和客户资料，需要 CONSOLE_TOKEN 才能订阅。也可以直接打开
            <code> /console?token=…</code>。
          </p>
          <input
            type="password"
            value={draftToken}
            placeholder="CONSOLE_TOKEN"
            autoFocus
            onChange={(e) => setDraftToken(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && saveToken()}
          />
          <button onClick={saveToken}>连接</button>
        </div>
      </div>
    )
  }

  return (
    <div className="console">
      <header className="console-header">
        <span className="console-title">导演台 · 工具调用实时流</span>
        <span className="console-status" data-state={connection}>
          {statusText}
        </span>
        <span className="console-compare">
          同样这通询问，人工客服约 {HUMAN_MINUTES} 分钟
        </span>
        <button
          className="console-switch"
          data-off={toolsEnabled === false}
          disabled={toolsEnabled === null}
          onClick={flipTools}
        >
          {toolsEnabled === false ? '工具已关闭 · 点此接回' : '工具已接通 · 点此关掉'}
        </button>
        {switchNote && <span className="console-switch-note">{switchNote}</span>}
        <button className="console-switch" disabled={closing} onClick={closeDemo}>
          {closing ? '正在发…' : '结束演示 · 发一份总结到他手机'}
        </button>
        {closingNote && (
          <span className="console-switch-note" data-ok={!closingNote.startsWith('没发出去')}>
            {closingNote}
          </span>
        )}
        {/* Two numbers that mean two things, so they are labelled apart. The
            everybody feed can only add up what this page has heard since it
            opened; one customer's figure is the audit log's, priced when each
            call happened, and is right however long ago the page was opened. */}
        <span className="console-cost">
          {view.kind === 'customer'
            ? `这通对话 ${formatRinggit(detail?.cost_myr ?? 0)}`
            : `全部 · 本页打开以来 ${formatRinggit(costMyr)}`}
        </span>
      </header>

      {toolsEnabled === false && (
        <div className="console-control-banner">
          对照组：所有工具已关闭。同一个 bot、同一个问题，现在它只能从提示词里的 JSON 里答——
          <strong>听起来一样自信，但没有一个数字是查来的。</strong>
        </div>
      )}

      <div className="console-body">
        <ConversationList token={token} view={view} onSelect={chooseView} onRefused={refuse} />

        <main className="console-main">
          {view.kind === 'customer' && !holding && (
            <div className="console-handover-head console-customer-bar">
              <strong>{view.name}</strong>
              <span className="console-handover-dim">bot 正在回复这位客户</span>
              <button className="console-switch" onClick={takeOver}>
                人工接管
              </button>
              {handoverNote && <span className="console-switch-note">{handoverNote}</span>}
            </div>
          )}

          {holding && (
            <div className="console-handover">
              <div className="console-handover-head">
                <strong>人工接管中</strong>
                <span>{holding.display_name ?? holding.key_id}</span>
                <span className="console-handover-dim">bot 已静默，客户看到的每一句都是你打的</span>
                <button className="console-switch" onClick={releaseHandover}>
                  交回 bot
                </button>
              </div>
              {/* The picker belongs to the everybody feed. On one customer's console
                  there is nobody else to switch to. */}
              {view.kind === 'all' && held.length > 1 && (
                <div className="console-handover-head">
                  <span className="console-handover-dim">还有别人也在接管中，点一下切换：</span>
                  {held.map((customer) => (
                    <button
                      key={customer.key_id}
                      className="console-switch"
                      data-off={customer.key_id !== holding.key_id}
                      onClick={() => setHeldPick(customer.key_id)}
                    >
                      {customer.display_name ?? customer.key_id}
                    </button>
                  ))}
                </div>
              )}
              <div className="console-handover-line">
                <input
                  value={draftReply}
                  placeholder="打字回复这位客户，Enter 发送"
                  disabled={sending}
                  maxLength={MAX_REPLY_CHARS}
                  onChange={(e) => setDraftReply(e.target.value)}
                  onKeyDown={(e) => {
                    // `isComposing` because this panel is in Chinese: picking a
                    // candidate off the IME is an Enter too, and without the guard
                    // the half-composed fragment goes to a live customer.
                    if (e.key === 'Enter' && !e.nativeEvent.isComposing) sendReply()
                  }}
                />
                <button className="console-switch" disabled={sending} onClick={sendReply}>
                  {sending ? '发送中…' : '发送'}
                </button>
              </div>
              {handoverNote && <span className="console-switch-note">{handoverNote}</span>}
            </div>
          )}

          <div className="console-feed" ref={feedRef}>
            {/* Said even while an older copy is still on screen. Found in the
                browser test: with the database down the transcript simply stopped
                moving, and nothing said it had -- an operator reading it would take
                a stale page for a quiet customer. The live calls below carry on. */}
            {view.kind === 'customer' && detail && detailNote && (
              <p className="console-switch-note">{detailNote}，下面是上一次读到的内容</p>
            )}
            {view.kind === 'customer' &&
              (detail ? (
                <Transcript detail={detail} />
              ) : (
                <p className="console-empty">{detailNote || '读取这通对话…'}</p>
              ))}

            {view.kind === 'customer' && liveRows.length > 0 && (
              <div className="console-live-divider">实时 · 还没进记录的调用</div>
            )}

            {view.kind === 'all' && liveRows.length === 0 ? (
              <p className="console-empty">等待第一条消息…（在手机上给这个号码发点什么）</p>
            ) : (
              liveRows.map((row) => (
                <Row
                  key={row.key}
                  row={row}
                  expanded={expanded.has(row.key)}
                  onToggle={() =>
                    setExpanded((current) => {
                      const next = new Set(current)
                      if (!next.delete(row.key)) next.add(row.key)
                      return next
                    })
                  }
                />
              ))
            )}
          </div>
        </main>
      </div>
    </div>
  )
}

function _lastIndexOf(rows: ToolRow[], id: string): number {
  for (let i = rows.length - 1; i >= 0; i -= 1) {
    if (rows[i].id === id) return i
  }
  return -1
}

/** Fold one event into the rows, pairing `tool_end` onto the call it answers. */
function mergeEvent(rows: ToolRow[], event: ConsoleEvent): ToolRow[] {
  if (event.type === 'send_failed') {
    return [
      ...rows,
      {
        key: nextRowKey++,
        id: `failed:${event.seq}`,
        seq: event.seq,
        at: event.at,
        tool: '回复没有送达',
        input: null,
        output: event.output,
        durationMs: null,
        status: 'error',
        keyId: event.key_id ?? '',
      },
    ]
  }

  if (event.type === 'tools_switched') {
    const off = event.status === 'off'
    return [
      ...rows,
      {
        key: nextRowKey++,
        id: `switch:${event.seq}`,
        seq: event.seq,
        at: event.at,
        tool: off ? '工具已关闭 —— 对照组开始' : '工具已接回 —— 对照组结束',
        input: null,
        output: null,
        durationMs: null,
        status: 'note',
        keyId: event.key_id ?? '',
      },
    ]
  }

  if (event.type === 'tool_start') {
    return [
      ...rows,
      {
        key: nextRowKey++,
        id: event.tool_use_id,
        seq: event.seq,
        at: event.at,
        tool: event.tool,
        input: event.input,
        output: null,
        durationMs: null,
        status: 'running',
        keyId: event.key_id ?? '',
      },
    ]
  }

  // A `tool_end` whose start we never saw (a screen that connected without
  // replay) still deserves a line rather than being dropped on the floor.
  //
  // Searched from the bottom: an end answers the most recent call with that id.
  // Anthropic's ids are unique so this is the same row either way in practice,
  // but scanning from the top means any repeat leaves the live call stuck on
  // "running" while a finished one further up is written to twice.
  const index = _lastIndexOf(rows, event.tool_use_id)
  const merged: ToolRow = {
    key: index === -1 ? nextRowKey++ : rows[index].key,
    id: event.tool_use_id,
    seq: index === -1 ? event.seq : rows[index].seq,
    at: index === -1 ? event.at : rows[index].at,
    tool: event.tool,
    input: index === -1 ? null : rows[index].input,
    output: event.output,
    durationMs: event.duration_ms,
    status: event.status === 'error' ? 'error' : 'ok',
    // The start's, when there was one: the end of a call belongs to whoever the
    // call was for, and a backend older than task 37.6 sends no key at all.
    keyId: (index === -1 ? event.key_id : rows[index].keyId || event.key_id) ?? '',
  }
  if (index === -1) return [...rows, merged]
  return rows.map((row, i) => (i === index ? merged : row))
}

function Row({
  row,
  expanded,
  onToggle,
}: {
  row: ToolRow
  expanded: boolean
  onToggle: () => void
}) {
  const badge = { running: '运行中', ok: 'ok', error: 'error', note: '开关' }[row.status]

  return (
    <div className="console-row" data-status={row.status} onClick={onToggle}>
      <div className="console-row-head">
        <span className="console-time">{formatTime(row.at)}</span>
        <span className="console-tool">{row.tool}</span>
        <span className="console-badge" data-status={row.status}>
          {badge}
        </span>
        {row.durationMs !== null && (
          <span className="console-duration">{row.durationMs} ms</span>
        )}
      </div>

      {row.input && (
        <div className="console-field">
          <span className="console-field-label">入参</span>
          {preview(JSON.stringify(row.input), 200, expanded)}
        </div>
      )}

      {row.output && (
        <div className="console-field console-field-out">
          <span className="console-field-label">返回</span>
          {preview(row.output, 300, expanded)}
        </div>
      )}
    </div>
  )
}
