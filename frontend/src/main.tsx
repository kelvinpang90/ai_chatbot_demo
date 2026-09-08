import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import Console from './pages/Console.tsx'
import History from './pages/History.tsx'

// Three screens, one bundle, and still no router: two of them are the operator's
// -- the live feed during a demo, the transcripts afterwards -- and neither is
// part of the customer's flow. One path check remains cheaper than a dependency
// that would exist to express exactly this.
const path = window.location.pathname.replace(/\/$/, '')

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {path === '/console' ? <Console /> : path === '/history' ? <History /> : <App />}
  </StrictMode>,
)
