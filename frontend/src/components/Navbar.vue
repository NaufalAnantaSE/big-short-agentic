<template>
  <header class="sticky top-0 z-30 bg-surface/95 backdrop-blur border-b border-border px-4 py-3">
    <div class="max-w-md mx-auto flex items-center justify-between">
      <div class="flex items-center space-x-2.5">
        <div
          :class="user?.role === 'admin' ? 'bg-amber-500/10 border-amber-500/30 text-amber-400' : 'bg-sky-500/10 border-sky-500/20 text-sky-400'"
          class="w-8 h-8 rounded-lg border flex items-center justify-center"
        >
          <svg v-if="user?.role === 'admin'" class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
            <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"></path>
          </svg>
          <svg v-else class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="22 7 13.5 15.5 8.5 10.5 2 17"></polyline>
            <polyline points="16 7 22 7 22 13"></polyline>
          </svg>
        </div>
        <div>
          <div class="flex items-center space-x-1.5">
            <h1 class="font-bold text-slate-100 text-base leading-tight">BingX Portal</h1>
            <span
              v-if="user?.role === 'admin'"
              class="bg-amber-500/15 text-amber-300 border-amber-500/30 text-[10px] font-bold px-1.5 py-0.5 rounded border uppercase tracking-wider"
            >
              Admin
            </span>
            <span
              v-else
              :class="isDemo ? 'bg-sky-500/15 text-sky-400 border-sky-500/30' : 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30'"
              class="text-[10px] font-bold px-1.5 py-0.5 rounded border uppercase tracking-wider"
            >
              {{ isDemo ? 'Demo VST' : 'Live' }}
            </span>
          </div>
          <p class="text-[11px] text-slate-400 font-medium">
            {{ user?.role === 'admin' ? 'Manajemen Pengguna & Konfigurasi AI' : 'Short-Only Memecoin System' }}
          </p>
        </div>
      </div>

      <div class="flex items-center space-x-2">
        <!-- Trader only: Mode Toggle -->
        <button
          v-if="user?.role !== 'admin'"
          @click="$emit('toggle-simple')"
          class="px-2.5 py-1.5 rounded-lg border text-xs font-semibold flex items-center space-x-1 transition"
          :class="simpleMode ? 'bg-amber-500/10 border-amber-500/30 text-amber-300' : 'bg-slate-800/80 border-border text-slate-300'"
          title="Ganti Mode Tampilan"
        >
          <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10"></circle>
            <path d="M12 16v-4"></path>
            <path d="M12 8h.01"></path>
          </svg>
          <span class="text-[11px]">{{ simpleMode ? 'Mode Sederhana' : 'Mode Detail' }}</span>
        </button>

        <!-- Trader only: API Settings -->
        <button
          v-if="user?.role !== 'admin'"
          @click="$emit('open-settings')"
          class="p-2 rounded-lg bg-slate-800/80 hover:bg-slate-700/80 border border-border text-slate-300 transition"
          title="Pengaturan Kunci API"
        >
          <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="3"></circle>
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path>
          </svg>
        </button>

        <!-- Logout for all roles -->
        <button
          @click="$emit('logout')"
          class="p-2 rounded-lg bg-rose-500/10 hover:bg-rose-500/20 border border-rose-500/20 text-rose-300 transition"
          title="Keluar"
        >
          <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path>
            <polyline points="16 17 21 12 16 7"></polyline>
            <line x1="21" y1="12" x2="9" y2="12"></line>
          </svg>
        </button>
      </div>
    </div>
  </header>
</template>

<script setup>
defineProps({
  user: Object,
  isDemo: Boolean,
  simpleMode: Boolean
})
defineEmits(['toggle-simple', 'open-settings', 'logout'])
</script>
