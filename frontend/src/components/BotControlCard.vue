<template>
  <div class="bg-surface border border-border rounded-2xl p-4 shadow-sm">
    <div class="flex items-center justify-between pb-3 border-b border-border/60 mb-3">
      <span class="text-xs font-bold text-slate-300 uppercase tracking-wider">Kendali Operasi Bot</span>
      <span class="text-[11px] font-semibold text-slate-400">
        Kuota: <strong class="text-sky-400">{{ currentFilled }}</strong> / {{ quota }} posisi
      </span>
    </div>

    <!-- Parameter Config (Simple & Senior-Friendly) -->
    <div class="space-y-3 mb-4">
      <div class="grid grid-cols-2 gap-2">
        <div class="bg-slate-900/80 p-3 rounded-xl border border-border">
          <label class="block text-[11px] text-slate-400 font-semibold mb-1">Modal per Koin</label>
          <div class="flex items-center space-x-1">
            <span class="text-base font-extrabold text-slate-100">$</span>
            <input
              v-model.number="margin"
              :disabled="isActive"
              type="number"
              min="1"
              max="500"
              step="1"
              class="w-full bg-transparent text-base font-extrabold text-slate-100 focus:outline-none"
            />
            <span class="text-[11px] font-bold text-slate-400">USDT</span>
          </div>
          <div class="text-[10px] text-slate-500 mt-0.5">≈ Rp {{ formatIDR(margin) }}</div>
        </div>

        <div class="bg-slate-900/80 p-3 rounded-xl border border-border">
          <label class="block text-[11px] text-slate-400 font-semibold mb-1">Batas Maksimal</label>
          <div class="flex items-center space-x-1">
            <input
              v-model.number="quota"
              :disabled="isActive"
              type="number"
              min="1"
              max="20"
              class="w-full bg-transparent text-base font-extrabold text-slate-100 focus:outline-none"
            />
            <span class="text-[11px] font-bold text-slate-400">Koin</span>
          </div>
          <div class="text-[10px] text-slate-500 mt-0.5">Posisi bersamaan</div>
        </div>
      </div>

      <!-- Mode Selection Dropdown -->
      <div>
        <label class="block text-[11px] text-slate-400 font-semibold mb-1">Pilihan Semesta Koin</label>
        <select
          v-model="universeMode"
          :disabled="isActive"
          class="w-full h-11 px-3 rounded-xl bg-slate-900 border border-border text-xs text-slate-100 font-medium focus:outline-none focus:border-sky-500"
        >
          <option value="PUMP_GAINERS">PUMP_GAINERS (Semua Altcoin yang Sedang Melonjak)</option>
          <option value="MEME_ONLY">MEME_ONLY (Khusus Memecoin Populer Saja)</option>
        </select>
      </div>
    </div>

    <!-- Big Action Buttons (Touch Target >= 48px) -->
    <div class="space-y-2.5">
      <div v-if="!isActive" class="grid grid-cols-1 gap-2">
        <button
          @click="startSession"
          :disabled="actionLoading"
          class="w-full h-12 rounded-xl bg-emerald-600 hover:bg-emerald-500 active:bg-emerald-700 text-white font-bold text-sm transition shadow-lg shadow-emerald-600/20 flex items-center justify-center space-x-2 disabled:opacity-50"
        >
          <svg class="w-4 h-4 text-white" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
            <polygon points="5 3 19 12 5 21 5 3"></polygon>
          </svg>
          <span>{{ actionLoading ? 'Menyiapkan...' : 'Mulai Bot Otomatis' }}</span>
        </button>
      </div>

      <div v-else class="space-y-2.5">
        <!-- Auto-Scan Periodic Toggle -->
        <div class="flex items-center justify-between p-2.5 rounded-xl bg-slate-900/90 border border-border text-xs">
          <label class="flex items-center space-x-2 text-slate-300 cursor-pointer select-none">
            <input type="checkbox" v-model="autoScan" class="rounded border-border bg-slate-950 text-sky-600 focus:ring-0" />
            <span class="text-[11px] font-medium">Auto-Pindai Otomatis (Tiap 60s)</span>
          </label>
          <span v-if="autoScan" class="text-[10px] text-sky-400 font-mono font-bold bg-sky-500/10 border border-sky-500/30 px-2 py-0.5 rounded-md">
            {{ autoScanCountdown }}s lagi
          </span>
        </div>

        <button
          @click="triggerCycle"
          :disabled="cycleLoading"
          class="w-full h-12 rounded-xl bg-sky-600 hover:bg-sky-500 active:bg-sky-700 text-white font-bold text-sm transition shadow-lg shadow-sky-600/20 flex items-center justify-center space-x-2 disabled:opacity-50"
        >
          <svg :class="{'animate-spin': cycleLoading}" class="w-4 h-4 text-white" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
            <circle cx="12" cy="12" r="10"></circle>
            <polyline points="12 6 12 12 16 14"></polyline>
          </svg>
          <span>{{ cycleLoading ? 'AI Sedang Menganalisis Koin...' : 'Pindai & Analisa Pasar Sekarang' }}</span>
        </button>

        <button
          @click="stopSession"
          :disabled="actionLoading"
          class="w-full h-11 rounded-xl bg-rose-600/20 hover:bg-rose-600/30 text-rose-300 border border-rose-500/30 font-semibold text-xs transition flex items-center justify-center space-x-2 disabled:opacity-50"
        >
          <svg class="w-3.5 h-3.5 text-rose-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
            <rect x="6" y="6" width="12" height="12"></rect>
          </svg>
          <span>Hentikan Pencarian Bot</span>
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onUnmounted } from 'vue'

