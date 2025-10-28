import typography from '@tailwindcss/typography'

/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        primary: {
          DEFAULT: '#3B82F6',
        },
        bg: 'var(--bg)',
        panel: 'var(--panel)',
        muted: 'var(--muted)',
        accent: 'var(--accent)'
      },
      boxShadow: {
        card: '0 2px 16px rgba(0,0,0,0.25)'
      },
      borderRadius: {
        xl: '14px',
        '2xl': '16px'
      },
      fontSize: {
        'label': ['0.75rem', { lineHeight: '1.25rem', letterSpacing: '0.06em', textTransform: 'uppercase' }]
      }
    },
  },
  plugins: [typography],
}
