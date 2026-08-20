/** @type {import('tailwindcss').Config} */
import typography from '@tailwindcss/typography'
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        // MobileWork Design System tokens
        page: '#f0f2f5',
        ink: '#121314',
        accent: '#1890ff',
        surface: '#ffffff',
        muted: '#7c8085',
        hairline: '#e5e6eb',
        danger: '#c0392b',
        warn: '#8a6d1a',
      },
      fontFamily: {
        sans: ["'IBM Plex Sans'", "'PingFang SC'", "'Microsoft YaHei'", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["ui-monospace", "'SFMono-Regular'", "Menlo", "Monaco", "Consolas", "monospace"],
      },
      borderRadius: { default: '8px' },
    },
  },
  plugins: [typography],
}
