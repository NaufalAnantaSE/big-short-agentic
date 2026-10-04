<template>
  <div class="space-y-4">
    <!-- API Missing Warning Banner -->
    <div
      v-if="!user.has_keys"
      class="clay-card p-4 bg-amber-500/10 border-amber-500/30 text-amber-900 dark:text-amber-200 text-xs leading-relaxed flex items-start justify-between gap-3 shadow-md"
    >
      <div class="space-y-1">
        <div class="font-extrabold text-amber-700 dark:text-amber-300 text-sm">Hubungkan Akun BingX Anda</div>
        <p class="text-text-muted text-[11px] font-medium">
          Kunci API diperlukan agar bot dapat membaca saldo dan mengeksekusi posisi pada akun BingX Anda.
        </p>
      </div>
      <button
        @click="showApiKeyModal = true"
        class="clay-btn bg-amber-500 hover:bg-amber-400 text-slate-950 font-extrabold px-3.5 py-2 text-xs shrink-0 shadow-sm"
      >
        Hubungkan
      </button>
    </div>

    <!-- 1. Account Summary Card (Saldo, Ekuitas & Tombol Sync) -->
    <AccountSummaryCard
      :summary="summary"
      :loading="refreshing"
      @refresh="syncNow"
    />

    <!-- 2. Bot Operations Control Card (Mulai & Hentikan & Auto-Scan) -->
    <BotControlCard
      :session-state="summary.session"
      :token="token"
      :is-live-mode="!isDemo"
      @session-started="onSessionStarted"
      @session-stopped="onSessionStopped"
      @cycle-done="onCycleDone"
      @sync-requested="syncNow"
    />

    <!-- 3. Candidate Radar (Analisa AI Ramah Lansia & Detail) -->
    <CandidateRadarCard
      :evaluations="evaluations"
      :simple-mode="simpleMode"
    />

    <!-- 4. Active Positions (Posisi Terbuka) -->
    <ActivePositionsCard
      :positions="summary.active_positions || []"
      :token="token"
      @position-closed="syncNow"
    />

    <!-- API Key Settings Modal -->
    <ApiKeyOnboardingModal
      v-if="showApiKeyModal"
      :token="token"
      :can-close="user.has_keys"
      :initial-is-demo="isDemo"
      @close="showApiKeyModal = false"
      @saved="onApiKeySaved"
    />
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import ApiKeyOnboardingModal from './ApiKeyOnboardingModal.vue'
import AccountSummaryCard from './AccountSummaryCard.vue'
import BotControlCard from './BotControlCard.vue'
import CandidateRadarCard from './CandidateRadarCard.vue'
import ActivePositionsCard from './ActivePositionsCard.vue'

const props = defineProps({
  token: String,
  user: Object,
  isDemo: Boolean,
  simpleMode: Boolean,
  syncTrigger: Number
})

const emit = defineEmits(['update-user', 'sync-status-changed'])

const summary = ref({
  balance: 0,
  equity: 0,
  used_margin: 0,
  asset: 'VST',
  active_positions: [],
  session: { status: 'IDLE', filled_count: 0, quota: 10, auto_scan: true, next_scan_in: 0 },
  last_sync_at: null
})
const evaluations = ref([])
const refreshing = ref(false)
const showApiKeyModal = ref(false)
let pollTimer = null

async function syncNow() {
  if (!props.token || !props.user.has_keys || refreshing.value) return
  refreshing.value = true
  emit('sync-status-changed', true)
  try {
    const res = await fetch('/api/account/sync', {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${props.token}` }
    })
    const data = await res.json()
    if (res.ok) {
      summary.value = data
      if (Array.isArray(data.latest_evaluations) && data.latest_evaluations.length > 0) {
        evaluations.value = data.latest_evaluations
      }
    }
  } catch (err) {
    console.error('Failed to sync BingX data:', err)
  } finally {
    refreshing.value = false
    emit('sync-status-changed', false)
  }
}

// Background poller for dynamic real-time data
async function pollSummary() {
  if (!props.token || !props.user.has_keys || refreshing.value) return
  // Don't poll if document is hidden to conserve battery/bandwidth
  if (typeof document !== 'undefined' && document.visibilityState !== 'visible') return

  try {
    const res = await fetch('/api/account/summary', {
      headers: { 'Authorization': `Bearer ${props.token}` }
    })
    const data = await res.json()
    if (res.ok) {
      summary.value = data
      if (Array.isArray(data.latest_evaluations) && data.latest_evaluations.length > 0) {
        evaluations.value = data.latest_evaluations
      }
    }
  } catch (err) {
    // Silent fail on background poll
  }
}

function onApiKeySaved(payload) {
  showApiKeyModal.value = false
  emit('update-user', { has_keys: true, is_demo: payload.isDemo })
  syncNow()
}

function onSessionStarted(sess) {
  summary.value.session = {
    ...summary.value.session,
    ...sess,
    status: 'ACTIVE_SEARCHING'
  }
  syncNow()
}

function onSessionStopped(res) {
  summary.value.session = {
    ...summary.value.session,
    status: 'TERMINATED',
    auto_scan: false
  }
  syncNow()
}

function onCycleDone(cycleData) {
  if (cycleData && cycleData.evaluations) {
    evaluations.value = cycleData.evaluations
  }
  syncNow()
}

onMounted(() => {
  if (props.user.has_keys) {
    syncNow()
  } else {
    showApiKeyModal.value = true
  }

  // Dynamic Polling: controlled account/state refresh every 10 seconds.
  // Scanning itself is server-owned and never triggered by this timer.
  pollTimer = setInterval(pollSummary, 10000)
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})

defineExpose({
  syncNow
})
</script>