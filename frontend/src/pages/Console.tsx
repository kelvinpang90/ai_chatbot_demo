import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import './Console.css'
import {
  ApiError,
  consoleStreamUrl,
  forgetToken,
  listConversations,
  readConversation,
  readFaultDrill,
  readHandovers,
  readToolSwitch,
  rememberToken,
  replyAsHuman,
  sendDemoSummary,
  setFaultDrill,
  setHandover,
  setToolSwitch,
  storedToken,
  type ConsoleEvent,
  type ConversationDetail,
  type ConversationSummary,
  type HandoverCustomer,
} from '../api'
import { BackOffice } from '../components/BackOffice'
import { CustomerList, type ConsoleView } from '../components/CustomerList'
import {
  boldRuns,
  describe,
  klEpoch,
  klTime,
  seconds,
  span,
  written,
  type Call,
  type Card,
} from '../consoleCards'
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

const POLL_FAILED = 'Could not read who is taken over'

// How often the conversation on screen is read again. The feed carries no
// messages, so this is what brings in what was *said*. Three seconds rather than
// five since task 27 put the customer's phone on the left of the projector; a
// reply that lands on the real phone should not take long to land here.
const TRANSCRIPT_POLL_MS = 3000

// After the feed says this customer's turn did something, read the transcript
// again this soon: long enough for the reply to have been written to the log.
const NUDGE_DELAY_MS = 1500

// How often to ask which conversation is the newest -- everybody's in follow
// mode, the chosen customer's otherwise.
const LATEST_POLL_MS = 5000

// How far before a conversation's first message a live call may be and still
// belong to it: the clock difference between this laptop and the server, and a
// call already running when the conversation's first row was written.
const START_SLACK_SECONDS = 5

// Carried over from the transcript page this screen absorbed (task 37.6).
const BAD_TOKEN_NOTE =
  'Wrong token. If you copied it from the server .env, leave out the quotes around the value -- docker compose counts them as part of the token.'
const NOT_CONFIGURED_NOTE = 'The backend has no CONSOLE_TOKEN set, so this page cannot open.'

// How long the same enquiry takes a person. Not measured, deliberately
// conservative, and on screen because "it is fast" means nothing next to a
// number the owner can compare against a salary.
const HUMAN_MINUTES = 3

const TECH_STORAGE_KEY = 'console_tech_mode'
const LIST_STORAGE_KEY = 'console_customer_list'
const THEME_STORAGE_KEY = 'console_theme_light'
const LIST_WIDTH_KEY = 'console_list_width'
const PHONE_WIDTH_KEY = 'console_phone_width'

// The three panes' widths, dragged from the bars between them. The system pane
// takes what is left and is never squeezed below SYSTEM_MIN_WIDTH, because it is
// the one the room is meant to be reading.
const LIST_WIDTH = { initial: 320, min: 200, max: 560 }
const PHONE_WIDTH = { initial: 380, min: 260, max: 900 }
const SYSTEM_MIN_WIDTH = 360
const SPLITTER_STEP = 20

const BOT_LABELS: Record<string, string> = {
  retail: 'Retail',
  food: 'Food',
  realestate: 'Property',
  hotel: 'Hotel',
  saas: 'SaaS',
  banking: 'Banking',
}

type Connection = 'connecting' | 'live' | 'error'

// React needs a key that is unique for the life of the list. The tool_use_id is
// not it: ids come from whichever backend process is running, and one that
// restarts mid-demo can hand out an id a row above already carries.
let nextRowKey = 1

// What every failure-drill line on the feed starts with, which is also how its
// card tells itself apart from a tools-switch line in tech mode.
const DRILL_LABEL = 'Failure drill'

/** One tool call, both halves of it, as a single line on the screen. */
interface ToolRow extends Call {
  key: number
  id: string
  seq: number
  at: number
  // Whose call it was (task 37.6). Blank for what belongs to nobody.
  keyId: string
}

