<template>
  <div class="min-h-screen bg-background text-text-main flex flex-col justify-between font-sans selection:bg-sky-500 selection:text-white transition-colors duration-200">
    <!-- Unauthenticated View -->
    <AuthView
      v-if="!token"
      :is-dark="isDark"
      @toggle-theme="toggleTheme"
      @auth-success="handleAuthSuccess"
    />

    <!-- Authenticated Mobile Webview -->
    <div v-else class="flex-1 flex flex-col max-w-md w-full mx-auto pb-10">
      <!-- Top Navbar -->
      <Navbar
        :user="user"
        :is-demo="isDemo"
        :is-dark="isDark"
        :simple-mode="simpleMode"
        :is-syncing="isSyncing"
        @toggle-theme="toggleTheme"
        @toggle-simple="simpleMode = !simpleMode"
        @open-settings="showApiKeyModal = true"
        @logout="handleLogout"
        @sync-now="onSyncNow"
      />

      <!-- Main Content Scroll Area -->
      <main class="p-4 flex-1">
        <!-- Render Admin Dashboard if Admin -->
        <AdminDashboard
          v-if="user.role === 'admin'"
          :token="token"
          :is-dark="isDark"
        />

        <!-- Render Trader Dashboard if Trader / Client -->
        <TraderDashboard
          v-else
          ref="traderDashboardRef"
          :token="token"
          :user="user"
          :is-demo="isDemo"
          :is-dark="isDark"
          :simple-mode="simpleMode"
          @update-user="handleUserUpdate"
          @sync-status-changed="onSyncStatusChanged"
        />
      </main>

      <!-- Global API Key Modal Triggered from Navbar (for trader) -->
      <ApiKeyOnboardingModal
        v-if="showApiKeyModal && user.role !== 'admin'"
        :token="token"
        :can-close="user.has_keys"
        :initial-is-demo="isDemo"
        :is-dark="isDark"
        @close="showApiKeyModal = false"
        @saved="onApiKeySaved"
      />
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import Navbar from './components/Navbar.vue'
import AuthView from './components/AuthView.vue'
import AdminDashboard from './components/AdminDashboard.vue'
import TraderDashboard from './components/TraderDashboard.vue'
import ApiKeyOnboardingModal from './components/ApiKeyOnboardingModal.vue'

// Reactive state
const token = ref(localStorage.getItem('bx_token') || '')
const user = ref(JSON.parse(localStorage.getItem('bx_user') || 'null') || {})
const isDemo = ref(user.value.is_demo !== false)
const simpleMode = ref(true)
const showApiKeyModal = ref(false)
const traderDashboardRef = ref(null)
const isSyncing = ref(false)

// Theme Management (Claymorphism Dark / Light)
const savedTheme = localStorage.getItem('bx_theme')
const isDark = ref(savedTheme !== 'light') // Default to dark

function applyTheme(dark) {
  if (dark) {
    document.documentElement.classList.add('dark')
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', '#0b0f19')
  } else {
    document.documentElement.classList.remove('dark')
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', '#edf2f7')
  }
}

function toggleTheme() {
  isDark.value = !isDark.value
  localStorage.setItem('bx_theme', isDark.value ? 'dark' : 'light')
  applyTheme(isDark.value)
}

function handleAuthSuccess(data) {
  token.value = data.token
  user.value = data.user
  isDemo.value = data.user.is_demo !== false
  localStorage.setItem('bx_token', data.token)
  localStorage.setItem('bx_user', JSON.stringify(data.user))
}

function handleLogout() {
  token.value = ''
  user.value = {}
  isDemo.value = true
  showApiKeyModal.value = false
  localStorage.removeItem('bx_token')
  localStorage.removeItem('bx_user')
}

function handleUserUpdate(patch) {
  user.value = { ...user.value, ...patch }
  if (patch.is_demo !== undefined) isDemo.value = patch.is_demo
  localStorage.setItem('bx_user', JSON.stringify(user.value))
}

function onApiKeySaved(payload) {
  showApiKeyModal.value = false
  handleUserUpdate({ has_keys: true, is_demo: payload.isDemo })
}

function onSyncNow() {
  if (traderDashboardRef.value && traderDashboardRef.value.syncNow) {
    traderDashboardRef.value.syncNow()
  }
}

function onSyncStatusChanged(val) {
  isSyncing.value = Boolean(val)
}

async function verifyAuthSession() {
  if (!token.value) return
  try {
    const res = await fetch('/api/auth/me', {
      headers: { 'Authorization': `Bearer ${token.value}` }
    })
    if (!res.ok) {
      handleLogout()
      return
    }
    const data = await res.json()
    user.value = data
    isDemo.value = data.is_demo !== false
    localStorage.setItem('bx_user', JSON.stringify(data))
  } catch (err) {
    console.error('Failed to verify session:', err)
  }
}

onMounted(() => {
  applyTheme(isDark.value)
  if (token.value) {
    verifyAuthSession()
  }
})
</script>