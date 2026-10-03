<template>
  <div class="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-end sm:items-center justify-center p-0 sm:p-4">
    <div class="w-full max-w-md clay-card border-t sm:border border-border rounded-t-3xl sm:rounded-3xl p-5 shadow-2xl max-h-[92vh] overflow-y-auto">
      <!-- Header -->
      <div class="flex items-center justify-between pb-3 border-b border-border mb-4">
        <div class="flex items-center space-x-2">
          <div class="w-8 h-8 rounded-xl bg-sky-500/15 border border-sky-500/30 flex items-center justify-center text-sky-600 dark:text-sky-400 shadow-sm">
            <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect>
              <path d="M7 11V7a5 5 0 0 1 10 0v4"></path>
            </svg>
          </div>
          <h3 class="text-sm font-extrabold text-text-main">Kunci API Akun BingX</h3>
        </div>
        <button
          v-if="canClose"
          @click="$emit('close')"
          class="p-1.5 rounded-xl text-text-subtle hover:text-text-main clay-btn clay-btn-slate"
        >
          <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="18" y1="6" x2="6" y2="18"></line>
            <line x1="6" y1="6" x2="18" y2="18"></line>
          </svg>
        </button>
      </div>

      <!-- Informative Senior-Friendly Callout -->
      <div class="p-3.5 rounded-2xl bg-sky-500/10 border border-sky-500/25 text-xs text-text-muted leading-relaxed mb-4">
        <p class="font-extrabold text-sky-700 dark:text-sky-300 mb-1">Keamanan Data Terjamin</p>
        Kunci API Anda disimpan dalam bentuk terenkripsi khusus untuk akun Anda sendiri dan tidak dapat dibaca oleh pengguna lain. Bot hanya meminta izin trading futures, <strong class="text-text-main font-bold">tanpa izin penarikan uang (withdrawal)</strong>.
      </div>

      <!-- Form -->
      <form @submit.prevent="saveKeys" class="space-y-4">
        <!-- Environment Selection -->
        <div>
          <label class="block text-xs font-bold text-text-muted mb-1.5">Pilihan Akun BingX</label>
          <div class="grid grid-cols-2 gap-2.5">
            <button
              type="button"
              @click="isDemo = true"
              :class="isDemo ? 'bg-sky-500/20 border-sky-500 text-sky-700 dark:text-sky-300 font-extrabold shadow-sm' : 'clay-inset text-text-subtle'"
              class="p-3 rounded-2xl border text-left transition clay-btn"
            >
              <div class="text-xs font-extrabold">Akun Demo (VST)</div>
              <div class="text-[10px] mt-0.5 opacity-80">Simulasi uang virtual tanpa resiko modal asli.</div>
            </button>
            <button
              type="button"
              @click="isDemo = false"
              :class="!isDemo ? 'bg-emerald-500/20 border-emerald-500 text-emerald-700 dark:text-emerald-300 font-extrabold shadow-sm' : 'clay-inset text-text-subtle'"
              class="p-3 rounded-2xl border text-left transition clay-btn"
            >
              <div class="text-xs font-extrabold">Akun Riil (Live)</div>
              <div class="text-[10px] mt-0.5 opacity-80">Trading langsung menggunakan saldo USDT riil.</div>
            </button>
          </div>
        </div>

        <div>
          <label class="block text-xs font-bold text-text-muted mb-1">API Key BingX</label>
          <input
            v-model="apiKey"
            type="text"
            required
            placeholder="Tempel API Key dari BingX di sini"
            class="clay-input w-full h-11 px-3.5 text-xs font-mono font-medium"
          />
        </div>

        <div>
          <label class="block text-xs font-bold text-text-muted mb-1">Secret Key BingX</label>
          <input
            v-model="secretKey"
            type="password"
            required
            placeholder="Tempel Secret Key di sini"
            class="clay-input w-full h-11 px-3.5 text-xs font-mono font-medium"
          />
        </div>

        <!-- Notification Message -->
        <div v-if="msg" :class="isSuccess ? 'bg-emerald-500/15 border-emerald-500/30 text-emerald-800 dark:text-emerald-300' : 'bg-rose-500/15 border-rose-500/30 text-rose-800 dark:text-rose-300'" class="p-3 rounded-xl border text-xs leading-relaxed font-semibold">
          {{ msg }}
        </div>

        <button
          type="submit"
          :disabled="loading"
          class="clay-btn clay-btn-sky w-full h-12 text-xs space-x-2"
        >
          <svg v-if="loading" class="animate-spin w-4 h-4 text-white" viewBox="0 0 24 24" fill="none">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"></path>
          </svg>
          <span>{{ loading ? 'Memverifikasi ke BingX...' : 'Simpan Kunci API & Hubungkan' }}</span>
        </button>
      </form>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'

const props = defineProps({
  token: String,
  canClose: {
    type: Boolean,
    default: false
  },
  initialIsDemo: {
    type: Boolean,
    default: true
  }
})

const emit = defineEmits(['close', 'saved'])

const apiKey = ref('')
const secretKey = ref('')
const isDemo = ref(props.initialIsDemo)
const loading = ref(false)
const msg = ref('')
const isSuccess = ref(false)

async function saveKeys() {
  loading.value = true
  msg.value = ''
  try {
    const res = await fetch('/api/credentials', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${props.token}`
      },
      body: JSON.stringify({
        api_key: apiKey.value,
        secret_key: secretKey.value,
        is_demo: isDemo.value
      })
    })
    const data = await res.json()
    if (!res.ok) throw new Error(data.detail || 'Gagal menyimpan kunci API.')
    
    isSuccess.value = true
    msg.value = data.message || 'Kunci API berhasil disimpan!'
    setTimeout(() => {
      emit('saved', { isDemo: isDemo.value })
    }, 1000)
  } catch (err) {
    isSuccess.value = false
    msg.value = err.message
  } finally {
    loading.value = false
  }
}
</script>