/** One card on the right, from the audit log or the live feed. */
interface Entry {
  key: string
  at: number
  call: Call
  card: Card
}

/** The conversation on screen, however it was chosen. */
interface Target {
  conversationId: string
  keyId: string
  name: string
}

function readFlag(key: string): boolean {
  try {
    return window.localStorage.getItem(key) === '1'
  } catch {
    return false
  }
}

function storeFlag(key: string, value: boolean): void {
  try {
    window.localStorage.setItem(key, value ? '1' : '0')
  } catch {
    // A browser refusing storage still works; it forgets on reload.
  }
}

function readWidth(key: string, fallback: number): number {
  try {
    const stored = Number(window.localStorage.getItem(key))
    return Number.isFinite(stored) && stored > 0 ? stored : fallback
  } catch {
    return fallback
  }
}

function storeWidth(key: string, value: number): void {
  try {
    window.localStorage.setItem(key, String(Math.round(value)))
  } catch {
    // A browser refusing storage still works; it forgets on reload.
  }
}

function formatRinggit(total: number): string {
  // Below one sen, two decimals reads as free and looks broken. Four decimals
  // reads as a real, very small number, which is the actual point being made.
  return `RM ${total.toFixed(total > 0 && total < 0.01 ? 4 : 2)}`
}

function tokens(n: number): string {
  return n >= 10000 ? `${(n / 1000).toFixed(1)}k` : n.toLocaleString()
}

/**
 * The director's console: on the left what the customer sees on their phone, on
 * the right what the business is buying -- what the system did, and what it
 * changed in the back office.
 */
