import type { Config } from "tailwindcss";

export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        border: "hsl(214 20% 88%)",
        ring: "hsl(217 91% 60%)",
        background: "hsl(0 0% 100%)",
        foreground: "hsl(222 20% 14%)",
        muted: {
          DEFAULT: "hsl(210 20% 96%)",
          foreground: "hsl(215 16% 47%)",
        },
        primary: {
          DEFAULT: "hsl(217 91% 45%)",
          foreground: "hsl(0 0% 100%)",
        },
        accent: {
          DEFAULT: "hsl(258 90% 66%)",
          foreground: "hsl(0 0% 100%)",
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
        soft: "0 1px 2px 0 hsl(222 20% 14% / 0.04), 0 1px 3px 0 hsl(222 20% 14% / 0.06)",
        raised: "0 4px 16px -4px hsl(222 30% 20% / 0.12), 0 2px 6px -2px hsl(222 30% 20% / 0.08)",
        glow: "0 0 0 1px hsl(217 91% 45% / 0.08), 0 8px 24px -8px hsl(217 91% 45% / 0.35)",
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
