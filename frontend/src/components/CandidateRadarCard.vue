<template>
  <div class="bg-surface border border-border rounded-2xl p-4 shadow-sm">
    <div class="flex items-center justify-between pb-3 border-b border-border/60 mb-3">
      <div class="flex items-center space-x-2">
        <div class="w-2 h-2 rounded-full bg-sky-400 animate-pulse"></div>
        <span class="text-xs font-bold text-slate-300 uppercase tracking-wider">Hasil Analisa AI Pasar</span>
      </div>
      <span class="text-[11px] text-slate-400 font-medium">
        {{ evaluations.length }} Koin Terpantau
      </span>
    </div>

    <!-- Empty State -->
    <div v-if="evaluations.length === 0" class="py-8 text-center">
      <div class="w-10 h-10 rounded-xl bg-slate-900 border border-border flex items-center justify-center text-slate-500 mx-auto mb-2">
        <svg class="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="11" cy="11" r="8"></circle>
          <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
        </svg>
      </div>
      <p class="text-xs text-slate-300 font-semibold">Belum Ada Koin yang Dipindai</p>
      <p class="text-[11px] text-slate-500 mt-1 max-w-[260px] mx-auto">
        Tekan tombol <span class="text-sky-400 font-semibold">"Pindai & Analisa Pasar"</span> di atas untuk meminta AI memeriksa peluang koin saat ini.
      </p>
    </div>

    <!-- List of Candidates -->
    <div v-else class="space-y-3">
      <div
        v-for="(item, idx) in evaluations"
        :key="idx"
        class="bg-slate-900/90 border border-border/80 rounded-xl p-3.5 transition"
      >
        <!-- Card Header -->
        <div class="flex items-start justify-between gap-2 mb-2">
          <div>
            <div class="flex items-center space-x-2">
              <span class="text-sm font-extrabold text-slate-100 tracking-tight">{{ item.clean_symbol }}</span>
              <span class="text-[11px] font-mono text-slate-400 font-semibold">{{ item.price_formatted }}</span>
            </div>
            <div class="text-[11px] text-slate-400 font-medium mt-0.5">
              {{ item.confidence_text }}
            </div>
          </div>

          <!-- Decision Badge -->
          <span :class="badgeClass(item.badge_color)" class="text-[10px] font-bold px-2 py-0.5 rounded-full border shrink-0">
            {{ item.badge_label }}
          </span>
        </div>

        <!-- Senior-Friendly Simple View -->
        <div v-if="simpleMode" class="space-y-2 mt-2 pt-2 border-t border-border/50 text-xs">
          <!-- Summary Title -->
          <div class="font-bold text-slate-200 leading-snug">
            {{ item.summary_title }}
          </div>

          <!-- Plain Indonesian Reason -->
          <p class="text-slate-300 text-[11px] leading-relaxed bg-slate-950/60 p-2.5 rounded-lg border border-border/40">
            {{ item.plain_reason }}
          </p>

          <!-- Capital Note -->
          <div class="flex items-center space-x-1.5 text-[10px] text-slate-400">
            <svg class="w-3.5 h-3.5 text-sky-400 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="12" cy="12" r="10"></circle>
              <line x1="12" y1="16" x2="12" y2="12"></line>
              <line x1="12" y1="8" x2="12.01" y2="8"></line>
            </svg>
            <span>{{ item.capital_note }}</span>
          </div>

          <!-- Execution Status -->
          <div v-if="item.executed" class="p-2 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-emerald-300 text-[11px] font-semibold">
            Order Jual Berhasil Dikirim ke BingX (Order ID: {{ item.order_id }})
          </div>
          <div v-else-if="item.dry_run && item.decision === 'ENTER_SHORT'" class="p-2 rounded-lg bg-sky-500/10 border border-sky-500/20 text-sky-300 text-[11px] font-semibold">
            Simulasi Selesai: Sinyal siap eksekusi lot {{ item.quantity }} koin.
          </div>
        </div>

        <!-- Technical Detail View (For Expert Analysts) -->
        <div v-else class="space-y-2 mt-2 pt-2 border-t border-border/50 text-[11px] font-mono">
          <div class="text-slate-300">
            <span class="text-slate-500 font-sans">Evidence:</span> {{ item.raw_evidence || '-' }}
          </div>
          <div v-if="item.raw_risk" class="text-slate-400">
            <span class="text-slate-500 font-sans">Risk Factors:</span> {{ item.raw_risk }}
          </div>
          <div class="text-slate-400 flex items-center space-x-3 pt-1 border-t border-border/30">
            <span>Lot: {{ item.quantity }}</span>
            <span>Notional: ${{ Number(item.notional || 0).toFixed(2) }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
defineProps({
  evaluations: {
    type: Array,
    default: () => []
  },
  simpleMode: {
    type: Boolean,
    default: true
  }
})

function badgeClass(color) {
  if (color === 'emerald') return 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30'
  if (color === 'amber') return 'bg-amber-500/15 text-amber-400 border-amber-500/30'
  return 'bg-slate-800 text-slate-400 border-border'
}
</script>
