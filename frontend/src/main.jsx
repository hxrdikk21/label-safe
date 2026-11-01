import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './styles.css'
import App from './App.jsx'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)

// Keep the boot loader (index.html) up for at least 0.8 s from navigation start, then fade it out.
const boot = document.getElementById('boot')
setTimeout(() => {
  boot.classList.add('is-done')
  boot.addEventListener('transitionend', () => boot.remove(), { once: true })
  setTimeout(() => boot.remove(), 500) // no transition with reduced motion or a hidden tab
}, Math.max(0, 800 - performance.now()))
