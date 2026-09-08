export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers as Record<string, string> | undefined),
    },
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}) as { detail?: string })
    throw new ApiError(response.status, body.detail ?? 'Request failed')
  }
  return response.json() as Promise<T>
}

export interface BotSummary {
  id: string
  name: string
  description: string
  icon: string
}

export async function listBots(lang: string): Promise<BotSummary[]> {
  return request<BotSummary[]>(`/api/bots?lang=${lang}`)
}

export interface ChatTurn {
  role: 'user' | 'assistant'
  content: string
}

export interface IdentifyResponse {
  key: string
  bot: BotSummary | null
  history: ChatTurn[]
}

/** Open the chat as a phone number - the same record WhatsApp writes to. */
export async function identify(phone: string, lang: string): Promise<IdentifyResponse> {
  return request<IdentifyResponse>('/api/chat/identify', {
    method: 'POST',
    body: JSON.stringify({ phone, lang }),
  })
}

export interface SelectBotResponse {
  greeting: string
  quick_questions: string[]
}

export async function selectBot(
  key: string,
  botId: string,
  lang: string,
): Promise<SelectBotResponse> {
  return request<SelectBotResponse>(`/api/chat/${key}/select`, {
    method: 'POST',
    body: JSON.stringify({ bot_id: botId, lang }),
  })
}

export interface SendMessageResponse {
  reply: string
}

export async function sendMessage(key: string, message: string): Promise<SendMessageResponse> {
  return request<SendMessageResponse>(`/api/chat/${key}/message`, {
    method: 'POST',
    body: JSON.stringify({ message }),
  })
}

export async function resetSession(key: string): Promise<{ status: string }> {
  return request(`/api/chat/${key}/reset`, { method: 'POST' })
}

// --- the audit log (task 37.2) ----------------------------------------------
//
// Everything under /console needs the console token. It is kept in
// sessionStorage rather than localStorage on purpose: this screen shows every
// customer's transcript, and a token that survives until the tab is closed is
// the right trade between not retyping it all afternoon and not leaving it on a
// laptop that gets handed to someone.

const TOKEN_KEY = 'console-token'

export function consoleToken(): string {
  try {
    return sessionStorage.getItem(TOKEN_KEY) ?? ''
  } catch {
    return ''
  }
}

export function setConsoleToken(token: string): void {
  try {
    sessionStorage.setItem(TOKEN_KEY, token)
  } catch {
    // A browser refusing storage still works, it just asks again next reload.
  }
}

export function clearConsoleToken(): void {
  try {
    sessionStorage.removeItem(TOKEN_KEY)
  } catch {
    // Nothing to clear if it could never be stored.
  }
}

function console_<T>(path: string): Promise<T> {
  return request<T>(path, { headers: { 'X-Console-Token': consoleToken() } })
}

export interface ConversationSummary {
  conversation_id: string
  key_id: string
  display_name: string | null
  channel: string
  bot_id: string
  messages: number
  tool_calls: number
  input_tokens: number
  output_tokens: number
  api_turns: number
  started_at: string
  last_at: string
}

export interface ToolCallRecord {
  tool: string
  tool_use_id: string
  input: Record<string, unknown> | null
  output: string | null
  duration_ms: number | null
  status: string
  at: string
}

export interface TranscriptMessage {
  id: number
  role: string
  content: string
  source: string
  at: string
  tool_calls: ToolCallRecord[]
}

export interface ConversationDetail {
  conversation_id: string
  key_id: string
  display_name: string | null
  channel: string
  bot_id: string
  messages: TranscriptMessage[]
  input_tokens: number
  output_tokens: number
  cache_write_tokens: number
  cache_read_tokens: number
  api_turns: number
}

export interface HistoryPage {
  conversations: ConversationSummary[]
  limit: number
  offset: number
}

export async function listConversations(search: string, offset = 0): Promise<HistoryPage> {
  const params = new URLSearchParams({ offset: String(offset) })
  if (search.trim()) params.set('key', search.trim())
  return console_<HistoryPage>(`/console/history?${params}`)
}

export async function readConversation(id: string): Promise<ConversationDetail> {
  return console_<ConversationDetail>(`/console/history/${encodeURIComponent(id)}`)
}
