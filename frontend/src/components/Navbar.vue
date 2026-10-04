<template>
  <header class="sticky top-0 z-30 bg-surface/90 backdrop-blur-md border-b border-border px-4 py-3 shadow-sm transition-colors duration-200">
    <div class="max-w-md mx-auto flex items-center justify-between">
      <!-- Brand & Status -->
      <div class="flex items-center space-x-2.5">
        <div
          :class="user?.role === 'admin' ? 'bg-amber-500/15 border-amber-500/30 text-amber-500 dark:text-amber-400' : 'bg-sky-500/15 border-sky-500/30 text-sky-600 dark:text-sky-400'"
          class="w-8 h-8 rounded-xl border flex items-center justify-center shadow-sm"
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
            <h1 class="font-extrabold text-text-main text-base leading-tight tracking-tight">BingX Portal</h1>
            <span
              v-if="user?.role === 'admin'"
              class="bg-amber-500/15 text-amber-700 dark:text-amber-300 border-amber-500/30 text-[10px] font-bold px-1.5 py-0.5 rounded-full border uppercase tracking-wider"
            >
              Admin
            </span>
            <span
              v-else
              :class="isDemo ? 'bg-sky-500/15 text-sky-700 dark:text-sky-300 border-sky-500/30' : 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border-emerald-500/30'"
              class="text-[10px] font-bold px-1.5 py-0.5 rounded-full border uppercase tracking-wider"
            >
              {{ isDemo ? 'Demo VST' : 'Live' }}
            </span>
          </div>
          <p class="text-[11px] text-text-subtle font-medium">
            {{ user?.role === 'admin' ? 'Manajemen Pengguna & Konfigurasi AI' : 'Short-Only Memecoin System' }}
          </p>
        </div>
      </div>

      <!-- Action Controls -->
      <div class="flex items-center space-x-1.5">
        <!-- Trader only: On-Demand Dynamic Sync Button -->
        <button
          v-if="user?.role !== 'admin'"
          @click="$emit('sync-now')"
          :disabled="isSyncing"
          class="p-2 rounded-xl border border-border clay-btn clay-btn-slate text-text-muted transition flex items-center justify-center"
          title="Sinkronkan Data dengan BingX Sekarang"
        >
          <svg :class="{'animate-spin text-sky-600 dark:text-sky-400': isSyncing}" class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="23 4 23 10 17 10"></polyline>
            <polyline points="1 20 1 14 7 14"></polyline>
            <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path>
          </svg>
        </button>

        <!-- Dark / Light Theme Toggle -->
        <button
          @click="$emit('toggle-theme')"
          class="p-2 rounded-xl border border-border clay-btn clay-btn-slate transition"
          :title="isDark ? 'Ganti ke Mode Terang (Light)' : 'Ganti ke Mode Gelap (Dark)'"
        >
          <!-- Sun Icon (shown in dark mode to switch to light) -->
          <svg v-if="isDark" class="w-4 h-4 text-amber-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="5"></circle>
            <line x1="12" y1="1" x2="12" y2="3"></line>
            <line x1="12" y1="21" x2="12" y2="23"></line>
            <line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line>
            <line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line>
            <line x1="1" y1="12" x2="3" y2="12"></line>
            <line x1="21" y1="12" x2="23" y2="12"></line>
            <line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line>
            <line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line>
          </svg>
          <!-- Moon Icon (shown in light mode to switch to dark) -->
          <svg v-else class="w-4 h-4 text-slate-700" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path>
          </svg>
        </button>

        <!-- Trader only: Simple / Detail Mode Toggle -->
        <button
          v-if="user?.role !== 'admin'"
          @click="$emit('toggle-simple')"
          class="px-2.5 py-1.5 rounded-xl border text-xs font-semibold flex items-center space-x-1 transition clay-btn"
          :class="simpleMode ? 'bg-amber-500/15 border-amber-500/30 text-amber-700 dark:text-amber-300' : 'clay-btn-slate border-border text-text-muted'"
          title="Ganti Mode Tampilan"
        >
          <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10"></circle>
            <path d="M12 16v-4"></path>
            <path d="M12 8h.01"></path>
          </svg>
          <span class="text-[11px] font-bold">{{ simpleMode ? 'Sederhana' : 'Detail' }}</span>
        </button>

        <!-- Trader only: API Settings -->
        <button
          v-if="user?.role !== 'admin'"
          @click="$emit('open-settings')"
          class="p-2 rounded-xl clay-btn clay-btn-slate border border-border text-text-muted transition"
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
          class="p-2 rounded-xl clay-btn clay-btn-rose border border-rose-500/30 text-white transition"
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
  isDark: Boolean,
  simpleMode: Boolean,
  isSyncing: Boolean
})
defineEmits(['toggle-theme', 'toggle-simple', 'open-settings', 'logout', 'sync-now'])
</script>