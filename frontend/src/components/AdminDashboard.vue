<template>
  <div class="space-y-4">
    <!-- Admin Hero Banner -->
    <div class="clay-card p-4 bg-gradient-to-r from-amber-500/15 via-surface to-surface border border-amber-500/30 shadow-md">
      <div class="flex items-center justify-between mb-2">
        <div class="flex items-center space-x-2">
          <div class="w-8 h-8 rounded-xl bg-amber-500/20 border border-amber-500/30 flex items-center justify-center text-amber-500 dark:text-amber-400 shadow-sm">
            <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
              <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"></path>
            </svg>
          </div>
          <div>
            <h2 class="text-sm font-extrabold text-text-main leading-tight">Panel Administrator</h2>
            <p class="text-[11px] text-amber-600 dark:text-amber-300 font-semibold">Khusus Manajemen Klien & Konfigurasi AI</p>
          </div>
        </div>
        <span class="text-[10px] font-extrabold px-2.5 py-0.5 rounded-full bg-amber-500/20 text-amber-700 dark:text-amber-300 border border-amber-500/30 uppercase tracking-wider">
          Admin Mode
        </span>
      </div>
      <p class="text-xs text-text-muted leading-relaxed mt-2 font-medium">
        Akun ini bertindak sebagai administrator sistem. Untuk menjalankan trading bot otomatis akun pribadi, silakan login menggunakan akun pengguna trader terpisah.
      </p>
    </div>

    <!-- Section 1: AI Model Configuration Card -->
    <div class="clay-card p-4">
      <div class="flex items-center justify-between pb-3 border-b border-border mb-3">
        <div class="flex items-center space-x-2">
          <div class="w-2.5 h-2.5 rounded-full bg-sky-500"></div>
          <span class="text-xs font-bold text-text-muted uppercase tracking-wider">Konfigurasi Kecerdasan Buatan (AI Engine)</span>
        </div>
      </div>

      <form @submit.prevent="saveAiSettings" class="space-y-3">
        <div>
          <label class="block text-[11px] font-bold text-text-muted mb-1">Model AI Analisa Pasar</label>
          <input
            v-model="aiForm.model"
            type="text"
            required
            placeholder="Contoh: testing_v1"
            class="clay-input w-full h-11 px-3.5 text-xs font-mono font-semibold"
          />
          <p class="text-[10px] text-text-subtle font-medium mt-1">
            Rujukan model via 9Router (default: <code class="text-sky-600 dark:text-sky-400 font-bold">testing_v1</code>).
          </p>
        </div>

        <div>
          <label class="block text-[11px] font-bold text-text-muted mb-1">Gateway Endpoint (Server Default)</label>
          <input
            :value="aiForm.gateway_url"
            disabled
            type="text"
            class="clay-input w-full h-10 px-3.5 text-xs opacity-70 font-mono"
          />
        </div>

        <div class="clay-inset p-3 text-[11px] text-text-muted leading-relaxed">
          <strong class="text-text-main font-bold">Aturan Penerapan:</strong> Model yang disimpan akan otomatis diterapkan untuk semua sesi pencarian koin baru yang diinisiasi oleh klien. Sesi aktif yang sedang berjalan tidak akan terinterupsi.
        </div>

        <div v-if="aiMsg" :class="aiSuccess ? 'text-emerald-800 dark:text-emerald-300 bg-emerald-500/15 border-emerald-500/30' : 'text-rose-800 dark:text-rose-300 bg-rose-500/15 border-rose-500/30'" class="p-2.5 rounded-xl border text-xs font-semibold">
          {{ aiMsg }}
        </div>

        <button
          type="submit"
          :disabled="aiLoading"
          class="clay-btn clay-btn-sky w-full h-11 text-xs space-x-1.5"
        >
          <span>{{ aiLoading ? 'Menyimpan...' : 'Simpan Konfigurasi AI' }}</span>
        </button>
      </form>
    </div>

    <!-- Section 2: Manage Client Users Card -->
    <div class="clay-card p-4">
      <div class="flex items-center justify-between pb-3 border-b border-border mb-3">
        <span class="text-xs font-bold text-text-muted uppercase tracking-wider">Manajemen Pengguna ({{ users.length }} Klien)</span>
        <button
          @click="fetchUsers"
          class="text-xs text-sky-600 dark:text-sky-400 hover:underline font-bold"
        >
          Perbarui Daftar
        </button>
      </div>

      <!-- Create New Client Form -->
      <form @submit.prevent="handleCreateUser" class="space-y-2.5 clay-inset p-3.5 mb-4">
        <div class="text-xs font-extrabold text-amber-600 dark:text-amber-400 mb-1">Tambah Akun Klien Baru</div>

        <div>
          <label class="block text-[10px] font-bold text-text-subtle mb-0.5">Nama Lengkap Klien</label>
          <input
            v-model="newUser.full_name"
            type="text"
            placeholder="Contoh: Pak Haji Bambang"
            class="clay-input w-full h-10 px-3 text-xs placeholder:text-text-subtle font-medium"
          />
        </div>

        <div class="grid grid-cols-2 gap-2">
          <div>
            <label class="block text-[10px] font-bold text-text-subtle mb-0.5">Username Login</label>
            <input
              v-model="newUser.username"
              type="text"
              required
              placeholder="bambang_trader"
              class="clay-input w-full h-10 px-3 text-xs placeholder:text-text-subtle font-medium"
            />
          </div>
          <div>
            <label class="block text-[10px] font-bold text-text-subtle mb-0.5">Password Awal</label>
            <input
              v-model="newUser.password"
              type="password"
              required
              placeholder="Min 6 karakter"
              class="clay-input w-full h-10 px-3 text-xs placeholder:text-text-subtle font-medium"
            />
          </div>
        </div>

        <div class="flex items-center space-x-3 pt-1">
          <label class="flex items-center space-x-2 text-xs text-text-muted cursor-pointer font-medium">
            <input type="checkbox" v-model="newUser.is_demo" class="rounded border-border text-sky-600 focus:ring-0" />
            <span class="text-[11px]">Mulai di Akun Demo VST (Rekomendasi)</span>
          </label>
        </div>

        <div v-if="userMsg" :class="userSuccess ? 'text-emerald-800 dark:text-emerald-300 bg-emerald-500/15 border-emerald-500/30' : 'text-rose-800 dark:text-rose-300 bg-rose-500/15 border-rose-500/30'" class="p-2.5 rounded-xl border text-[11px] font-semibold">
          {{ userMsg }}
        </div>

        <button
          type="submit"
          :disabled="userLoading"
          class="clay-btn bg-amber-500 hover:bg-amber-400 text-slate-950 font-extrabold w-full h-11 text-xs shadow-sm space-x-1.5"
        >
          <span>{{ userLoading ? 'Membuat Akun...' : 'Buat & Aktifkan Akun Klien' }}</span>
        </button>
      </form>

      <!-- Users List -->
      <div class="space-y-2">
        <div
          v-for="u in users"
          :key="u.id"
          class="p-3 rounded-2xl clay-inset flex items-center justify-between"
        >
          <div>
            <div class="flex items-center space-x-2">
              <span class="text-xs font-bold text-text-main">{{ u.full_name || u.username }}</span>
              <span v-if="u.role === 'admin'" class="text-[9px] font-extrabold px-1.5 py-0.5 rounded-full bg-amber-500/20 text-amber-700 dark:text-amber-300 border border-amber-500/30 uppercase">
                Admin
              </span>
            </div>
            <div class="text-[10px] text-text-subtle font-mono mt-0.5">
              @{{ u.username }} · {{ u.is_demo ? 'Demo VST' : 'Live' }}
            </div>
          </div>

          <div class="flex items-center space-x-2">
            <span
              :class="u.has_api_key ? 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border-emerald-500/30' : 'bg-slate-200 dark:bg-slate-800 text-slate-700 dark:text-slate-300 border-border'"
              class="text-[10px] font-bold px-2 py-0.5 rounded-full border inline-block"
            >
              {{ u.has_api_key ? 'API Terhubung' : 'Belum Ada API' }}
            </span>

            <button
              v-if="u.role !== 'admin'"
              @click="handleDeleteUser(u.id, u.username)"
              class="p-1.5 rounded-xl hover:bg-rose-500/20 text-rose-500 dark:text-rose-400 transition"
              title="Hapus Klien"
            >
              <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <polyline points="3 6 5 6 21 6"></polyline>
                <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
              </svg>
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'

