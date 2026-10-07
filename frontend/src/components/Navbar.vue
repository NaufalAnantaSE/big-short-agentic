<template>
  <header class="sticky top-0 z-30 bg-surface border-b border-border px-4 py-2.5">
    <div class="max-w-md mx-auto flex items-center justify-between gap-2">
      <!-- Brand & Status -->
      <div class="flex items-center space-x-2.5 min-w-0">
        <div
          :class="user?.role === 'admin' ? 'bg-amber-500/15 border-amber-500/30 text-amber-500 dark:text-amber-400' : 'bg-sky-500/15 border-sky-500/30 text-sky-600 dark:text-sky-400'"
          class="w-9 h-9 rounded-xl border flex items-center justify-center shrink-0"
        >
          <svg v-if="user?.role === 'admin'" class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
            <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"></path>
          </svg>
          <svg v-else class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="22 7 13.5 15.5 8.5 10.5 2 17"></polyline>
            <polyline points="16 7 22 7 22 13"></polyline>
          </svg>
        </div>
        <div class="min-w-0">
          <div class="flex items-center space-x-1.5">
            <h1 class="font-extrabold text-text-main text-base leading-tight tracking-tight truncate">BingX Agent</h1>
            <span
              v-if="user?.role === 'admin'"
              class="bg-amber-500/15 text-amber-700 dark:text-amber-300 border-amber-500/30 text-[10px] font-bold px-1.5 py-0.5 rounded-full border uppercase tracking-wider shrink-0"
            >
              Admin
            </span>
            <span
              v-else
              :class="isDemo ? 'bg-sky-500/15 text-sky-700 dark:text-sky-300 border-sky-500/30' : 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border-emerald-500/30'"
              class="text-[10px] font-bold px-1.5 py-0.5 rounded-full border uppercase tracking-wider shrink-0"
            >
              {{ isDemo ? 'Demo' : 'Live' }}
            </span>
          </div>
          <p class="text-xs text-text-muted font-medium truncate">
            {{ user?.role === 'admin' ? 'Kelola pengguna & AI' : 'Trading otomatis' }}
          </p>
        </div>
      </div>

      <!-- Action Controls: icon + text label (senior-friendly).
           Sync lives in AccountSummaryCard ("Sync Akun") to avoid duplicate controls. -->
      <div class="flex items-center gap-1 shrink-0">
        <!-- Dark / Light Theme Toggle (compact: sun/moon is universally recognized) -->
        <button
          @click="$emit('toggle-theme')"
          class="clay-btn clay-btn-slate !rounded-xl w-11 !min-h-[44px] !px-0"
          :title="isDark ? 'Ganti ke Mode Terang' : 'Ganti ke Mode Gelap'"
          :aria-label="isDark ? 'Ganti ke Mode Terang' : 'Ganti ke Mode Gelap'"
        >
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
          <svg v-else class="w-4 h-4 text-slate-700 dark:text-slate-300" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path>
          </svg>
        </button>

        <!-- Trader only: Simple / Detail Mode Toggle -->
        <button
          v-if="user?.role !== 'admin'"
          @click="$emit('toggle-simple')"
          class="clay-btn flex-col !rounded-xl px-2 py-1 !min-h-[44px] border"
          :class="simpleMode ? 'bg-amber-500/15 border-amber-500/40 text-amber-700 dark:text-amber-300' : 'clay-btn-slate text-text-muted'"
          title="Ganti Mode Tampilan"
        >
          <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10"></circle>
            <path d="M12 16v-4"></path>
            <path d="M12 8h.01"></path>
          </svg>
          <span class="text-[9px] font-bold leading-none mt-0.5">{{ simpleMode ? 'Mudah' : 'Detail' }}</span>
        </button>

        <!-- Trader only: API Settings -->
        <button
          v-if="user?.role !== 'admin'"
          @click="$emit('open-settings')"
          class="clay-btn clay-btn-slate flex-col !rounded-xl px-2 py-1 !min-h-[44px] text-text-muted"
          title="Pengaturan Kunci API"
        >
          <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="3"></circle>
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path>
          </svg>
          <span class="text-[9px] font-bold leading-none mt-0.5">Kunci API</span>
        </button>

        <!-- Logout for all roles -->
        <button
          @click="$emit('logout')"
          class="clay-btn clay-btn-rose flex-col !rounded-xl px-2 py-1 !min-h-[44px]"
          title="Keluar"
        >
          <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path>
            <polyline points="16 17 21 12 16 7"></polyline>
            <line x1="21" y1="12" x2="9" y2="12"></line>
          </svg>
          <span class="text-[9px] font-bold leading-none mt-0.5">Keluar</span>
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