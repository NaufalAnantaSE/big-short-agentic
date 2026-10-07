<template>
  <div class="clay-card p-4">
    <div class="flex items-center justify-between pb-3 border-b border-border mb-3">
      <div class="flex items-center space-x-2">
        <div class="w-2.5 h-2.5 rounded-full bg-sky-500 animate-pulse"></div>
        <span class="text-xs font-bold text-text-muted uppercase tracking-wider">Hasil Analisa AI Pasar</span>
      </div>
      <span class="text-[11px] text-text-subtle font-semibold">
        {{ evaluations.length }} Koin Terpantau
      </span>
    </div>

    <!-- Empty State -->
    <div v-if="evaluations.length === 0" class="py-8 text-center">
      <div class="w-12 h-12 rounded-2xl clay-inset flex items-center justify-center text-text-subtle mx-auto mb-2">
        <svg class="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="11" cy="11" r="8"></circle>
          <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
        </svg>
      </div>
      <p class="text-xs text-text-main font-bold">Belum Ada Koin yang Dipindai</p>
      <p class="text-[11px] text-text-subtle mt-1 max-w-[260px] mx-auto leading-relaxed">
        Tekan tombol <span class="text-emerald-600 dark:text-emerald-400 font-extrabold">"Mulai Bot Otomatis"</span> di atas untuk memulai pemindaian koin dan analisa pasar mandiri oleh AI.
      </p>
    </div>

    <!-- List of Candidates -->
    <div v-else class="space-y-3">
      <div
        v-for="(item, idx) in evaluations"
        :key="idx"
        class="clay-inset p-3.5 transition"
      >
        <!-- Card Header -->
        <div class="flex items-start justify-between gap-2 mb-2">
          <div>
            <div class="flex items-center space-x-2">
              <span class="text-sm font-extrabold text-text-main font-mono tracking-tight">{{ item.clean_symbol }}</span>
              <span class="text-[11px] font-mono text-text-subtle font-semibold">{{ item.price_formatted }}</span>
            </div>
            <div class="text-[11px] text-text-subtle font-medium mt-0.5">
              {{ item.confidence_text }}
            </div>
          </div>

          <!-- Decision Badge -->
          <span :class="badgeClass(item.badge_color)" class="text-[10px] font-extrabold px-2.5 py-0.5 rounded-full border shrink-0 shadow-sm">
            {{ item.badge_label }}
          </span>
        </div>

        <!-- Metric Badges Row (Playbook, Fibonacci, Wave, Funding, RSI, Bollinger, EMA) -->
        <div class="flex flex-wrap items-center gap-1.5 mb-2.5">
          <span
            v-if="item.playbook && item.playbook.playbook && item.playbook.playbook !== 'NONE'"
            class="text-[9px] px-2 py-0.5 rounded-md font-bold bg-primary/15 border border-primary/30 text-primary flex items-center gap-1"
          >
            <span class="w-1.5 h-1.5 rounded-full bg-primary animate-pulse"></span>
            ⚡ {{ item.playbook.title_id || item.playbook_title }} ({{ item.playbook.score || item.playbook_score }}%)
          </span>
          <span
            v-if="item.fibonacci_zone"
            :class="fibBadgeClass(item.fibonacci_zone)"
            class="text-[9px] px-2 py-0.5 rounded-md font-bold border"
          >
            Fib: {{ formatFibZone(item.fibonacci_zone, item.fibonacci_retracement) }}
          </span>
          <span
            v-if="item.rsi && item.rsi.valid"
            :class="rsiBadgeClass(item.rsi)"
            class="text-[9px] px-2 py-0.5 rounded-md font-bold border"
          >
            RSI: {{ Math.round(item.rsi.rsi_15m) }}{{ item.rsi.divergence === 'BEARISH_DIV' ? ' (Bearish Div)' : (item.rsi.divergence === 'BULLISH_DIV' ? ' (Bullish Div)' : '') }}
          </span>
          <span
            v-if="item.bollinger && item.bollinger.valid && (item.bollinger.is_overextended_upper || item.bollinger.is_overextended_lower || item.bollinger.is_squeeze)"
            class="text-[9px] px-2 py-0.5 rounded-md font-bold bg-purple-500/15 border border-purple-500/30 text-purple-700 dark:text-purple-300"
          >
            BB: {{ item.bollinger.is_overextended_upper ? 'Ext Atas' : (item.bollinger.is_overextended_lower ? 'Ext Bawah' : 'Squeeze') }}
          </span>
          <span
            v-if="item.ema_trend && item.ema_trend.valid"
            :class="item.ema_trend.trend === 'STRONG_UPTREND' ? 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border-emerald-500/20' : (item.ema_trend.trend === 'STRONG_DOWNTREND' ? 'bg-rose-500/10 text-rose-700 dark:text-rose-300 border-rose-500/20' : 'bg-slate-500/10 text-slate-700 dark:text-slate-300 border-border')"
            class="text-[9px] px-2 py-0.5 rounded-md font-bold border"
          >
            EMA: {{ item.ema_trend.trend === 'STRONG_UPTREND' ? 'Uptrend' : (item.ema_trend.trend === 'STRONG_DOWNTREND' ? 'Downtrend' : 'Netral') }}
          </span>
          <span
            v-if="item.exhaustion_score !== null && item.exhaustion_score !== undefined"
            class="text-[9px] px-2 py-0.5 rounded-md font-bold bg-indigo-500/15 border border-indigo-500/30 text-indigo-700 dark:text-indigo-300"
          >
            Skor Jenuh: {{ item.exhaustion_score }}/100
          </span>
          <span
            v-if="item.funding_note"
            class="text-[9px] px-2 py-0.5 rounded-md font-bold bg-amber-500/15 border border-amber-500/30 text-amber-700 dark:text-amber-300"
          >
            Funding Aktif
          </span>
        </div>

        <!-- Senior-Friendly Simple View -->
        <div v-if="simpleMode" class="space-y-2 mt-2 pt-2 border-t border-border/60 text-xs">
          <!-- Summary Title -->
          <div class="font-extrabold text-text-main leading-snug">
            {{ item.summary_title }}
          </div>

          <!-- Plain Indonesian Reason -->
          <p class="text-text-muted text-[11px] leading-relaxed bg-surface/80 p-2.5 rounded-xl border border-border">
            {{ item.plain_reason }}
          </p>

          <!-- Strategy Playbook Context -->
          <div v-if="item.playbook && item.playbook.playbook && item.playbook.playbook !== 'NONE'" class="p-2.5 rounded-xl bg-primary/10 border border-primary/20 text-[11px] space-y-1">
            <div class="flex items-center justify-between text-primary font-bold text-[10px] uppercase">
              <span>🎯 {{ item.playbook.title_id }}</span>
              <span class="font-mono">Kecocokan {{ item.playbook.score }}%</span>
            </div>
            <p class="text-text-main text-[11px] leading-relaxed">
              {{ item.playbook.explanation_id }}
            </p>
          </div>

          <!-- Quantitative Insights (Fibonacci / Wave / Funding / RSI / BB / EMA) -->
          <div v-if="item.fibonacci_note || item.wave_note || item.funding_note || item.rsi_note || item.bb_note || item.ema_note" class="space-y-1 bg-surface/60 p-2.5 rounded-xl border border-border text-[11px]">
            <div v-if="item.fibonacci_note" class="flex items-start space-x-1.5 text-sky-700 dark:text-sky-300 font-medium">
              <span class="w-1.5 h-1.5 rounded-full bg-sky-500 mt-1 shrink-0"></span>
              <span>{{ item.fibonacci_note }}</span>
            </div>
            <div v-if="item.rsi_note" class="flex items-start space-x-1.5 text-violet-700 dark:text-violet-300 font-medium">
              <span class="w-1.5 h-1.5 rounded-full bg-violet-500 mt-1 shrink-0"></span>
              <span>{{ item.rsi_note }}</span>
            </div>
            <div v-if="item.bb_note" class="flex items-start space-x-1.5 text-purple-700 dark:text-purple-300 font-medium">
              <span class="w-1.5 h-1.5 rounded-full bg-purple-500 mt-1 shrink-0"></span>
              <span>{{ item.bb_note }}</span>
            </div>
            <div v-if="item.ema_note" class="flex items-start space-x-1.5 text-cyan-700 dark:text-cyan-300 font-medium">
              <span class="w-1.5 h-1.5 rounded-full bg-cyan-500 mt-1 shrink-0"></span>
              <span>{{ item.ema_note }}</span>
            </div>
            <div v-if="item.wave_note" class="flex items-start space-x-1.5 text-indigo-700 dark:text-indigo-300 font-medium">
              <span class="w-1.5 h-1.5 rounded-full bg-indigo-500 mt-1 shrink-0"></span>
              <span>{{ item.wave_note }}</span>
            </div>
            <div v-if="item.funding_note" class="flex items-start space-x-1.5 text-amber-700 dark:text-amber-300 font-medium">
              <span class="w-1.5 h-1.5 rounded-full bg-amber-500 mt-1 shrink-0"></span>
              <span>{{ item.funding_note }}</span>
            </div>
          </div>

          <!-- Automated TP/SL & Risk Levels -->
          <div v-if="item.take_profit_price && item.stop_loss_price" class="p-2.5 rounded-xl bg-sky-500/10 border border-sky-500/20 text-[11px] space-y-1">
            <div class="flex items-center justify-between text-text-subtle font-bold text-[10px] uppercase">
              <span>Batas Pengaman Otomatis</span>
              <span class="text-sky-600 dark:text-sky-400 font-mono">R:R 1:{{ (item.playbook && item.playbook.recommended_rr) ? item.playbook.recommended_rr.toFixed(1) : '2.0' }} (ATR Dynamic)</span>
            </div>
            <div class="flex items-center justify-between font-mono font-bold text-[11px]">
              <span class="text-emerald-600 dark:text-emerald-400">TP: ${{ item.take_profit_price }} (+{{ item.tp_percent }}%)</span>
              <span class="text-rose-600 dark:text-rose-400">SL: ${{ item.stop_loss_price }} (-{{ item.sl_percent }}%)</span>
            </div>
          </div>

          <!-- Capital Note -->
          <div class="flex items-center space-x-1.5 text-[10px] text-text-subtle font-medium">
            <svg class="w-3.5 h-3.5 text-sky-600 dark:text-sky-400 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="12" cy="12" r="10"></circle>
              <line x1="12" y1="16" x2="12" y2="12"></line>
              <line x1="12" y1="8" x2="12.01" y2="8"></line>
            </svg>
            <span>{{ item.capital_note }}</span>
          </div>

          <!-- Execution Status -->
          <div v-if="item.executed" class="p-2 rounded-xl bg-emerald-500/15 border border-emerald-500/30 text-emerald-800 dark:text-emerald-300 text-[11px] font-bold">
            Order Jual Berhasil Dikirim ke BingX (Order ID: {{ item.order_id }})
          </div>
          <div v-else-if="item.dry_run && item.decision === 'ENTER_SHORT'" class="p-2 rounded-xl bg-sky-500/15 border border-sky-500/30 text-sky-800 dark:text-sky-300 text-[11px] font-bold">
            Simulasi Selesai: Sinyal siap eksekusi lot {{ item.quantity }} koin.
          </div>
        </div>

        <!-- Technical Detail View (For Expert Analysts) -->
        <div v-else class="space-y-2 mt-2 pt-2 border-t border-border/60 text-[11px] font-mono">
          <div v-if="item.playbook && item.playbook.playbook && item.playbook.playbook !== 'NONE'" class="text-primary font-bold">
            <span class="text-text-subtle font-sans font-semibold">Playbook:</span> {{ item.playbook.playbook }} (Score: {{ item.playbook.score }}/100, R:R {{ item.playbook.recommended_rr }})
          </div>
          <div class="text-text-main">
            <span class="text-text-subtle font-sans font-semibold">Evidence:</span> {{ item.raw_evidence || '-' }}
          </div>
          <div v-if="item.raw_risk" class="text-text-muted">
            <span class="text-text-subtle font-sans font-semibold">Risk Factors:</span> {{ item.raw_risk }}
          </div>
          <div v-if="item.fibonacci_note" class="text-sky-700 dark:text-sky-300">
            <span class="text-text-subtle font-sans font-semibold">Fibonacci:</span> {{ item.fibonacci_note }}
          </div>
          <div v-if="item.wave_note" class="text-indigo-700 dark:text-indigo-300">
            <span class="text-text-subtle font-sans font-semibold">Wave / Exhaustion:</span> {{ item.wave_note }}
          </div>
          <div class="text-text-subtle flex items-center space-x-3 pt-1 border-t border-border/40 font-semibold">
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
  if (color === 'emerald') return 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border-emerald-500/30'
  if (color === 'amber') return 'bg-amber-500/15 text-amber-700 dark:text-amber-300 border-amber-500/30'
  return 'bg-slate-200 dark:bg-slate-800 text-slate-700 dark:text-slate-300 border-border'
}

