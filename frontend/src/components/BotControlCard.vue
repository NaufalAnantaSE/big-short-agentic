<template>
  <div class="clay-card p-4">
    <div class="flex items-center justify-between pb-3 border-b border-border mb-3">
      <span class="text-xs font-bold text-text-muted uppercase tracking-wider">Kendali Operasi Bot</span>
      <span class="text-[11px] font-semibold text-text-muted">
        Kuota: <strong class="text-sky-600 dark:text-sky-400 font-extrabold">{{ currentFilled }}</strong> / {{ quota }} posisi
      </span>
    </div>

    <!-- Parameter Config (Simple & Senior-Friendly) -->
    <div class="space-y-3 mb-4">
      <div class="grid grid-cols-2 gap-2.5">
        <div class="clay-inset p-3">
          <label class="block text-[11px] text-text-subtle font-bold mb-1">Modal per Koin</label>
          <div class="flex items-center space-x-1">
            <span class="text-base font-extrabold text-text-main font-mono">$</span>
            <input
              v-model.number="margin"
              @change="onParamChange"
              type="number"
              min="1"
              max="500"
              step="1"
              class="w-full bg-transparent text-base font-extrabold text-text-main font-mono focus:outline-none"
            />
            <span class="text-[11px] font-bold text-text-subtle">USDT</span>
          </div>
          <div class="text-[10px] text-text-subtle font-medium mt-0.5">≈ Rp {{ formatIDR(margin) }}</div>
        </div>

        <div class="clay-inset p-3">
          <label class="block text-[11px] text-text-subtle font-bold mb-1">Batas Maksimal</label>
          <div class="flex items-center space-x-1">
            <input
              v-model.number="quota"
              @change="onParamChange"
              type="number"
              min="1"
              max="50"
              class="w-full bg-transparent text-base font-extrabold text-text-main font-mono focus:outline-none"
            />
            <span class="text-[11px] font-bold text-text-subtle">Koin</span>
          </div>
          <div class="text-[10px] text-text-subtle font-medium mt-0.5">Posisi bersamaan</div>
        </div>
      </div>

      <!-- Mode Selection Dropdown -->
      <div>
        <label class="block text-[11px] text-text-subtle font-bold mb-1">Pilihan Semesta Koin</label>
        <select
          v-model="universeMode"
          :disabled="isActive"
          class="clay-input w-full h-11 px-3 text-xs text-text-main font-semibold"
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
          class="clay-btn clay-btn-emerald w-full h-12 text-sm space-x-2"
        >
          <svg class="w-4 h-4 text-white" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
            <polygon points="5 3 19 12 5 21 5 3"></polygon>
          </svg>
          <span>{{ actionLoading ? 'Menyiapkan...' : 'Mulai Bot Otomatis' }}</span>
        </button>
      </div>

      <div v-else class="space-y-2.5">
        <!-- Auto-Scan Periodic Toggle -->
        <div class="clay-inset flex items-center justify-between p-2.5 text-xs">
          <label class="flex items-center space-x-2 text-text-main cursor-pointer select-none">
            <input type="checkbox" v-model="autoScan" class="rounded border-border text-sky-600 focus:ring-0" />
            <span class="text-[11px] font-bold">Auto-Pindai Otomatis (Tiap 60s)</span>
          </label>
          <span v-if="autoScan" class="text-[10px] text-sky-700 dark:text-sky-300 font-mono font-bold bg-sky-500/15 border border-sky-500/30 px-2 py-0.5 rounded-full">
            {{ autoScanCountdown }}s lagi
          </span>
        </div>

        <button
          @click="triggerCycle"
          :disabled="cycleLoading"
          class="clay-btn clay-btn-sky w-full h-12 text-sm space-x-2"
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
          class="clay-btn clay-btn-rose w-full h-11 text-xs space-x-2"
        >
          <svg class="w-3.5 h-3.5 text-white" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
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

watch(() => props.sessionState, (newSess) => {
  if (newSess?.margin_per_pos) margin.value = Number(newSess.margin_per_pos)
  if (newSess?.quota) quota.value = Number(newSess.quota)
}, { immediate: true })

async function onParamChange() {
  if (!isActive.value) return
  try {
    await fetch('/api/session/update', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${props.token}`
      },
      body: JSON.stringify({
        margin_per_pos: margin.value,
        quota: quota.value
      })
    })
  } catch (err) {
    console.error('Failed to update session parameter:', err)
  }
}

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

    // Langsung aktifkan mode auto-scan dan eksekusi cycle pemindaian pertama secara instan
    autoScan.value = true
    await triggerCycle()
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
        dry_run: false // Selalu eksekusi riil ke BingX API (baik VST Demo maupun Live)
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
