<template>
  <div class="min-h-screen flex items-center justify-center p-4 bg-background transition-colors duration-200">
    <div class="w-full max-w-md clay-card p-6 relative">
      <!-- Theme Switcher in Auth Screen -->
      <div class="absolute top-4 right-4">
        <button
          @click="$emit('toggle-theme')"
          class="p-2 rounded-xl border border-border clay-btn clay-btn-slate transition"
          :title="isDark ? 'Ganti ke Mode Terang' : 'Ganti ke Mode Gelap'"
        >
          <svg v-if="isDark" class="w-4 h-4 text-amber-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="5"></circle>
            <line x1="12" y1="1" x2="12" y2="3"></line>
            <line x1="12" y1="21" x2="12" y2="23"></line>
            <line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line>
            <line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line>
            <line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line>
          </svg>
          <svg v-else class="w-4 h-4 text-slate-700" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path>
          </svg>
        </button>
      </div>

      <!-- Header -->
      <div class="text-center mb-6 pt-2">
        <div class="w-14 h-14 rounded-2xl bg-sky-500/15 border border-sky-500/30 flex items-center justify-center text-sky-600 dark:text-sky-400 mx-auto mb-3 shadow-sm">
          <svg class="w-7 h-7" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="22 7 13.5 15.5 8.5 10.5 2 17"></polyline>
            <polyline points="16 7 22 7 22 13"></polyline>
          </svg>
        </div>
        <h2 class="text-xl font-extrabold text-text-main tracking-tight">BingX Agent Portal</h2>
        <p class="text-xs text-text-subtle font-medium mt-1">Platform Eksekusi Short Memecoin Berbasis AI</p>
      </div>

      <!-- Error Alert -->
      <div v-if="errorMsg" class="mb-4 p-3 rounded-xl bg-rose-500/15 border border-rose-500/30 text-rose-800 dark:text-rose-300 text-xs leading-relaxed flex items-start space-x-2 font-medium">
        <svg class="w-4 h-4 shrink-0 mt-0.5 text-rose-600 dark:text-rose-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="10"></circle>
          <line x1="12" y1="8" x2="12" y2="12"></line>
          <line x1="12" y1="16" x2="12.01" y2="16"></line>
        </svg>
        <span>{{ errorMsg }}</span>
      </div>

      <!-- Login Form (Single clean form, no public register) -->
      <form @submit.prevent="handleSubmit" class="space-y-4">
        <div>
          <label class="block text-xs font-bold text-text-muted mb-1.5">Nama Pengguna (Username)</label>
          <input
            v-model="form.username"
            type="text"
            required
            autocomplete="username"
            placeholder="Masukkan username akun Anda"
            class="clay-input w-full h-12 px-3.5 text-sm placeholder:text-text-subtle font-medium"
          />
        </div>

        <div>
          <label class="block text-xs font-bold text-text-muted mb-1.5">Kata Sandi (Password)</label>
          <input
            v-model="form.password"
            type="password"
            required
            autocomplete="current-password"
            placeholder="Masukkan kata sandi"
            class="clay-input w-full h-12 px-3.5 text-sm placeholder:text-text-subtle font-medium"
          />
        </div>

        <button
          type="submit"
          :disabled="loading"
          class="clay-btn clay-btn-sky w-full h-12 text-sm mt-2 space-x-2"
        >
          <svg v-if="loading" class="animate-spin w-4 h-4 text-white" viewBox="0 0 24 24" fill="none">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"></path>
          </svg>
          <span>{{ loading ? 'Memverifikasi Akun...' : 'Masuk ke Aplikasi' }}</span>
        </button>
      </form>

      <!-- Client Access Notice -->
      <div class="mt-6 pt-4 border-t border-border text-center space-y-1.5">
        <p class="text-xs font-bold text-text-main">Belum memiliki akun klien?</p>
        <p class="text-[11px] text-text-subtle leading-relaxed">
          Pendaftaran akun privat dilakukan melalui Admin setelah aktivasi langganan. Hubungi <span class="text-sky-600 dark:text-sky-400 font-bold">Naufal Ananta</span> untuk pembuatan kredensial akses Anda.
        </p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive } from 'vue'

defineProps({
  isDark: Boolean
})
const emit = defineEmits(['auth-success', 'toggle-theme'])

const loading = ref(false)
const errorMsg = ref('')

const form = reactive({
  username: '',
  password: ''
})

async function handleSubmit() {
  errorMsg.value = ''
  loading.value = true

  try {
    const res = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(form)
    })
    const data = await res.json()
    if (!res.ok) {
      throw new Error(data.detail || 'Username atau kata sandi tidak cocok.')
    }
    emit('auth-success', data)
  } catch (err) {
    errorMsg.value = err.message
  } finally {
    loading.value = false
  }
}
</script>
