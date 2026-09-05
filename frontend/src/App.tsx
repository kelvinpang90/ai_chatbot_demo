import { useState } from 'react'
import './App.css'
import LanguageSwitcher from './components/LanguageSwitcher'
import PhoneEntry from './pages/PhoneEntry'
import BotSelect from './pages/BotSelect'
import Chat from './pages/Chat'
import { resetSession, selectBot, type BotSummary, type ChatTurn, type IdentifyResponse } from './api'
import { DEFAULT_LANG, type Lang } from './i18n/strings'

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

  return (
    <div className="app-shell">
      <LanguageSwitcher lang={lang} onChange={setLang} />

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
