<template>
  <div class="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-end sm:items-center justify-center p-0 sm:p-4">
    <div class="w-full max-w-md bg-surface border-t sm:border border-border rounded-t-2xl sm:rounded-2xl p-5 shadow-2xl max-h-[90vh] overflow-y-auto">
      <!-- Header -->
      <div class="flex items-center justify-between pb-3 border-b border-border mb-4">
        <div class="flex items-center space-x-2">
          <div class="w-7 h-7 rounded-lg bg-amber-500/10 border border-amber-500/20 flex items-center justify-center text-amber-400">
            <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path>
              <circle cx="9" cy="7" r="4"></circle>
              <path d="M23 21v-2a4 4 0 0 0-3-3.87"></path>
              <path d="M16 3.13a4 4 0 0 1 0 7.75"></path>
            </svg>
          </div>
          <h3 class="text-sm font-bold text-slate-100">Manajemen Klien & Akses (Admin)</h3>
        </div>
        <button @click="$emit('close')" class="p-1 rounded-lg text-slate-400 hover:text-slate-200">
          <svg class="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="18" y1="6" x2="6" y2="18"></line>
            <line x1="6" y1="6" x2="18" y2="18"></line>
          </svg>
        </button>
      </div>

      <!-- Add New Client User Form -->
      <div class="bg-slate-900/90 border border-border p-3.5 rounded-xl mb-4">
        <div class="flex items-center justify-between mb-2">
          <span class="text-xs font-bold text-slate-200 uppercase tracking-wide">Buat Akun Klien Baru</span>
          <span class="text-[10px] text-amber-400 font-semibold">Khusus Klien Berbayar</span>
        </div>

        <form @submit.prevent="handleCreateUser" class="space-y-2.5">
          <div>
            <label class="block text-[10px] font-semibold text-slate-400 mb-0.5">Nama Lengkap Klien</label>
            <input
              v-model="newUser.full_name"
              type="text"
              placeholder="Contoh: Pak Haji Bambang"
              class="w-full h-9 px-3 rounded-lg bg-slate-950 border border-border text-xs text-slate-100 placeholder-slate-500 focus:outline-none focus:border-sky-500"
            />
          </div>

          <div class="grid grid-cols-2 gap-2">
            <div>
              <label class="block text-[10px] font-semibold text-slate-400 mb-0.5">Username Login</label>
              <input
                v-model="newUser.username"
                type="text"
                required
                placeholder="bambang_trader"
                class="w-full h-9 px-3 rounded-lg bg-slate-950 border border-border text-xs text-slate-100 placeholder-slate-500 focus:outline-none focus:border-sky-500"
              />
            </div>
            <div>
              <label class="block text-[10px] font-semibold text-slate-400 mb-0.5">Password Awal</label>
              <input
                v-model="newUser.password"
                type="password"
                required
                placeholder="Min 6 karakter"
                class="w-full h-9 px-3 rounded-lg bg-slate-950 border border-border text-xs text-slate-100 placeholder-slate-500 focus:outline-none focus:border-sky-500"
              />
            </div>
          </div>

          <div class="flex items-center space-x-3 pt-1">
            <label class="flex items-center space-x-2 text-xs text-slate-300 cursor-pointer">
              <input type="checkbox" v-model="newUser.is_demo" class="rounded border-border bg-slate-950 text-sky-600 focus:ring-0" />
              <span class="text-[11px]">Mulai di Akun Demo VST (Rekomendasi)</span>
            </label>
          </div>

          <div v-if="actionMsg" :class="actionSuccess ? 'text-emerald-300 bg-emerald-500/10 border-emerald-500/30' : 'text-rose-300 bg-rose-500/10 border-rose-500/30'" class="p-2 rounded-lg border text-[11px]">
            {{ actionMsg }}
          </div>

          <button
            type="submit"
            :disabled="creating"
            class="w-full h-10 bg-amber-600 hover:bg-amber-500 text-slate-950 font-bold rounded-lg text-xs transition flex items-center justify-center space-x-1.5 shadow"
          >
            <span>{{ creating ? 'Mendaftarkan Akun...' : 'Buat & Aktifkan Akun Klien' }}</span>
          </button>
        </form>
      </div>

      <!-- Registered Users List -->
      <div class="space-y-2">
        <div class="text-xs font-bold text-slate-400 uppercase tracking-wide px-1">
          Daftar Pengguna Terdaftar ({{ users.length }})
        </div>

        <div
          v-for="u in users"
          :key="u.id"
          class="p-3 rounded-xl bg-slate-900 border border-border flex items-center justify-between"
        >
          <div>
            <div class="flex items-center space-x-2">
              <span class="text-xs font-bold text-slate-100">{{ u.full_name || u.username }}</span>
              <span v-if="u.role === 'admin'" class="text-[9px] font-bold px-1.5 py-0.2 rounded bg-amber-500/20 text-amber-400 border border-amber-500/30 uppercase">
                Admin
              </span>
            </div>
            <div class="text-[10px] text-slate-400 font-mono mt-0.5">
              @{{ u.username }} · {{ u.is_demo ? 'Demo VST' : 'Live' }}
            </div>
          </div>

          <div class="flex items-center space-x-2">
            <span
              :class="u.has_api_key ? 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30' : 'bg-slate-800 text-slate-400 border-border'"
              class="text-[10px] font-semibold px-2 py-0.5 rounded-full border inline-block"
            >
              {{ u.has_api_key ? 'API Terhubung' : 'Belum Ada API' }}
            </span>

            <!-- Delete button for non-admin -->
            <button
              v-if="u.role !== 'admin'"
              @click="handleDeleteUser(u.id, u.username)"
              class="p-1 rounded hover:bg-rose-500/20 text-rose-400 transition"
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
import { ref, reactive } from 'vue'

const props = defineProps({
  users: {
    type: Array,
    default: () => []
  },
  token: String
})

const emit = defineEmits(['close', 'refresh-users'])

const creating = ref(false)
const actionMsg = ref('')
const actionSuccess = ref(false)

const newUser = reactive({
  full_name: '',
  username: '',
  password: '',
  is_demo: true
})

async function handleCreateUser() {
  actionMsg.value = ''
  creating.value = true
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
    if (!res.ok) throw new Error(data.detail || 'Gagal membuat akun klien.')
    
    actionSuccess.value = true
    actionMsg.value = data.message || 'Akun berhasil dibuat!'
    newUser.full_name = ''
    newUser.username = ''
    newUser.password = ''
    emit('refresh-users')
  } catch (err) {
    actionSuccess.value = false
    actionMsg.value = err.message
  } finally {
    creating.value = false
  }
}

async function handleDeleteUser(userId, username) {
  if (!confirm(`Hapus akun klien @${username}? Tindakan ini tidak dapat dibatalkan.`)) return
  try {
    const res = await fetch(`/api/admin/users/${userId}`, {
      method: 'DELETE',
      headers: {
        'Authorization': `Bearer ${props.token}`
      }
    })
    const data = await res.json()
    if (!res.ok) throw new Error(data.detail || 'Gagal menghapus pengguna.')
    emit('refresh-users')
  } catch (err) {
    alert(err.message)
  }
}
</script>