function fibBadgeClass(zone) {
  if (zone === 'PEAK_EXHAUSTION' || zone === 'BLOW_OFF_EXTENSION') {
    return 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border-emerald-500/30'
  }
  if (zone === 'SHALLOW_PULLBACK') {
    return 'bg-sky-500/15 text-sky-700 dark:text-sky-300 border-sky-500/30'
  }
  if (zone === 'EXTENDED_DUMP') {
    return 'bg-rose-500/15 text-rose-700 dark:text-rose-300 border-rose-500/30'
  }
  return 'bg-slate-200 dark:bg-slate-800 text-slate-700 dark:text-slate-300 border-border'
}

function formatFibZone(zone, retracement) {
  const pct = (retracement !== null && retracement !== undefined) ? Math.round(Number(retracement) * 100) : 0
  if (zone === 'PEAK_EXHAUSTION') return `Puncak Jenuh (${pct}%)`
  if (zone === 'BLOW_OFF_EXTENSION') return 'Blow-Off Top'
  if (zone === 'SHALLOW_PULLBACK') return `Koreksi Awal (${pct}%)`
  if (zone === 'EXTENDED_DUMP') return `Sudah Turun (${pct}%)`
  return `${zone || 'Normal'} (${pct}%)`
}

function rsiBadgeClass(rsi) {
  if (rsi.divergence === 'BEARISH_DIV') return 'bg-rose-500/15 text-rose-700 dark:text-rose-300 border-rose-500/30'
  if (rsi.divergence === 'BULLISH_DIV') return 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border-emerald-500/30'
  if (rsi.is_overbought) return 'bg-amber-500/15 text-amber-700 dark:text-amber-300 border-amber-500/30'
  if (rsi.is_oversold) return 'bg-sky-500/15 text-sky-700 dark:text-sky-300 border-sky-500/30'
  return 'bg-slate-200 dark:bg-slate-800 text-slate-700 dark:text-slate-300 border-border'
}
</script>
