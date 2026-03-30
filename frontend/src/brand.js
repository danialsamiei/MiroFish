export const APP_BRAND = 'Gantor MiroFish'
export const APP_TAGLINE = {
  fa: 'نسخه چندزبانه و فارسی‌محور موتور متن‌باز MiroFish روی QADR',
  en: 'A multilingual, Persian-first MiroFish deployment on QADR',
  zh: '部署在 QADR 上的多语言波斯语优先 MiroFish'
}
export const APP_DESCRIPTION = {
  fa: 'سامانه تحلیل، گراف‌سازی، شبیه‌سازی و گزارش‌سازی اجتماعی با تمرکز ویژه بر کاربری فارسی',
  en: 'A graph, simulation, and reporting system with a Persian-first multilingual interface',
  zh: '面向波斯语优先场景的图谱、仿真与报告系统'
}
export const APP_REPOSITORY_URL = 'https://github.com/danialsamiei/MiroFish'

export const AVAILABLE_LOCALES = [
  { value: 'fa', label: 'فارسی' },
  { value: 'en', label: 'English' },
  { value: 'zh', label: '中文' },
]

const LOCALE_STORAGE_KEY = 'gantor-mirofish-locale'
const localeListeners = new Set()

const normalizeLocale = (value) => {
  return AVAILABLE_LOCALES.some((item) => item.value === value) ? value : 'fa'
}

export const getStoredLocale = () => {
  if (typeof window === 'undefined') return 'fa'
  try {
    return normalizeLocale(window.localStorage.getItem(LOCALE_STORAGE_KEY))
  } catch {
    return 'fa'
  }
}

export const getCurrentLocale = () => getStoredLocale()

export const setCurrentLocale = (value) => {
  const next = normalizeLocale(value)
  if (typeof window !== 'undefined') {
    try {
      window.localStorage.setItem(LOCALE_STORAGE_KEY, next)
    } catch {
      /* noop */
    }
  }
  localeListeners.forEach((listener) => listener(next))
  return next
}

export const onLocaleChange = (listener) => {
  localeListeners.add(listener)
  return () => localeListeners.delete(listener)
}

export const getLocaleMeta = (locale) => {
  const active = normalizeLocale(locale)
  const rtl = active === 'fa'
  return {
    locale: active,
    lang: active === 'fa' ? 'fa' : active === 'zh' ? 'zh-CN' : 'en',
    dir: rtl ? 'rtl' : 'ltr',
    title:
      active === 'fa'
        ? `${APP_BRAND} | موتور چندعاملی، گراف و گزارش`
        : active === 'zh'
          ? `${APP_BRAND} | 群体智能、图谱与报告引擎`
          : `${APP_BRAND} | Swarm Intelligence, Graph and Report Engine`,
    description: APP_DESCRIPTION[active],
  }
}

export const localeText = (locale, variants) => {
  const active = normalizeLocale(locale)
  return variants[active] ?? variants.fa ?? variants.en ?? variants.zh ?? ''
}

export const applyLocaleToDocument = (locale) => {
  if (typeof document === 'undefined') return
  const meta = getLocaleMeta(locale)
  document.documentElement.lang = meta.lang
  document.documentElement.dir = meta.dir
  document.documentElement.dataset.locale = meta.locale
  document.documentElement.dataset.dir = meta.dir
  document.title = meta.title

  const descriptionTag = document.querySelector('meta[name="description"]')
  if (descriptionTag) {
    descriptionTag.setAttribute('content', meta.description)
  }
}
