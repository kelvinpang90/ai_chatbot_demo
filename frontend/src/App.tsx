import { useState } from 'react'
import './App.css'
import LanguageSwitcher from './components/LanguageSwitcher'
import PasswordGate from './pages/PasswordGate'
import PhoneEntry from './pages/PhoneEntry'
import BotSelect from './pages/BotSelect'
import Chat from './pages/Chat'
import {
  ApiError,
  clearToken,
  getToken,
  resetSession,
  selectBot,
  type BotSummary,
  type ChatTurn,
  type IdentifyResponse,
} from './api'
import { DEFAULT_LANG, type Lang } from './i18n/strings'

type View =
  | { name: 'password' }
  | { name: 'phone' }
  | { name: 'botSelect'; chatKey: string }
  | {
      name: 'chat'
      chatKey: string
      bot: BotSummary
      history: ChatTurn[]
      quickQuestions: string[]
    }

function App() {
  const [lang, setLang] = useState<Lang>(DEFAULT_LANG)
  const [view, setView] = useState<View>(() => (getToken() ? { name: 'phone' } : { name: 'password' }))

  function handleAuthError() {
    clearToken()
    setView({ name: 'password' })
  }

  // A number already in a demo goes straight back into it, carrying whatever was
  // said on the phone. Only a number with no conversation sees the menu.
  function handleIdentified(result: IdentifyResponse) {
    setView(
      result.bot
        ? {
            name: 'chat',
            chatKey: result.key,
            bot: result.bot,
            history: result.history,
            quickQuestions: [],
          }
        : { name: 'botSelect', chatKey: result.key },
    )
  }

  async function handleBotSelected(chatKey: string, bot: BotSummary) {
    try {
      const { greeting, quick_questions } = await selectBot(chatKey, bot.id, lang)
      setView({
        name: 'chat',
        chatKey,
        bot,
        history: [{ role: 'assistant', content: greeting }],
        quickQuestions: quick_questions,
      })
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) handleAuthError()
    }
  }

  async function handleReset(chatKey: string) {
    try {
      await resetSession(chatKey)
    } catch {
      // Best-effort: picking a demo again starts a fresh conversation anyway.
    }
    setView({ name: 'botSelect', chatKey })
  }

  return (
    <div className="app-shell">
      <LanguageSwitcher lang={lang} onChange={setLang} />

      {view.name === 'password' && (
        <PasswordGate lang={lang} onSuccess={() => setView({ name: 'phone' })} />
      )}

      {view.name === 'phone' && (
        <PhoneEntry lang={lang} onIdentified={handleIdentified} onAuthError={handleAuthError} />
      )}

      {view.name === 'botSelect' && (
        <BotSelect
          lang={lang}
          onSelect={(bot) => handleBotSelected(view.chatKey, bot)}
          onAuthError={handleAuthError}
        />
      )}

      {view.name === 'chat' && (
        <Chat
          // Remounted per conversation, so the turns handed in below seed the
          // chat once instead of being merged into the previous one's.
          key={`${view.chatKey}:${view.bot.id}`}
          lang={lang}
          bot={view.bot}
          chatKey={view.chatKey}
          history={view.history}
          quickQuestions={view.quickQuestions}
          onReset={() => handleReset(view.chatKey)}
          onAuthError={handleAuthError}
        />
      )}
    </div>
  )
}

export default App
