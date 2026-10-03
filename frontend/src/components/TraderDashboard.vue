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

    <!-- 1. Account Summary Card (Saldo & Ekuitas) -->
    <AccountSummaryCard
      :summary="summary"
      :loading="refreshing"
      @refresh="fetchAccountSummary"
    />

    <!-- 2. Bot Operations Control Card (Mulai & Hentikan) -->
    <BotControlCard
      :session-state="summary.session"
      :token="token"
      :is-live-mode="!isDemo"
      @session-started="onSessionStarted"
      @session-stopped="onSessionStopped"
      @cycle-done="onCycleDone"
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
      @position-closed="fetchAccountSummary"
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
import { ref, onMounted } from 'vue'
import ApiKeyOnboardingModal from './ApiKeyOnboardingModal.vue'
import AccountSummaryCard from './AccountSummaryCard.vue'
import BotControlCard from './BotControlCard.vue'
import CandidateRadarCard from './CandidateRadarCard.vue'
import ActivePositionsCard from './ActivePositionsCard.vue'

const props = defineProps({
  token: String,
  user: Object,
  isDemo: Boolean,
  simpleMode: Boolean
})

const emit = defineEmits(['update-user'])

const summary = ref({
  balance: 0,
  equity: 0,
  used_margin: 0,
  asset: 'VST',
  active_positions: [],
  session: { status: 'IDLE', filled_count: 0, quota: 10 }
})
const evaluations = ref([])
const refreshing = ref(false)
const showApiKeyModal = ref(false)

async function fetchAccountSummary() {
  if (!props.token || !props.user.has_keys) return
  refreshing.value = true
  try {
    const res = await fetch('/api/account/summary', {
      headers: { 'Authorization': `Bearer ${props.token}` }
    })
    const data = await res.json()
    if (res.ok) {
      summary.value = data
    }
  } catch (err) {
    console.error('Failed to fetch summary:', err)
  } finally {
    refreshing.value = false
  }
}

function onApiKeySaved(payload) {
  showApiKeyModal.value = false
  emit('update-user', { has_keys: true, is_demo: payload.isDemo })
  fetchAccountSummary()
}

function onSessionStarted(sess) {
  summary.value.session = {
    ...summary.value.session,
    ...sess,
    status: 'ACTIVE_SEARCHING'
  }
}

function onSessionStopped(res) {
  summary.value.session = {
    ...summary.value.session,
    status: 'TERMINATED'
  }
}

function onCycleDone(cycleData) {
  if (cycleData.evaluations) {
    evaluations.value = cycleData.evaluations
  }
  fetchAccountSummary()
}

onMounted(() => {
  if (props.user.has_keys) {
    fetchAccountSummary()
  } else {
    showApiKeyModal.value = true
  }
})
</script>
