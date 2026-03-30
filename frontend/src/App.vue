<template>
  <div class="miro-shell">
    <header class="miro-shell-header">
      <div class="miro-shell-brand">
        <strong>{{ APP_BRAND }}</strong>
        <span>{{ tagline }}</span>
      </div>
      <div class="miro-shell-actions">
        <select class="miro-shell-select" :value="locale" @change="handleLocaleChange">
          <option v-for="item in AVAILABLE_LOCALES" :key="item.value" :value="item.value">
            {{ item.label }}
          </option>
        </select>
        <a class="miro-shell-link" :href="APP_REPOSITORY_URL" target="_blank" rel="noreferrer">
          {{ repoLabel }}
        </a>
      </div>
    </header>
    <div v-if="degradedBanner" class="miro-degraded-banner">
      {{ degradedBanner }}
    </div>
    <div class="miro-shell-content">
      <router-view />
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import {
  APP_BRAND,
  APP_REPOSITORY_URL,
  APP_TAGLINE,
  AVAILABLE_LOCALES,
  applyLocaleToDocument,
  getCurrentLocale,
  localeText,
  onLocaleChange,
  setCurrentLocale,
} from './brand'

const locale = ref(getCurrentLocale())
const backendHealth = ref(null)

const tagline = computed(() => localeText(locale.value, APP_TAGLINE))
const repoLabel = computed(() =>
  localeText(locale.value, {
    fa: 'فورک GitHub',
    en: 'GitHub Fork',
    zh: 'GitHub Fork',
  })
)
const degradedBanner = computed(() => {
  if (!backendHealth.value?.degraded) return ''
  return localeText(locale.value, {
    fa: 'این نسخه در حالت تنزل‌یافته اجرا می‌شود. تولید هستی‌شناسی فعال است، اما مسیر کامل گراف و شبیه‌سازی به ZEP وابسته است.',
    en: 'This deployment is running in degraded mode. Ontology generation is available, but full graph and simulation flows still depend on ZEP.',
    zh: '当前部署处于降级模式。本体生成可用，但完整图谱与仿真流程仍依赖 ZEP。',
  })
})

let unsubscribe = null

const syncLocale = (next) => {
  locale.value = next
  applyLocaleToDocument(next)
}

const handleLocaleChange = (event) => {
  syncLocale(setCurrentLocale(event.target.value))
}

onMounted(() => {
  unsubscribe = onLocaleChange(syncLocale)
  syncLocale(locale.value)
  fetch('/api/health')
    .then((response) => response.ok ? response.json() : null)
    .then((data) => { backendHealth.value = data })
    .catch(() => { backendHealth.value = null })
})

onBeforeUnmount(() => {
  unsubscribe?.()
})
</script>

<style scoped>
</style>