export default function Console() {
  const [token, setToken] = useState(storedToken)
  const [draftToken, setDraftToken] = useState('')
  const [gateNote, setGateNote] = useState('')
  // Bumped to build a fresh EventSource after the server dropped the old one.
  const [attempt, setAttempt] = useState(0)
  const [connection, setConnection] = useState<Connection>('connecting')
  const [rows, setRows] = useState<ToolRow[]>([])
  // Whether the bots still have their tools. `null` until the backend says, so
  // the switch cannot start out claiming a position it has not been told.
  const [toolsEnabled, setToolsEnabled] = useState<boolean | null>(null)
  const [switchNote, setSwitchNote] = useState('')
  // Whether the next ERP call is set to fail (task 27.1). Disarms itself when it
  // fires, which this screen hears about from the feed.
  const [drillArmed, setDrillArmed] = useState<boolean | null>(null)
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
  // Follow whoever spoke last, or one conversation the operator picked.
  const [view, setView] = useState<ConsoleView>({ kind: 'all' })
  // The newest conversation: everybody's in follow mode, the picked customer's
  // otherwise -- which is how a picked conversation knows whether the live feed
  // is still about it.
  const [latest, setLatest] = useState<ConversationSummary | null>(null)
  const [detail, setDetail] = useState<ConversationDetail | null>(null)
  const [detailNote, setDetailNote] = useState('')
  // Bumped when the feed shows the customer on screen doing something.
  const [nudge, setNudge] = useState(0)
  // Bumped when the feed shows anybody doing something: in follow mode, a new
  // customer starting a demo is the moment to ask who is newest.
  const [feedTick, setFeedTick] = useState(0)
  const [techMode, setTechMode] = useState(() => readFlag(TECH_STORAGE_KEY))
  const [showList, setShowList] = useState(() => readFlag(LIST_STORAGE_KEY))
  const [light, setLight] = useState(() => readFlag(THEME_STORAGE_KEY))
  const [listWidth, setListWidth] = useState(() => readWidth(LIST_WIDTH_KEY, LIST_WIDTH.initial))
  const [phoneWidth, setPhoneWidth] = useState(() => readWidth(PHONE_WIDTH_KEY, PHONE_WIDTH.initial))
  const phoneRef = useRef<HTMLDivElement>(null)
  const streamRef = useRef<HTMLDivElement>(null)
  // Replay re-sends the whole buffer every time a stream opens, so the same
  // event arrives again after a reconnect. Sequence numbers make that harmless -
  // but only if they outlive the stream that saw them first, or a redeploy
  // mid-demo doubles every row on the screen.
  const seenRef = useRef<Set<number>>(new Set())
  // Which run of the backend the sequence numbers in `seenRef` came from.
  const bootRef = useRef<string | null>(null)
  // The token this console has actually got a stream out of. Kept outside the
  // effect on purpose: a per-EventSource flag resets on every retry, so a
  // backend down for longer than one retry would look like a bad token again
  // and throw away a token we have proof is good.
  const provenTokenRef = useRef<string | null>(null)
  // Whose conversation is on screen, for the stream handler, which outlives it.
  const targetKeyRef = useRef('')

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

      // The customer on screen just did something: what they said and what the
      // bot answered are about to be in the log, so read it soon rather than on
      // the next beat.
      if (event.key_id && event.type !== 'tool_start') {
        setFeedTick((n) => n + 1)
        if (event.key_id === targetKeyRef.current) setNudge((n) => n + 1)
      }

      // Cost comes from the audit log, priced per conversation; the feed's copy
      // would be everybody's.
      if (event.type === 'usage') return

      // The switch may have been thrown from another screen, or by this one;
      // either way the stream is what says where it now stands. The event also
      // gets a card, so read it and carry on.
      if (event.type === 'tools_switched') {
        setToolsEnabled(event.status === 'on')
        setSwitchNote('')
      }
      if (event.type === 'fault_drill') {
        setDrillArmed(event.status === 'armed')
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
          giveUp('Subscription refused: wrong token, or the backend has no CONSOLE_TOKEN.')
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
        giveUp('Cannot reach the backend after several tries.')
      }
    }
    source.addEventListener('hello', hello as EventListener)
    for (const type of ['tool_start', 'tool_end', 'send_failed', 'usage', 'tools_switched', 'fault_drill']) {
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
      .catch(() => !stale && setSwitchNote('Could not read the tools switch'))
    readFaultDrill(token)
      .then(({ armed }) => !stale && setDrillArmed(armed))
      .catch(() => !stale && setSwitchNote('Could not read the failure drill'))
    return () => {
      stale = true
    }
  }, [token])

  const statusText = { connecting: 'Connecting…', live: 'Live', error: 'Disconnected, retrying…' }[connection]

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
      .catch(() => setSwitchNote('Switch not thrown: the backend refused'))
  }

  function flipDrill() {
    if (drillArmed === null) return
    // Not optimistic, for the tools switch's reason.
    setFaultDrill(token, !drillArmed)
      .then(({ armed }) => {
        setDrillArmed(armed)
        setSwitchNote('')
      })
      .catch(() => setSwitchNote('Drill not armed: the backend refused'))
  }

  useEffect(() => {
    if (!token) return
    let stale = false
    const ask = () =>
      readHandovers(token)
        .then(({ customers }) => {
          if (stale) return
          setHeld(customers)
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

  // Stable, because the list keys its polling on it. Only setters inside.
  const refuse = useCallback((status: number) => {
    // A token the server will not take is the one error worth forgetting, so the
    // gate comes back -- saying why, rather than as an empty box.
    forgetToken()
    setGateNote(status === 503 ? NOT_CONFIGURED_NOTE : BAD_TOKEN_NOTE)
    setToken('')
  }, [])

  const pickedKey = view.kind === 'customer' ? view.keyId : ''
  useEffect(() => {
    if (!token) return
    let stale = false
    const ask = () =>
      listConversations(token, pickedKey, 0, 1)
        .then((page) => !stale && setLatest(page.conversations[0] ?? null))
        .catch((failure: unknown) => {
          if (stale) return
          if (failure instanceof ApiError && (failure.status === 401 || failure.status === 503)) {
            refuse(failure.status)
          }
        })
    const soon = window.setTimeout(ask, feedTick ? NUDGE_DELAY_MS : 0)
    const timer = window.setInterval(ask, LATEST_POLL_MS)
    return () => {
      stale = true
      window.clearTimeout(soon)
      window.clearInterval(timer)
    }
  }, [token, pickedKey, refuse, feedTick])

  // The screen shows one conversation and nothing else -- the 2026-09-14 run
  // had an old retail chat above and live food calls below it. In follow mode
  // that is the newest conversation anybody has had; picked, it is the pick.
  const followed =
    view.kind === 'all' && latest
      ? {
          conversationId: latest.conversation_id,
          keyId: latest.key_id,
          name: latest.display_name || latest.key_id,
        }
      : null
  const target: Target | null =
    view.kind === 'customer'
      ? { conversationId: view.conversationId, keyId: view.keyId, name: view.name }
      : followed
  const targetId = target?.conversationId ?? ''
  const targetKey = target?.keyId ?? ''
  useEffect(() => {
    targetKeyRef.current = targetKey
  }, [targetKey])

  // The latest answer is only about this conversation while the view has not
  // changed under it; follow mode's answer is about everybody.
  const isLatest =
    !!latest &&
    latest.conversation_id === targetId &&
    (view.kind === 'all' || latest.key_id === view.keyId)

  useEffect(() => {
    if (!token || !targetId) return
    let stale = false
    const read = () =>
      readConversation(token, targetId)
        .then((got) => {
          if (stale) return
          setDetail(got)
          setDetailNote('')
        })
        .catch(() => !stale && setDetailNote('Could not read this conversation'))
    const soon = window.setTimeout(read, nudge ? NUDGE_DELAY_MS : 0)
    const timer = window.setInterval(read, TRANSCRIPT_POLL_MS)
    return () => {
      stale = true
      window.clearTimeout(soon)
      window.clearInterval(timer)
    }
  }, [token, targetId, nudge])

  // A transcript still on screen from the previous conversation is not shown
  // under the next one's name while the next one loads.
  const shown = detail && detail.conversation_id === targetId ? detail : null
  const startedAt = shown?.messages[0] ? klEpoch(shown.messages[0].at) : 0

  const pastIds = useMemo(() => toolUseIds(shown), [shown])
  const entries = useMemo(() => {
    if (!shown) return []
    const past: Omit<Entry, 'card'>[] = shown.messages.flatMap((message) =>
      message.tool_calls.map((call) => ({
        key: `db:${call.tool_use_id}:${call.at}`,
        at: klEpoch(call.at),
        call: {
          tool: call.tool,
          input: call.input,
          output: call.output,
          status: call.status === 'error' ? ('error' as const) : ('ok' as const),
          durationMs: call.duration_ms,
        },
      })),
    )
    // What the log does not have yet, or never will: pushes, handovers and
    // media arrive on the feed only. Only while this is the customer's newest
    // conversation -- the feed is keyed by customer, not by conversation, so an
    // older one would otherwise collect calls from whatever came after it.
    const live: Omit<Entry, 'card'>[] = isLatest
      ? rows
          .filter(
            (row) =>
              (row.keyId === shown.key_id || (row.keyId === '' && row.status === 'note')) &&
              !pastIds.has(row.id) &&
              row.at >= startedAt - START_SLACK_SECONDS,
          )
          .map((row) => ({ key: `live:${row.key}`, at: row.at, call: row }))
      : []
    return cards([...past, ...live].sort((a, b) => a.at - b.at))
  }, [shown, rows, pastIds, isLatest, startedAt])

  const writes = useMemo(
    () =>
      entries.flatMap((entry) => {
        const write = written(entry.call)
        return write ? [{ ...write, at: entry.at }] : []
      }),
    [entries],
  )
  const slowest = Math.max(1, ...entries.map((entry) => entry.call.durationMs ?? 0))

  // Follow both columns down, keyed on how much there is: a re-read that brought
  // nothing new must not yank an operator who scrolled up to read.
  const messageCount = shown?.messages.length ?? 0
  useEffect(() => {
    phoneRef.current?.scrollTo({ top: phoneRef.current.scrollHeight })
  }, [messageCount, targetId])
  useEffect(() => {
    streamRef.current?.scrollTo({ top: streamRef.current.scrollHeight })
  }, [entries.length, targetId])

  const holding = target ? (held.find((c) => c.key_id === target.keyId) ?? null) : null
  // Anybody else still silent to the bot. A cold review of task 20 found one
  // conversation nobody handed back is enough to leave a customer unanswered,
  // so they stay on screen even while somebody else is being followed.
  const heldElsewhere = held.filter((c) => c.key_id !== targetKey)

  function chooseView(next: ConsoleView) {
    setView(next)
    setLatest(null)
    setDetailNote('')
    setClosingNote('')
  }

  function openHeld(customer: HandoverCustomer) {
    listConversations(token, customer.key_id, 0, 1)
      .then((page) => {
        const row = page.conversations[0]
        if (!row) return
        chooseView({
          kind: 'customer',
          conversationId: row.conversation_id,
          keyId: row.key_id,
          name: customer.display_name || row.key_id,
        })
      })
      .catch(() => setHandoverNote("Could not open this customer's conversation"))
  }

  function takeOver() {
    if (!target) return
    setHandover(token, target.keyId, true)
      .then(({ customers }) => {
        setHeld(customers)
        setHandoverNote('')
      })
      .catch(() => setHandoverNote('Could not take over: the backend refused'))
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
        setNudge((n) => n + 1)
      })
      .catch((failure: unknown) => {
        setHandoverNote(
          failure instanceof ApiError ? `Not sent: ${failure.message}` : 'Not sent: the backend refused',
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
      .catch(() => setHandoverNote('Could not hand back: the backend refused'))
  }

  function closeDemo() {
    if (closing || !target) return
    setClosing(true)
    setClosingNote('')
    sendDemoSummary(token, target.keyId)
      .then((sent) => {
        const who = sent.display_name ?? sent.key_id
        // Who it went to, said out loud. In a room with three customers in it,
        // this line is the difference between right and lucky.
        setClosingNote(`Sent to ${who} · ${sent.minutes} min · ${sent.tool_calls} real calls`)
      })
      .catch((failure: unknown) => {
        setClosingNote(
          failure instanceof ApiError ? `Not sent: ${failure.message}` : 'Not sent: the backend refused',
        )
      })
      .finally(() => setClosing(false))
  }

  function toggleTech() {
    setTechMode((on) => {
      storeFlag(TECH_STORAGE_KEY, !on)
      return !on
    })
  }

  function toggleTheme() {
    setLight((on) => {
      storeFlag(THEME_STORAGE_KEY, !on)
      return !on
    })
  }

  function toggleList() {
    setShowList((on) => {
      storeFlag(LIST_STORAGE_KEY, !on)
      return !on
    })
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
      <div className="console" data-theme={light ? 'light' : 'dark'}>
        <div className="console-gate">
          <h1>Director's console</h1>
          {gateNote && <p className="console-gate-note">{gateNote}</p>}
          <p>
            This feed carries real orders and customer details, so it needs CONSOLE_TOKEN. You can also open
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
          <button onClick={saveToken}>Connect</button>
        </div>
      </div>
    )
  }

  const botId = shown?.bot_id ?? latest?.bot_id ?? ''
  // Whatever the window leaves after the other panes, so dragging one bar can
  // never push the system pane off the screen.
  const room = window.innerWidth
  const listMax = Math.max(LIST_WIDTH.min, Math.min(LIST_WIDTH.max, room - phoneWidth - SYSTEM_MIN_WIDTH))
  const phoneMax = Math.max(
    PHONE_WIDTH.min,
    Math.min(PHONE_WIDTH.max, room - (showList ? listWidth : 0) - SYSTEM_MIN_WIDTH),
  )
  const widths = {
    '--list-width': `${Math.min(listWidth, listMax)}px`,
    '--phone-width': `${Math.min(phoneWidth, phoneMax)}px`,
  } as CSSProperties

  return (
    <div className="console" data-tech={techMode} data-theme={light ? 'light' : 'dark'}>
      <header className="cx-bar">
        <button className="cx-btn" aria-pressed={showList} onClick={toggleList}>
          Customers
        </button>
        {target ? (
          <>
            <span className="cx-who">{target.name}</span>
            {shown && <span className="cx-tag">{shown.channel === 'whatsapp' ? 'WhatsApp' : 'Web'}</span>}
            {botId && <span className="cx-tag">{BOT_LABELS[botId] ?? botId}</span>}
            <span className="cx-state" data-held={!!holding}>
              {holding ? 'Human has it · bot silent' : 'Bot is replying'}
            </span>
          </>
        ) : (
          <span className="cx-who cx-dim">No conversation yet</span>
        )}
        <span className="cx-mode">{view.kind === 'all' ? 'Following latest' : 'Pinned'}</span>
        <span className="cx-live" data-state={connection}>
          {statusText}
        </span>

        <span className="cx-spacer" />

        {shown && (
          <span className="cx-cost" title="Everything this conversation cost on Claude, priced per call when it happened">
            This chat <b>{formatRinggit(shown.cost_myr)}</b>
            <small>
              {tokens(shown.input_tokens + shown.cache_read_tokens + shown.cache_write_tokens)} in ·{' '}
              {tokens(shown.output_tokens)} out · {shown.api_turns} calls
            </small>
          </span>
        )}
        <span className="cx-compare">A person takes ~{HUMAN_MINUTES} min</span>

        <button className="cx-btn" onClick={toggleTheme} title="Switch between a light and a dark background">
          {light ? 'Dark background' : 'Light background'}
        </button>
        <label className="cx-toggle">
          <input type="checkbox" checked={techMode} onChange={toggleTech} />
          Tech mode
        </label>
        {target &&
          (holding ? (
            <button className="cx-btn cx-btn-hot" onClick={releaseHandover}>
              Hand back to bot
            </button>
          ) : (
            <button className="cx-btn" onClick={takeOver}>
              Take over
            </button>
          ))}
        <button
          className="cx-btn"
          data-off={toolsEnabled === false}
          disabled={toolsEnabled === null}
          onClick={flipTools}
        >
          {toolsEnabled === false ? 'Tools off · turn back on' : 'Turn tools off (control)'}
        </button>
        <button
          className="cx-btn"
          data-off={drillArmed === true}
          disabled={drillArmed === null}
          onClick={flipDrill}
          title="Make the next ERP call fail, once, the way an unreachable ERP fails"
        >
          {drillArmed ? 'Drill armed · call off' : 'Break next ERP call (drill)'}
        </button>
        <button className="cx-btn" disabled={closing || !target} onClick={closeDemo}>
          {closing ? 'Sending…' : 'End demo · send summary'}
        </button>
      </header>

      {(switchNote || closingNote || handoverNote) && (
        <div className="cx-notes">
          {switchNote && <span className="cx-note">{switchNote}</span>}
          {handoverNote && <span className="cx-note">{handoverNote}</span>}
          {closingNote && (
            <span className="cx-note" data-ok={!closingNote.startsWith('Not sent')}>
              {closingNote}
            </span>
          )}
        </div>
      )}

      {toolsEnabled === false && (
        <div className="console-control-banner">
          Control arm: every tool is off. Same bot, same question -- now it can only answer from the JSON in its prompt.{' '}
          <strong>It sounds just as sure, but not one number was looked up.</strong>
        </div>
      )}

      {heldElsewhere.length > 0 && (
        <div className="cx-held-elsewhere">
          Still taken over, and the bot will not answer them:
          {heldElsewhere.map((customer) => (
            <button key={customer.key_id} className="cx-btn cx-btn-hot" onClick={() => openHeld(customer)}>
              {customer.display_name ?? customer.key_id}
            </button>
          ))}
        </div>
      )}

      <div className="console-body" style={widths}>
        {showList && (
          <>
            <CustomerList token={token} view={view} onSelect={chooseView} onRefused={refuse} />
            <Splitter
              label="Resize the customer list"
              value={Math.min(listWidth, listMax)}
              min={LIST_WIDTH.min}
              max={listMax}
              initial={LIST_WIDTH.initial}
              onChange={(next) => {
                setListWidth(next)
                storeWidth(LIST_WIDTH_KEY, next)
              }}
            />
          </>
        )}

        <main className="cx-main">
          <section className="cx-phone">
            <div className="cx-pane-label">Customer's phone</div>
            <div className="cx-phone-scroll" ref={phoneRef}>
              {!target && <p className="cx-empty">Waiting for the first message… (send this number something from a phone)</p>}
              {target && !shown && <p className="cx-empty">{detailNote || 'Reading this conversation…'}</p>}
              {shown && detailNote && <p className="cx-note">{detailNote} -- showing the last copy read</p>}
              {shown?.messages.map((message, i) => {
                const at = klTime(klEpoch(message.at))
                const previous = shown.messages[i - 1]
                // A time on the first bubble of each minute, like the phone does.
                const stamp = !previous || klTime(klEpoch(previous.at)).slice(0, 5) !== at.slice(0, 5)
                const who =
                  message.role === 'user' ? 'cust' : message.source === 'human' ? 'human' : 'bot'
                return (
                  <div key={message.id} className={`cx-msg cx-msg-${who}`}>
                    {(stamp || who === 'human') && (
                      <span className="cx-msg-meta">
                        {who === 'human' && 'Colleague · '}
                        {message.source === 'voice' && 'Voice · '}
                        {at.slice(0, 5)}
                      </span>
                    )}
                    <div className="cx-bubble">
                      {boldRuns(message.content).map((run, j) =>
                        run.bold ? <strong key={j}>{run.text}</strong> : run.text,
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
            {holding && (
              <div className="cx-reply">
                <input
                  value={draftReply}
                  placeholder="Reply as a colleague, Enter to send"
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
                <button className="cx-btn" disabled={sending} onClick={sendReply}>
                  {sending ? 'Sending…' : 'Send'}
                </button>
              </div>
            )}
          </section>

          <Splitter
            label="Resize the customer's phone"
            value={Math.min(phoneWidth, phoneMax)}
            min={PHONE_WIDTH.min}
            max={phoneMax}
            initial={PHONE_WIDTH.initial}
            onChange={(next) => {
              setPhoneWidth(next)
              storeWidth(PHONE_WIDTH_KEY, next)
            }}
          />

          <section className="cx-system">
            <div className="cx-stream" ref={streamRef}>
              <div className="cx-pane-label">What the system is doing</div>
              {shown && entries.length === 0 && <p className="cx-empty">No system has been called in this conversation yet</p>}
              {entries.map((entry) => (
                <CardView key={entry.key} entry={entry} slowest={slowest} />
              ))}
            </div>
            {shown && target && (
              <BackOffice
                token={token}
                botId={shown.bot_id}
                keyId={target.keyId}
                startedAt={startedAt}
                writes={writes}
              />
            )}
          </section>
        </main>
      </div>
    </div>
  )
}

/**
 * A bar between two panes: drag it, or focus it and use the arrow keys.
 * Double-click puts the pane back to its starting width.
 */
function Splitter({
  label,
  value,
  min,
  max,
  initial,
  onChange,
}: {
  label: string
  value: number
  min: number
  max: number
  initial: number
  onChange: (next: number) => void
}) {
  const clamp = (n: number) => Math.min(max, Math.max(min, n))
  const drag = useRef<{ x: number; width: number } | null>(null)

  return (
    <div
      className="cx-splitter"
      role="separator"
      aria-orientation="vertical"
      aria-label={label}
      aria-valuenow={Math.round(value)}
      aria-valuemin={min}
      aria-valuemax={max}
      tabIndex={0}
      title={`${label} -- drag, or double-click to reset`}
      onPointerDown={(e) => {
        e.currentTarget.setPointerCapture(e.pointerId)
        drag.current = { x: e.clientX, width: value }
      }}
      onPointerMove={(e) => {
        if (drag.current) onChange(clamp(drag.current.width + e.clientX - drag.current.x))
      }}
      onPointerUp={() => {
        drag.current = null
      }}
      onPointerCancel={() => {
        drag.current = null
      }}
      onDoubleClick={() => onChange(clamp(initial))}
      onKeyDown={(e) => {
        if (e.key === 'ArrowLeft') onChange(clamp(value - SPLITTER_STEP))
        if (e.key === 'ArrowRight') onChange(clamp(value + SPLITTER_STEP))
      }}
    />
  )
}

/**
 * Cards for a time-ordered run of calls, with a model's handover folded into
 * one: `request_human_help` starts a `handover` span with the same reason, and
 * two cards saying "handed to a colleague" and "human has it" side by side read as two events.
 */
function cards(calls: Omit<Entry, 'card'>[]): Entry[] {
  const entries: Entry[] = []
  for (const item of calls) {
    const card = describe(item.call)
    if (!card) continue
    if (item.call.tool === 'handover') {
      const reason = String(item.call.input?.reason ?? '')
      const asked = entries.findLast(
        (e) => e.call.tool === 'request_human_help' && String(e.call.input?.reason ?? '') === reason,
      )
      if (asked && reason) {
        asked.card = {
          ...asked.card,
          detail:
            item.call.status === 'running'
              ? `${asked.card.detail} · human has it`
              : `${asked.card.detail} · handed back after ${span((item.call.durationMs ?? 0) / 1000)}`,
        }
        continue
      }
    }
    entries.push({ ...item, card })
  }
  return entries
}

function CardView({ entry, slowest }: { entry: Entry; slowest: number }) {
  const { call, card } = entry
  const ms = call.durationMs
  return (
    <div className="cx-card" data-kind={card.kind} data-running={call.status === 'running'}>
      <div className="cx-card-icon">{card.icon}</div>
      <div className="cx-card-title">
        <strong>{card.title}</strong>
        {card.badge && <span className="cx-badge">{card.badge}</span>}
        <span className="cx-time">{klTime(entry.at)}</span>
      </div>
      {card.detail && <div className="cx-card-detail">{card.detail}</div>}
      {/* Function name, arguments and timing -- never the output, which for a
          refusal or a handover is text written for the model, not the room. */}
      <div className="cx-tech">
        <span className="cx-fn">
          {call.status === 'note'
            ? call.tool.startsWith(DRILL_LABEL)
              ? 'fault_drill'
              : 'tools_switched'
            : call.tool}
        </span>
        {ms != null && (
          <>
            <span className="cx-ms">{seconds(ms)}</span>
            <span className="cx-bar-track">
              <span className="cx-bar-fill" style={{ width: `${Math.max(2, (ms / slowest) * 100)}%` }} />
            </span>
          </>
        )}
        {call.input && Object.keys(call.input).length > 0 && (
          <code>{JSON.stringify(call.input)}</code>
        )}
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
        tool: event.tool,
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
        tool: off ? 'Tools turned off -- control arm starts' : 'Tools back on -- control arm ends',
        input: null,
        output: null,
        durationMs: null,
        status: 'note',
        keyId: event.key_id ?? '',
      },
    ]
  }

  if (event.type === 'fault_drill') {
    const label = {
      armed: `${DRILL_LABEL} armed -- the next ERP call will fail`,
      fired: `${DRILL_LABEL}: this ERP call was cut off on purpose`,
      disarmed: `${DRILL_LABEL} called off`,
    }[event.status as 'armed' | 'fired' | 'disarmed']
    return [
      ...rows,
      {
        key: nextRowKey++,
        id: `drill:${event.seq}`,
        seq: event.seq,
        at: event.at,
        tool: label ?? DRILL_LABEL,
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
