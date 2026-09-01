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
        background: "rgb(var(--background) / <alpha-value>)",
        surface: "rgb(var(--surface) / <alpha-value>)",
        "surface-raised": "rgb(var(--surface-raised) / <alpha-value>)",
        foreground: "rgb(var(--foreground) / <alpha-value>)",
        muted: "rgb(var(--muted) / <alpha-value>)",
        "border-strong": "rgb(var(--border-strong) / <alpha-value>)",
        brand: {
          100: "#EEF0FB",
          300: "#8B96E3",
          400: "#707CD6",
          500: "#5E6AD2",
          600: "#4D59C1",
          700: "#3D48A5",
        },
        // Functional data colors (used for map layers and category cues)
        power: "#D99E41",
        water: "#4DB6AC",
        success: "#57AB5A",
        warning: "#D99E41",
        danger: "#E5534B",
      },
      fontFamily: {
        sans: [
          "var(--font-inter)",
          "-apple-system",
          "BlinkMacSystemFont",
          "Segoe UI",
          "Roboto",
          "Helvetica Neue",
          "sans-serif",
        ],
        mono: [
          "var(--font-mono)",
          "ui-monospace",
          "SFMono-Regular",
          "Menlo",
          "Monaco",
          "Consolas",
          "monospace",
        ],
      },
      boxShadow: {
        raised: "0 1px 2px rgb(0 0 0 / 0.04), 0 4px 12px rgb(0 0 0 / 0.06)",
        overlay: "0 24px 64px -16px rgb(0 0 0 / 0.35), 0 4px 16px rgb(0 0 0 / 0.2)",
      },
    },
  },
  plugins: [require("tailwind-scrollbar-hide")],
};

export default config;