const props = defineProps({
  sessionState: Object,
  token: String,
  isLiveMode: Boolean
})

const emit = defineEmits(['session-started', 'session-stopped', 'cycle-done'])

const margin = ref(5.0)
const quota = ref(10)
const universeMode = ref('PUMP_GAINERS')
const actionLoading = ref(false)
const cycleLoading = ref(false)
const autoScan = ref(false)
const autoScanCountdown = ref(60)
let timerId = null

const isActive = computed(() => {
  return props.sessionState?.status === 'ACTIVE_SEARCHING'
})

const currentFilled = computed(() => {
  return props.sessionState?.filled_count || 0
})

function formatIDR(usdt) {
  if (!usdt) return '0'
  return Math.round(Number(usdt) * 16200).toLocaleString('id-ID')
}

// Auto-scan timer ticker
watch([isActive, autoScan], ([active, auto]) => {
  if (timerId) {
    clearInterval(timerId)
    timerId = null
  }

  if (active && auto) {
    autoScanCountdown.value = 60
    timerId = setInterval(() => {
      if (cycleLoading.value) return
      autoScanCountdown.value -= 1
      if (autoScanCountdown.value <= 0) {
        autoScanCountdown.value = 60
        triggerCycle()
      }
    }, 1000)
  }
})

onUnmounted(() => {
  if (timerId) clearInterval(timerId)
})

async function startSession() {
  actionLoading.value = true
  try {
    const res = await fetch('/api/session/start', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${props.token}`
      },
      body: JSON.stringify({
        margin_per_pos: margin.value,
        leverage: 20,
        quota: quota.value,
        mode: universeMode.value,
        is_live: props.isLiveMode
      })
    })
    const data = await res.json()
    if (!res.ok) throw new Error(data.detail || 'Gagal memulai sesi.')
    emit('session-started', data.session)
  } catch (err) {
    alert(err.message)
  } finally {
    actionLoading.value = false
  }
}

async function stopSession() {
  actionLoading.value = true
  autoScan.value = false
  try {
    const res = await fetch('/api/session/stop', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${props.token}`
      }
    })
    const data = await res.json()
    if (!res.ok) throw new Error(data.detail || 'Gagal menghentikan sesi.')
    emit('session-stopped', data.result)
  } catch (err) {
    alert(err.message)
  } finally {
    actionLoading.value = false
  }
}

async function triggerCycle() {
  if (cycleLoading.value) return
  cycleLoading.value = true
  try {
    const res = await fetch('/api/session/cycle', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${props.token}`
      },
      body: JSON.stringify({
        dry_run: !props.isLiveMode
      })
    })
    const data = await res.json()
    if (!res.ok) throw new Error(data.detail || 'Gagal menjalankan pemindaian.')
    emit('cycle-done', data.data)
  } catch (err) {
    console.error(err)
  } finally {
    cycleLoading.value = false
  }
}
</script>
