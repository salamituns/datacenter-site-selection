import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        // Day: warm survey paper. Night: engineering blueprint.
        background: "rgb(var(--background) / <alpha-value>)",
        surface: "rgb(var(--surface) / <alpha-value>)",
        "surface-raised": "rgb(var(--surface-raised) / <alpha-value>)",
        foreground: "rgb(var(--foreground) / <alpha-value>)",
        muted: "rgb(var(--muted) / <alpha-value>)",
        "border-strong": "rgb(var(--border-strong) / <alpha-value>)",
        // Signal orange — survey marker ink
        accent: {
          100: "#FBE6D6",
          200: "#F5C4A3",
          300: "#F9A870",
          400: "#F5854A",
          500: "#EE6D2D",
          600: "#E8590C",
          700: "#C24A08",
          800: "#9C3B06",
        },
        // Functional data colors (map layers, category cues)
        power: "#B07D0F",
        water: "#1F7A74",
        success: "#3E7C4F",
        warning: "#B07D0F",
        danger: "#B8442C",
        // Dark-mode variants
        "power-night": "#E2B056",
        "water-night": "#46C0B4",
        "success-night": "#72C684",
        "danger-night": "#E4685A",
      },
      fontFamily: {
        display: ["var(--font-display)", "Georgia", "serif"],
        sans: [
          "var(--font-sans)",
          "-apple-system",
          "BlinkMacSystemFont",
          "Segoe UI",
          "sans-serif",
        ],
        mono: ["var(--font-mono)", "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      boxShadow: {
        plate: "0 1px 0 rgb(0 0 0 / 0.04)",
        overlay: "0 24px 64px -16px rgb(0 0 0 / 0.4), 0 4px 16px rgb(0 0 0 / 0.2)",
      },
      borderRadius: {
        DEFAULT: "2px",
      },
    },
  },
  plugins: [require("tailwind-scrollbar-hide")],
};

export default config;
