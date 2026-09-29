<template>
  <div class="min-h-screen flex items-center justify-center p-4 bg-background">
    <div class="w-full max-w-md bg-surface border border-border rounded-2xl p-6 shadow-xl">
      <!-- Header -->
      <div class="text-center mb-6">
        <div class="w-12 h-12 rounded-xl bg-sky-500/10 border border-sky-500/20 flex items-center justify-center text-sky-400 mx-auto mb-3">
          <svg class="w-6 h-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="22 7 13.5 15.5 8.5 10.5 2 17"></polyline>
            <polyline points="16 7 22 7 22 13"></polyline>
          </svg>
        </div>
        <h2 class="text-xl font-bold text-slate-100">BingX Agent Portal</h2>
        <p class="text-xs text-slate-400 mt-1">Platform Eksekusi Short Memecoin Berbasis AI</p>
      </div>

      <!-- Error Alert -->
      <div v-if="errorMsg" class="mb-4 p-3 rounded-lg bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs leading-relaxed flex items-start space-x-2">
        <svg class="w-4 h-4 shrink-0 mt-0.5 text-rose-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="10"></circle>
          <line x1="12" y1="8" x2="12" y2="12"></line>
          <line x1="12" y1="16" x2="12.01" y2="16"></line>
        </svg>
        <span>{{ errorMsg }}</span>
      </div>

      <!-- Login Form (Single clean form, no public register) -->
      <form @submit.prevent="handleSubmit" class="space-y-4">
        <div>
          <label class="block text-xs font-semibold text-slate-300 mb-1.5">Nama Pengguna (Username)</label>
          <input
            v-model="form.username"
            type="text"
            required
            autocomplete="username"
            placeholder="Masukkan username akun Anda"
            class="w-full h-12 px-3.5 rounded-xl bg-slate-900/90 border border-border text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-sky-500 transition"
          />
        </div>

        <div>
          <label class="block text-xs font-semibold text-slate-300 mb-1.5">Kata Sandi (Password)</label>
          <input
            v-model="form.password"
            type="password"
            required
            autocomplete="current-password"
            placeholder="Masukkan kata sandi"
            class="w-full h-12 px-3.5 rounded-xl bg-slate-900/90 border border-border text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-sky-500 transition"
          />
        </div>

        <button
          type="submit"
          :disabled="loading"
          class="w-full h-12 bg-sky-600 hover:bg-sky-500 active:bg-sky-700 text-white rounded-xl font-semibold text-sm transition shadow-lg shadow-sky-600/20 flex items-center justify-center space-x-2 disabled:opacity-50 mt-2"
        >
          <svg v-if="loading" class="animate-spin w-4 h-4 text-white" viewBox="0 0 24 24" fill="none">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"></path>
          </svg>
          <span>{{ loading ? 'Memverifikasi Akun...' : 'Masuk ke Aplikasi' }}</span>
        </button>
      </form>

      <!-- Client Access Notice -->
      <div class="mt-6 pt-4 border-t border-border/80 text-center space-y-1.5">
        <p class="text-xs font-semibold text-slate-300">Belum memiliki akun klien?</p>
        <p class="text-[11px] text-slate-400 leading-relaxed">
          Pendaftaran akun privat dilakukan melalui Admin setelah aktivasi langganan. Hubungi <span class="text-sky-400 font-semibold">Naufal Ananta</span> untuk pembuatan kredensial akses Anda.
        </p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive } from 'vue'

const emit = defineEmits(['auth-success'])

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
