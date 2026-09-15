import { useState } from 'react'
import './App.css'
import LanguageSwitcher from './components/LanguageSwitcher'
import PhoneEntry from './pages/PhoneEntry'
import BotSelect from './pages/BotSelect'
import Chat from './pages/Chat'
import { TokenGate } from './pages/VerticalAdmin'
import {
  resetSession,
  selectBot,
  storedToken,
  type BotSummary,
  type ChatTurn,
  type IdentifyResponse,
} from './api'
import { DEFAULT_LANG, STRINGS, type Lang } from './i18n/strings'

type View =
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
  const [view, setView] = useState<View>({ name: 'phone' })
  // Operator only since task 29.1 -- see `chatRequest` in api.ts.
  const [unlocked, setUnlocked] = useState(() => storedToken() !== '')

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
    } catch {
      // Staying on the menu is the honest outcome: nothing was started.
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

  if (!unlocked) {
    return (
      <TokenGate
        note=""
        title="💬 Web chat"
        blurb="网页聊天仅供演示人员使用。需要 console token（服务器上的 CONSOLE_TOKEN）。"
        onUnlocked={() => setUnlocked(true)}
      />
    )
  }

  return (
    <div className="app-shell" data-view={view.name}>
      <header className="top-bar">
        <span className="top-bar-title">
          <span className="top-bar-logo" aria-hidden="true">
            💬
          </span>
          {STRINGS[lang].appTitle}
        </span>
        <LanguageSwitcher lang={lang} onChange={setLang} />
      </header>

      {view.name === 'phone' && <PhoneEntry lang={lang} onIdentified={handleIdentified} />}

      {view.name === 'botSelect' && (
        <BotSelect lang={lang} onSelect={(bot) => handleBotSelected(view.chatKey, bot)} />
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
        />
      )}
    </div>
  )
}

export default App
