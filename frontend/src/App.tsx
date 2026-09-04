import { useState } from 'react'
import './App.css'
import LanguageSwitcher from './components/LanguageSwitcher'
import PasswordGate from './pages/PasswordGate'
import BotSelect from './pages/BotSelect'
import Chat from './pages/Chat'
import { clearToken, createSessionId, getToken, type BotSummary } from './api'
import { DEFAULT_LANG, type Lang } from './i18n/strings'

type View =
  | { name: 'password' }
  | { name: 'botSelect' }
  | { name: 'chat'; bot: BotSummary; sessionId: string }

function App() {
  const [lang, setLang] = useState<Lang>(DEFAULT_LANG)
  const [view, setView] = useState<View>(() => (getToken() ? { name: 'botSelect' } : { name: 'password' }))

  function handleAuthError() {
    clearToken()
    setView({ name: 'password' })
  }

  return (
    <div className="app-shell">
      <LanguageSwitcher lang={lang} onChange={setLang} />

      {view.name === 'password' && (
        <PasswordGate lang={lang} onSuccess={() => setView({ name: 'botSelect' })} />
      )}

      {view.name === 'botSelect' && (
        <BotSelect
          lang={lang}
          onSelect={(bot) => setView({ name: 'chat', bot, sessionId: createSessionId() })}
          onAuthError={handleAuthError}
        />
      )}

      {view.name === 'chat' && (
        <Chat
          lang={lang}
          bot={view.bot}
          sessionId={view.sessionId}
          onAuthError={handleAuthError}
        />
      )}
    </div>
  )
}

export default App
