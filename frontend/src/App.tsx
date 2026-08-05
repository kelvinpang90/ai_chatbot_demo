import { useState } from 'react'
import './App.css'
import LanguageSwitcher from './components/LanguageSwitcher'
import PasswordGate from './pages/PasswordGate'
import BotSelect from './pages/BotSelect'
import { clearToken, getToken, type BotSummary } from './api'
import { DEFAULT_LANG, type Lang } from './i18n/strings'

type View = { name: 'password' } | { name: 'botSelect' } | { name: 'selected'; bot: BotSummary }

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
          onSelect={(bot) => setView({ name: 'selected', bot })}
          onAuthError={handleAuthError}
        />
      )}

      {view.name === 'selected' && (
        <div className="page-centered">
          <p>
            Selected: {view.bot.icon} {view.bot.name} — identity selection lands in task 12.
          </p>
        </div>
      )}
    </div>
  )
}

export default App
