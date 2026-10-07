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
          <label class="block text-xs text-text-muted font-bold mb-1">Modal per Koin</label>
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
            <span class="text-xs font-bold text-text-muted">USDT</span>
          </div>
          <div class="text-[11px] text-text-muted font-medium mt-0.5">≈ Rp {{ formatIDR(margin) }}</div>
        </div>

        <div class="clay-inset p-3">
          <label class="block text-xs text-text-muted font-bold mb-1">Batas Maksimal</label>
          <div class="flex items-center space-x-1">
            <input
              v-model.number="quota"
              @change="onParamChange"
              type="number"
              min="1"
              max="50"
              class="w-full bg-transparent text-base font-extrabold text-text-main font-mono focus:outline-none"
            />
            <span class="text-xs font-bold text-text-muted">Koin</span>
          </div>
          <div class="text-[11px] text-text-muted font-medium mt-0.5">Posisi bersamaan</div>
        </div>
      </div>

      <!-- Advanced strategy selectors: hidden in Simple mode (senior-friendly).
           Defaults (PUMP_GAINERS / SHORT) are applied automatically. -->
      <template v-if="!simpleMode">
        <!-- Mode Selection Dropdown -->
        <div>
          <label class="block text-xs text-text-muted font-bold mb-1">Pilihan Semesta Koin</label>
          <select
            v-model="universeMode"
            :disabled="isSessionRunning"
            class="clay-input w-full h-11 px-3 text-sm text-text-main font-semibold"
          >
            <option value="PUMP_GAINERS">PUMP_GAINERS (Semua Altcoin yang Sedang Melonjak)</option>
            <option value="MEME_ONLY">MEME_ONLY (Khusus Memecoin Populer Saja)</option>
          </select>
        </div>

        <!-- Direction Mode Selector -->
        <div>
          <label class="block text-xs text-text-muted font-bold mb-1">Arah Trading (Strategi AI)</label>
          <select
            v-model="directionMode"
            :disabled="isSessionRunning"
            class="clay-input w-full h-11 px-3 text-sm text-text-main font-semibold"
          >
            <option value="SHORT">SHORT ONLY (Koin Pucuk / Jenuh Pembeli)</option>
            <option value="LONG">LONG ONLY (Pantulan Support / Retest Sehat)</option>
            <option value="BOTH">DUA ARAH (Long &amp; Short Fleksibel Sesuai AI)</option>
          </select>
        </div>

        <!-- Direction & Strategy Mode Badge -->
        <div class="clay-inset p-2.5 flex items-center justify-between text-xs">
          <div class="space-y-0.5">
            <span class="block text-[11px] font-bold text-text-muted uppercase tracking-wider">Arah Aktif</span>
            <span class="font-extrabold text-sky-700 dark:text-sky-300">
              {{ directionMode === 'BOTH' ? 'DUA ARAH (Long & Short)' : (directionMode === 'LONG' ? 'LONG ONLY (Beli Pantulan)' : 'SHORT ONLY (Jual Pucuk)') }}
            </span>
          </div>
          <span class="text-[11px] px-2 py-0.5 rounded-full font-mono font-bold bg-sky-500/15 text-sky-700 dark:text-sky-300 border border-sky-500/30">
            {{ directionMode }}
          </span>
        </div>
      </template>
      <p v-else class="text-xs text-text-muted leading-relaxed">
        Strategi otomatis: AI memindai koin yang sedang melonjak lalu ambil posisi short saat momentum jenuh.
      </p>
    </div>

    <!-- Active Status Callout if Quota Reached -->
    <div
      v-if="isSessionRunning && isExhausted"
      class="clay-inset p-3 mb-3 bg-amber-500/10 border border-amber-500/25 rounded-2xl text-xs text-amber-900 dark:text-amber-200 leading-relaxed font-medium"
    >
      <div class="font-extrabold text-amber-700 dark:text-amber-300 mb-0.5 flex items-center space-x-1.5">
        <svg class="w-4 h-4 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="10"></circle>
          <line x1="12" y1="8" x2="12" y2="12"></line>
          <line x1="12" y1="16" x2="12.01" y2="16"></line>
        </svg>
        <span>Kuota Penuh ({{ currentFilled }}/{{ quota }}) — Bot Siaga di Server</span>
      </div>
      Bot tetap aktif di latar belakang server. Begitu Anda menutup salah satu posisi cuan di bawah, bot akan otomatis memindai dan membuka koin baru.
    </div>

    <!-- Big Action Buttons (Touch Target >= 48px) -->
    <div class="space-y-2.5">
      <!-- State 1: IDLE / TERMINATED -> Start Button (opens confirmation first) -->
      <div v-if="!isSessionRunning" class="grid grid-cols-1 gap-2">
        <button
          @click="showStartConfirm = true"
          :disabled="actionLoading"
          class="clay-btn clay-btn-emerald w-full h-12 text-sm space-x-2"
        >
          <svg class="w-4 h-4 text-white" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
            <polygon points="5 3 19 12 5 21 5 3"></polygon>
          </svg>
          <span>{{ actionLoading ? 'Menyiapkan Engine...' : 'Mulai Bot Otomatis' }}</span>
        </button>
        <p class="text-[11px] text-text-muted text-center leading-relaxed">
          Bot akan memindai pasar dan membuka posisi secara otomatis sesuai pengaturan di atas.
        </p>
      </div>

      <!-- State 2: RUNNING (ACTIVE_SEARCHING or EXHAUSTED) -> Controls -->
      <div v-else class="space-y-2.5">
        <!-- Persistent Auto-Scan Toggle (Server Daemon) -->
        <div class="clay-inset flex items-center justify-between p-2.5 text-xs">
          <label class="flex items-center space-x-2 text-text-main cursor-pointer select-none">
            <input
              type="checkbox"
              v-model="autoScan"
              @change="onAutoScanToggle"
              class="rounded border-border text-sky-600 focus:ring-0"
            />
            <span class="text-[11px] font-bold">Auto-Pindai Server Persisten</span>
          </label>
          <div class="flex items-center space-x-1.5">
            <span v-if="autoScan && isScanning" class="text-[10px] text-emerald-700 dark:text-emerald-300 font-mono font-bold bg-emerald-500/15 border border-emerald-500/30 px-2 py-0.5 rounded-full">
              Sedang memindai
            </span>
            <span v-else-if="autoScan && !isExhausted" class="text-[10px] text-sky-700 dark:text-sky-300 font-mono font-bold bg-sky-500/15 border border-sky-500/30 px-2 py-0.5 rounded-full">
              {{ countdown > 0 ? `${countdown}s lagi` : 'Menunggu server' }}
            </span>
            <span v-else-if="autoScan && isExhausted" class="text-[10px] text-amber-700 dark:text-amber-300 font-mono font-bold bg-amber-500/15 border border-amber-500/30 px-2 py-0.5 rounded-full">
              Siaga Kuota
            </span>
            <span v-else class="text-[10px] text-text-subtle font-mono font-bold bg-slate-500/15 border border-border px-2 py-0.5 rounded-full">
              Mati
            </span>
          </div>
        </div>

        <button
          @click="triggerCycle"
          :disabled="cycleLoading || isScanning"
          class="clay-btn clay-btn-sky w-full h-12 text-sm space-x-2"
        >
          <svg :class="{'animate-spin': cycleLoading || isScanning}" class="w-4 h-4 text-white" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
            <circle cx="12" cy="12" r="10"></circle>
            <polyline points="12 6 12 12 16 14"></polyline>
          </svg>
          <span>{{ (cycleLoading || isScanning) ? 'AI Sedang Menganalisis Pasar...' : 'Pindai & Analisa Pasar Sekarang' }}</span>
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

    <!-- Start confirmation modal (prevents accidental taps, explicit in Live mode) -->
    <div v-if="showStartConfirm" class="fixed inset-0 z-50 bg-black/60 flex items-end sm:items-center justify-center p-0 sm:p-4" @click.self="showStartConfirm = false">
      <div class="w-full max-w-md clay-card p-5 rounded-t-3xl sm:rounded-3xl">
        <h3 class="text-base font-extrabold text-text-main mb-2">Mulai Bot Otomatis?</h3>
        <div class="text-sm text-text-muted leading-relaxed space-y-2 mb-4">
          <p>Bot akan berjalan dengan pengaturan:</p>
          <ul class="list-disc list-inside space-y-1 font-semibold text-text-main">
            <li>Modal per koin: <span class="font-mono">${{ margin }} USDT</span> (≈ Rp {{ formatIDR(margin) }})</li>
            <li>Maksimal {{ quota }} posisi bersamaan</li>
            <li>Mode: {{ isLiveMode ? 'LIVE (uang sungguhan)' : 'Demo (uang virtual)' }}</li>
          </ul>
          <p v-if="isLiveMode" class="p-3 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-800 dark:text-rose-300 font-bold">
            Perhatian: mode LIVE menggunakan saldo USDT asli Anda. Pastikan Anda memahami risikonya.
          </p>
          <p v-else>Mode demo memakai uang virtual, aman untuk mencoba.</p>
        </div>
        <div class="grid grid-cols-2 gap-2.5">
          <button @click="showStartConfirm = false" class="clay-btn clay-btn-slate h-12 text-sm">
            Batal
          </button>
          <button @click="confirmStart" :disabled="actionLoading" class="clay-btn clay-btn-emerald h-12 text-sm">
            {{ actionLoading ? 'Memulai...' : 'Ya, Mulai Bot' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'

const props = defineProps({
  sessionState: Object,
  token: String,
  isLiveMode: Boolean,
  simpleMode: {
    type: Boolean,
    default: true
  }
})

const emit = defineEmits(['session-started', 'session-stopped', 'cycle-done', 'sync-requested'])

const margin = ref(5.0)
const quota = ref(10)
const universeMode = ref('PUMP_GAINERS')
const directionMode = ref('SHORT')
const actionLoading = ref(false)
const cycleLoading = ref(false)
const autoScan = ref(true)
const countdown = ref(60)
const showStartConfirm = ref(false)
let timerId = null

const isSessionRunning = computed(() => {
  const st = props.sessionState?.status
  return st === 'ACTIVE_SEARCHING' || st === 'EXHAUSTED'
})

const isExhausted = computed(() => {
  return props.sessionState?.status === 'EXHAUSTED'
})

const isScanning = computed(() => {
  return Boolean(props.sessionState?.is_scanning)
})

const currentFilled = computed(() => {
  return props.sessionState?.filled_count || 0
})

watch(() => props.sessionState, (newSess) => {
  if (!newSess) return
  if (newSess.margin_per_pos !== undefined) margin.value = Number(newSess.margin_per_pos)
  if (newSess.quota !== undefined) quota.value = Number(newSess.quota)
  if (newSess.auto_scan !== undefined) autoScan.value = Boolean(newSess.auto_scan)
  if (newSess.direction_mode) directionMode.value = newSess.direction_mode
  if (typeof newSess.next_scan_in === 'number') {
    countdown.value = newSess.next_scan_in
  }
}, { immediate: true, deep: true })

// Presentation-only countdown. The backend daemon owns scan scheduling.
// Never trigger a sync/cycle from this timer: doing so caused a zero-second
// feedback loop where every tick requested another account refresh.
onMounted(() => {
  timerId = setInterval(() => {
    if (isSessionRunning.value && autoScan.value && !isExhausted.value) {
      if (countdown.value > 0) {
        countdown.value -= 1
      }
    }
  }, 1000)
})

onUnmounted(() => {
  if (timerId) clearInterval(timerId)
})

async function onParamChange() {
  if (!isSessionRunning.value) return
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
    emit('sync-requested')
  } catch (err) {
    console.error('Failed to update session parameter:', err)
  }
}

async function onAutoScanToggle() {
  try {
    await fetch('/api/session/auto-scan', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${props.token}`
      },
      body: JSON.stringify({
        auto_scan: autoScan.value
      })
    })
    emit('sync-requested')
  } catch (err) {
    console.error('Failed to toggle auto scan:', err)
  }
}

function formatIDR(usdt) {
  if (!usdt) return '0'
  return Math.round(Number(usdt) * 16200).toLocaleString('id-ID')
}

async function startSession() {
  // Kept for programmatic use; UI now goes through the confirmation modal.
  showStartConfirm.value = false
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
        is_live: props.isLiveMode,
        environment: props.isLiveMode ? 'BINGX_LIVE' : 'BINGX_VST',
        execution_mode: props.isLiveMode ? 'EXCHANGE_LIVE' : 'EXCHANGE_DEMO',
        direction_mode: directionMode.value,
        exit_policy: 'MANUAL_ONLY',
        auto_scan: true,
        scan_interval: 60
      })
    })
    const data = await res.json()
    if (!res.ok) throw new Error(data.detail || 'Gagal memulai sesi.')
    autoScan.value = true
    emit('session-started', data.session)
    emit('sync-requested')
  } catch (err) {
    alert(err.message)
  } finally {
    actionLoading.value = false
  }
}

function confirmStart() {
  startSession()
}

async function stopSession() {
  actionLoading.value = true
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
    emit('sync-requested')
  } catch (err) {
    alert(err.message)
  } finally {
    actionLoading.value = false
  }
}

async function triggerCycle() {
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
    alert(err.message)
  } finally {
    cycleLoading.value = false
  }
}
</script>