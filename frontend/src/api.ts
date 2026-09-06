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

/** One line on the director's console. Mirrors backend/app/console/events.py. */
export interface ConsoleEvent {
  seq: number
  at: number
  type: 'tool_start' | 'tool_end' | 'send_failed' | 'usage'
  tool: string
  tool_use_id: string
  input: Record<string, unknown> | null
  output: string | null
  duration_ms: number | null
  status: 'ok' | 'error' | null
  model: string | null
  tokens: Record<string, number> | null
  cost_myr: number | null
}

/**
 * The tool feed, gated by CONSOLE_TOKEN.
 *
 * The token travels as a query parameter because EventSource cannot set request
 * headers - see the note on `_check_token` in the router. `replay` asks for the
 * buffer first, which is what a screen opened mid-conversation wants.
 */
export function consoleStreamUrl(token: string, replay = true): string {
  return `/console/stream?token=${encodeURIComponent(token)}&replay=${replay}`
}