const props = defineProps({
  token: String
})

// AI Settings State
const aiForm = reactive({
  model: '',
  gateway_url: ''
})
const aiLoading = ref(false)
const aiMsg = ref('')
const aiSuccess = ref(false)

// Users State
const users = ref([])
const userLoading = ref(false)
const userMsg = ref('')
const userSuccess = ref(false)

const newUser = reactive({
  full_name: '',
  username: '',
  password: '',
  is_demo: true
})

async function fetchAiSettings() {
  try {
    const res = await fetch('/api/admin/ai-settings', {
      headers: { 'Authorization': `Bearer ${props.token}` }
    })
    const data = await res.json()
    if (res.ok) {
      aiForm.model = data.model || ''
      aiForm.gateway_url = data.gateway_url || ''
    }
  } catch (err) {
    console.error('Failed to fetch AI settings:', err)
  }
}

async function saveAiSettings() {
  aiLoading.value = true
  aiMsg.value = ''
  try {
    const res = await fetch('/api/admin/ai-settings', {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${props.token}`
      },
      body: JSON.stringify({ model: aiForm.model })
    })
    const data = await res.json()
    if (!res.ok) throw new Error(data.detail || 'Gagal menyimpan pengaturan AI.')
    aiSuccess.value = true
    aiMsg.value = `Model AI berhasil diubah ke: ${data.model}`
  } catch (err) {
    aiSuccess.value = false
    aiMsg.value = err.message
  } finally {
    aiLoading.value = false
  }
}

async function fetchUsers() {
  try {
    const res = await fetch('/api/admin/users', {
      headers: { 'Authorization': `Bearer ${props.token}` }
    })
    const data = await res.json()
    if (res.ok) {
      users.value = data.users || []
    }
  } catch (err) {
    console.error('Failed to fetch users:', err)
  }
}

async function handleCreateUser() {
  userLoading.value = true
  userMsg.value = ''
  try {
    const res = await fetch('/api/admin/users', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${props.token}`
      },
      body: JSON.stringify(newUser)
    })
    const data = await res.json()
    if (!res.ok) throw new Error(data.detail || 'Gagal membuat pengguna.')
    userSuccess.value = true
    userMsg.value = data.message || 'Akun berhasil dibuat!'
    newUser.full_name = ''
    newUser.username = ''
    newUser.password = ''
    fetchUsers()
  } catch (err) {
    userSuccess.value = false
    userMsg.value = err.message
  } finally {
    userLoading.value = false
  }
}

async function handleDeleteUser(userId, username) {
  if (!confirm(`Hapus akun klien @${username}?`)) return
  try {
    const res = await fetch(`/api/admin/users/${userId}`, {
      method: 'DELETE',
      headers: { 'Authorization': `Bearer ${props.token}` }
    })
    const data = await res.json()
    if (!res.ok) throw new Error(data.detail || 'Gagal menghapus pengguna.')
    fetchUsers()
  } catch (err) {
    alert(err.message)
  }
}

onMounted(() => {
  fetchAiSettings()
  fetchUsers()
})
</script>
