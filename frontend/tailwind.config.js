/** Tailwind maps every color to a CSS variable defined in src/styles/tokens.css.
 *  Change the design tokens there, not here. */
/** @type {import('tailwindcss').Config} */
const token = (name) => `rgb(var(--bp-${name}) / <alpha-value>)`;

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        canvas: token("canvas"),
        surface: token("surface"),
        subtle: token("subtle"),
        border: token("border"),
        ink: { DEFAULT: token("ink"), muted: token("ink-muted"), faint: token("ink-faint") },
        brand: { DEFAULT: token("brand"), strong: token("brand-strong"), soft: token("brand-soft") },
        ok: { DEFAULT: token("ok"), soft: token("ok-soft") },
        warn: { DEFAULT: token("warn"), soft: token("warn-soft") },
        crit: { DEFAULT: token("crit"), soft: token("crit-soft") },
        ai: { DEFAULT: token("ai"), soft: token("ai-soft") },
      },
      fontFamily: {
        sans: ["Pretendard", "Inter", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "monospace"],
      },
      borderRadius: { card: "var(--bp-radius-card)" },
      width: { partner: "var(--bp-partner-width)" },
    },
  },
  plugins: [],
};
