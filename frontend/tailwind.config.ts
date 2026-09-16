import type { Config } from "tailwindcss";

export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        border: "#d7e0ea",
        ring: "#2f5a94",
        background: "var(--background)",
        foreground: "#111c2e",
        muted: {
          DEFAULT: "rgb(var(--muted) / <alpha-value>)",
          foreground: "#5b6b80",
        },
        primary: {
          DEFAULT: "#123B6D",
          foreground: "#ffffff",
        },
        accent: {
          DEFAULT: "#F5A900",
          foreground: "#071F43",
        },
        success: {
          DEFAULT: "hsl(152 69% 31%)",
          foreground: "hsl(0 0% 100%)",
          soft: "hsl(152 60% 95%)",
        },
        warning: {
          DEFAULT: "hsl(38 92% 42%)",
          foreground: "hsl(0 0% 100%)",
          soft: "hsl(43 96% 94%)",
        },
        destructive: {
          DEFAULT: "hsl(0 72% 51%)",
          foreground: "hsl(0 0% 100%)",
          soft: "hsl(0 86% 96%)",
        },
      },
      borderRadius: {
        md: "0.375rem",
        lg: "0.625rem",
        xl: "0.9rem",
      },
      boxShadow: {
        soft: "0 1px 2px 0 hsl(215 30% 14% / 0.04), 0 1px 3px 0 hsl(215 30% 14% / 0.06)",
        raised: "0 4px 16px -4px hsl(215 35% 16% / 0.12), 0 2px 6px -2px hsl(215 35% 16% / 0.08)",
        glow: "0 0 0 1px hsl(38 96% 48% / 0.15), 0 8px 24px -8px hsl(38 96% 48% / 0.45)",
      },
      fontFamily: {
        sans: [
          "Inter var",
          "Inter",
          "-apple-system",
          "BlinkMacSystemFont",
          "Segoe UI",
          "sans-serif",
        ],
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
} satisfies Config;
