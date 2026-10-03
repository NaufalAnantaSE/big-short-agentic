<template>
  <div class="clay-card p-4">
    <div class="flex items-center justify-between pb-3 border-b border-border mb-3">
      <div class="flex items-center space-x-2">
        <span class="text-xs font-bold text-text-muted uppercase tracking-wider">Posisi Terbuka (BingX)</span>
      </div>
      <span class="text-[11px] font-extrabold text-sky-600 dark:text-sky-400">
        {{ positions.length }} Posisi Berjalan
      </span>
    </div>

    <!-- Empty State -->
    <div v-if="positions.length === 0" class="py-6 text-center">
      <p class="text-xs text-text-muted font-semibold">Tidak ada posisi terbuka saat ini.</p>
      <p class="text-[11px] text-text-subtle mt-0.5">Seluruh modal Anda aman di saldo kas.</p>
    </div>

    <!-- Position Cards -->
    <div v-else class="space-y-3">
      <div
        v-for="(p, idx) in positions"
        :key="idx"
        class="clay-inset p-3.5"
      >
        <div class="flex items-center justify-between mb-2">
          <div class="flex items-center space-x-2">
            <span class="text-sm font-extrabold text-text-main font-mono">{{ p.symbol }}</span>
            <span class="text-[10px] font-bold px-1.5 py-0.5 rounded-md bg-rose-500/15 text-rose-700 dark:text-rose-300 border border-rose-500/30 uppercase">
              SHORT {{ p.leverage }}x
            </span>
          </div>
          <!-- PnL -->
          <div :class="p.unrealized_pnl >= 0 ? 'text-emerald-600 dark:text-emerald-400' : 'text-rose-600 dark:text-rose-400'" class="text-right">
            <div class="text-xs font-extrabold font-mono">
              {{ p.unrealized_pnl >= 0 ? '+' : '' }}${{ Number(p.unrealized_pnl).toFixed(2) }}
            </div>
            <div class="text-[10px] font-bold font-mono">
              {{ p.unrealized_pnl >= 0 ? '+' : '' }}{{ Number(p.pnl_pct).toFixed(1) }}%
            </div>
          </div>
        </div>

        <div class="grid grid-cols-3 gap-1 py-2 border-y border-border/60 text-[11px]">
          <div>
            <div class="text-[10px] text-text-subtle font-semibold">Harga Masuk</div>
            <div class="font-mono text-text-main font-semibold">{{ p.entry_price }}</div>
          </div>
          <div>
            <div class="text-[10px] text-text-subtle font-semibold">Harga Sekarang</div>
            <div class="font-mono text-text-main font-semibold">{{ p.mark_price }}</div>
          </div>
          <div>
            <div class="text-[10px] text-text-subtle font-semibold">Margin Dipakai</div>
            <div class="font-mono text-text-main font-semibold">${{ Number(p.initial_margin).toFixed(2) }}</div>
          </div>
        </div>

        <!-- Touch-Friendly Close Position Button -->
        <div class="mt-2.5">
          <button
            @click="handleClosePosition(p.symbol, p.position_side)"
            :disabled="closingSymbol === p.symbol"
            class="clay-btn clay-btn-slate w-full h-10 text-xs font-bold space-x-1.5"
          >
            <svg v-if="closingSymbol === p.symbol" class="animate-spin w-3.5 h-3.5 text-text-muted" viewBox="0 0 24 24" fill="none">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"></path>
            </svg>
            <span v-else>
              <svg class="w-3.5 h-3.5 inline mr-1 text-amber-500 dark:text-amber-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="10"></circle>
                <line x1="15" y1="9" x2="9" y2="15"></line>
                <line x1="9" y1="9" x2="15" y2="15"></line>
              </svg>
            </span>
            <span>{{ closingSymbol === p.symbol ? 'Menutup Posisi...' : 'Tutup Posisi Sekarang (Ambil Untung)' }}</span>
          </button>
        </div>
      </div>

      <!-- Exit Note -->
      <div class="clay-inset p-3 text-[11px] text-text-subtle leading-relaxed mt-3">
        <strong class="text-text-main font-bold">Kontrol Penutupan Posisi:</strong> Anda dapat menutup posisi kapan saja langsung melalui tombol di atas, atau menutupnya melalui aplikasi resmi BingX. Bot tidak menutup posisi tanpa persetujuan Anda.
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'

const props = defineProps({
  positions: {
    type: Array,
    default: () => []
  },
  token: String
})

const emit = defineEmits(['position-closed'])
const closingSymbol = ref('')

async function handleClosePosition(symbol, positionSide) {
  if (!confirm(`Tutup posisi ${symbol} di harga pasar saat ini?`)) return

  closingSymbol.value = symbol
  try {
    const res = await fetch('/api/position/close', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${props.token}`
      },
      body: JSON.stringify({
        symbol: symbol,
        position_side: positionSide || 'SHORT'
      })
    })
    const data = await res.json()
    if (!res.ok) throw new Error(data.detail || 'Gagal menutup posisi.')
    alert(data.message || `Posisi ${symbol} berhasil ditutup.`)
    emit('position-closed')
  } catch (err) {
    alert(err.message)
  } finally {
    closingSymbol.value = ''
  }
}
</script>
