import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import {
  APP_BRAND,
  applyLocaleToDocument,
  getStoredLocale,
  onLocaleChange,
} from './brand'
import { installUiLocalization } from './localize-ui'
import { installBidiTextEnhancer } from './bidi'
import './theme.css'

const THEME_KEY = 'gantor-mirofish-theme'

const readThemePreference = () => {
  try {
    const stored = localStorage.getItem(THEME_KEY)
    if (stored === 'auto' || stored === 'dark' || stored === 'light') return stored
  } catch {
    /* noop */
  }
  return 'auto'
}

const resolveTheme = (preference) => {
  if (preference === 'dark' || preference === 'light') return preference
  return window.matchMedia?.('(prefers-color-scheme: light)').matches ? 'light' : 'dark'
}

const applyTheme = () => {
  const effective = resolveTheme(readThemePreference())
  document.documentElement.dataset.theme = effective
  document.documentElement.style.colorScheme = effective
}

applyLocaleToDocument(getStoredLocale())
document.title = APP_BRAND
applyTheme()

if (window.matchMedia) {
  const media = window.matchMedia('(prefers-color-scheme: light)')
  media.addEventListener('change', () => {
    if (readThemePreference() === 'auto') applyTheme()
  })
}

window.addEventListener('storage', (event) => {
  if (event.key === THEME_KEY) {
    applyTheme()
  }
})

const app = createApp(App)

app.use(router)

app.mount('#app')

const root = document.body
installUiLocalization(root, getStoredLocale, onLocaleChange)
installBidiTextEnhancer(root)
