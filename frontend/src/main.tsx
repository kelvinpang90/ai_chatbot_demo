import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import Console from './pages/Console.tsx'
import FoodAdmin from './pages/FoodAdmin.tsx'
import VerticalAdmin from './pages/VerticalAdmin.tsx'
import Privacy from './pages/Privacy.tsx'

// Four screens, one bundle, and still no router: three of them are screens in
// the room rather than the customer's flow -- the console, the property agency's
// own back office, and the notice we publish. One path check remains cheaper
// than a dependency that would exist to express exactly this.
const path = window.location.pathname.replace(/\/$/, '')

const SCREENS: Record<string, React.ReactElement> = {
  '/console': <Console />,
  // The transcript page became a view of the console (task 37.6). The old path
  // still opens it, so a bookmark from before does not land on the customer demo.
  '/history': <Console />,
  '/vertical-admin': <VerticalAdmin />,
  '/food-admin': <FoodAdmin />,
  // The public one (task 29.3). It is in this table rather than inside `App`
  // precisely because `App` asks for the console token first, and the Meta
  // reviewer who follows the app's privacy link has no token to type.
  '/privacy': <Privacy />,
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>{SCREENS[path] ?? <App />}</StrictMode>,
)
