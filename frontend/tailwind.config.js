/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: [
    "./index.html",
    "./src/**/*.{vue,js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        background: 'var(--color-bg)',
        surface: 'var(--color-surface)',
        'surface-card': 'var(--color-surface-card)',
        'surface-inset': 'var(--color-surface-inset)',
        border: 'var(--color-border)',
        'text-main': 'var(--color-text-main)',
        'text-muted': 'var(--color-text-muted)',
        'text-subtle': 'var(--color-text-subtle)',
        primary: '#0284c7',
        accent: '#10b981',
        warning: '#f59e0b',
        danger: '#ef4444',
      },
      fontFamily: {
        // System font stack only: no webfont downloads, faster on low-end phones
        sans: ['-apple-system', 'BlinkMacSystemFont', '"Segoe UI"', 'Roboto', 'Helvetica', 'Arial', 'sans-serif'],
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'Consolas', 'monospace'],
      },
      boxShadow: {
        'clay-card-light': '8px 12px 24px -4px rgba(15, 23, 42, 0.08), inset 2px 2px 4px rgba(255, 255, 255, 0.9), inset -2px -2px 4px rgba(148, 163, 184, 0.25)',
        'clay-card-dark': '8px 12px 28px -4px rgba(0, 0, 0, 0.6), inset 2px 2px 4px rgba(255, 255, 255, 0.08), inset -2px -2px 4px rgba(0, 0, 0, 0.55)',
        'clay-inset-light': 'inset 3px 3px 6px rgba(148, 163, 184, 0.25), inset -2px -2px 5px rgba(255, 255, 255, 0.9)',
        'clay-inset-dark': 'inset 3px 3px 7px rgba(0, 0, 0, 0.65), inset -2px -2px 5px rgba(255, 255, 255, 0.04)',
        'clay-btn-light': '4px 6px 14px -2px rgba(15, 23, 42, 0.12), inset 1px 1px 2px rgba(255, 255, 255, 0.4), inset -2px -2px 4px rgba(0, 0, 0, 0.15)',
        'clay-btn-dark': '4px 6px 16px -2px rgba(0, 0, 0, 0.5), inset 1px 1px 2px rgba(255, 255, 255, 0.15), inset -2px -2px 4px rgba(0, 0, 0, 0.4)',
      }
    },
  },
  plugins: [],
}
