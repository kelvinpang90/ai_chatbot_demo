import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import Console from './pages/Console.tsx'
import History from './pages/History.tsx'
import VerticalAdmin from './pages/VerticalAdmin.tsx'

// Four screens, one bundle, and still no router: three of them are screens in
// the room rather than the customer's flow -- the live feed during a demo, the
// transcripts afterwards, and the property agency's own back office. One path
// check remains cheaper than a dependency that would exist to express exactly
// this, and the chain stays readable until there is a fifth.
const path = window.location.pathname.replace(/\/$/, '')

const SCREENS: Record<string, React.ReactElement> = {
  '/console': <Console />,
  '/history': <History />,
  '/vertical-admin': <VerticalAdmin />,
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>{SCREENS[path] ?? <App />}</StrictMode>,
)
