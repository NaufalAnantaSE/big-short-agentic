<template>
  <div class="bg-surface border border-border rounded-2xl p-4 shadow-sm">
    <div class="flex items-center justify-between pb-3 border-b border-border/60 mb-3">
      <div class="flex items-center space-x-2">
        <span class="text-xs font-bold text-slate-400 uppercase tracking-wider">Status Akun BingX</span>
        <span :class="statusBadgeClass" class="text-[10px] font-bold px-2 py-0.5 rounded-full border">
          {{ statusBadgeLabel }}
        </span>
      </div>
      <button
        @click="$emit('refresh')"
        :disabled="loading"
        class="text-xs text-sky-400 hover:text-sky-300 font-medium flex items-center space-x-1"
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
      <div class="text-[11px] font-semibold text-slate-400">Total Saldo Aktif</div>
      <div class="flex items-baseline space-x-2 mt-0.5">
        <span class="text-2xl font-extrabold text-slate-50 tracking-tight">
          {{ formatNumber(summary.balance) }}
        </span>
        <span class="text-sm font-bold text-sky-400">{{ summary.asset || 'USDT' }}</span>
      </div>
      <div class="text-xs text-slate-400 font-medium mt-0.5">
        Sekitar Rp {{ formatIDR(summary.balance) }}
      </div>
    </div>

    <!-- Secondary Metrics Grid -->
    <div class="grid grid-cols-2 gap-2 pt-2 border-t border-border/50 text-xs">
      <div class="bg-slate-900/60 p-2.5 rounded-xl border border-border/60">
        <div class="text-[10px] text-slate-400 font-medium">Ekuitas Akun</div>
        <div class="font-bold text-slate-200 text-sm mt-0.5">
          ${{ formatNumber(summary.equity) }}
        </div>
      </div>
      <div class="bg-slate-900/60 p-2.5 rounded-xl border border-border/60">
        <div class="text-[10px] text-slate-400 font-medium">Margin Terpakai</div>
        <div class="font-bold text-slate-200 text-sm mt-0.5">
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
  if (st === 'ACTIVE_SEARCHING') return 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30'
  if (st === 'EXHAUSTED') return 'bg-amber-500/10 text-amber-400 border-amber-500/30'
  return 'bg-slate-800 text-slate-400 border-border'
})
</script>
