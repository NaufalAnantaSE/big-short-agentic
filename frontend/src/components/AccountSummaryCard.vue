<template>
  <div class="clay-card p-4">
    <div class="flex items-center justify-between pb-3 border-b border-border mb-3">
      <div class="flex items-center space-x-2">
        <span class="text-xs font-bold text-text-muted uppercase tracking-wider">Status Akun BingX</span>
        <span :class="statusBadgeClass" class="text-[10px] font-bold px-2.5 py-0.5 rounded-full border shadow-sm">
          {{ statusBadgeLabel }}
        </span>
      </div>
      <button
        @click="$emit('refresh')"
        :disabled="loading"
        class="text-xs text-sky-600 dark:text-sky-400 hover:underline font-bold flex items-center space-x-1"
      >
        <svg :class="{'animate-spin': loading}" class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polyline points="23 4 23 10 17 10"></polyline>
          <polyline points="1 20 1 14 7 14"></polyline>
          <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path>
        </svg>
        <span>Perbarui</span>
      </button>
    </div>

    <!-- Main Balance Display (Large for high legibility) -->
    <div class="mb-4">
      <div class="text-[11px] font-semibold text-text-subtle">Total Saldo Aktif</div>
      <div class="flex items-baseline space-x-2 mt-0.5">
        <span class="text-2xl font-extrabold text-text-main tracking-tight font-mono">
          {{ formatNumber(summary.balance) }}
        </span>
        <span class="text-sm font-extrabold text-sky-600 dark:text-sky-400">{{ summary.asset || 'USDT' }}</span>
      </div>
      <div class="text-xs text-text-subtle font-medium mt-0.5">
        Sekitar Rp {{ formatIDR(summary.balance) }}
      </div>
    </div>

    <!-- Secondary Metrics Grid (Recessed Inset Wells) -->
    <div class="grid grid-cols-2 gap-2.5 pt-2 border-t border-border text-xs">
      <div class="clay-inset p-3">
        <div class="text-[10px] text-text-subtle font-semibold">Ekuitas Akun</div>
        <div class="font-extrabold text-text-main text-sm mt-0.5 font-mono">
          ${{ formatNumber(summary.equity) }}
        </div>
      </div>
      <div class="clay-inset p-3">
        <div class="text-[10px] text-text-subtle font-semibold">Margin Terpakai</div>
        <div class="font-extrabold text-text-main text-sm mt-0.5 font-mono">
          ${{ formatNumber(summary.used_margin) }}
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  summary: {
    type: Object,
    default: () => ({
      balance: 0,
      equity: 0,
      used_margin: 0,
      asset: 'VST',
      session: { status: 'IDLE' }
    })
  },
  loading: Boolean
})

defineEmits(['refresh'])

function formatNumber(num) {
  if (num === undefined || num === null) return '0.00'
  return Number(num).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function formatIDR(usdt) {
  if (!usdt) return '0'
  const val = Number(usdt) * 16200
  return Math.round(val).toLocaleString('id-ID')
}

const statusBadgeLabel = computed(() => {
  const st = props.summary.session?.status || 'IDLE'
  if (st === 'ACTIVE_SEARCHING') return 'Bot Aktif Mencari Koin'
  if (st === 'EXHAUSTED') return 'Batas Kuota Tercapai'
  if (st === 'TERMINATED') return 'Bot Dihentikan'
  return 'Bot Standby (Diam)'
})

const statusBadgeClass = computed(() => {
  const st = props.summary.session?.status || 'IDLE'
  if (st === 'ACTIVE_SEARCHING') return 'bg-emerald-100 dark:bg-emerald-500/20 text-emerald-900 dark:text-emerald-300 border-emerald-300 dark:border-emerald-500/40 font-extrabold'
  if (st === 'EXHAUSTED') return 'bg-amber-100 dark:bg-amber-500/25 text-amber-900 dark:text-amber-200 border-amber-300 dark:border-amber-500/40 font-extrabold'
  return 'bg-slate-200 dark:bg-slate-800 text-slate-800 dark:text-slate-200 border-border font-extrabold'
})
</script>
