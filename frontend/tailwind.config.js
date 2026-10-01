/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        mc: {
          bg: "#0f0f11",
          card: "#18181b",
          card2: "#1a1a1e",
          border: "#27272a",
          text: "#e4e4e7",
          muted: "#a1a1aa",
          faint: "#71717a",
          sidebar: "#0c0c0e",
        },
        sky: {
          400: "#38bdf8",
          300: "#7dd3fc",
          500: "#0ea5e9",
        },
        violet: {
          400: "#a78bfa",
        },
      },
      fontFamily: {
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
      },
      boxShadow: {
        card: "0 1px 2px rgba(0,0,0,0.35), 0 8px 24px -12px rgba(0,0,0,0.55)",
        glow: "0 0 0 1px rgba(56,189,248,0.25), 0 0 18px -4px rgba(56,189,248,0.45)",
        glowViolet: "0 0 0 1px rgba(167,139,250,0.25), 0 0 18px -4px rgba(167,139,250,0.45)",
        lift: "0 10px 30px -10px rgba(0,0,0,0.6)",
      },
      borderRadius: {
        xl2: "16px",
      },
    },
  },
  plugins: [],
};