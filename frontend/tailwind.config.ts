import type { Config } from "tailwindcss";

export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        border: "#d6cfc0",
        ring: "#7a8a72",
        background: "#f8f4ec",
        foreground: "#2a2b22",
        muted: {
          DEFAULT: "#e4ddcf",
          foreground: "#6b6a5c",
        },
        primary: {
          DEFAULT: "#8fa286",
          foreground: "#1f231b",
        },
        accent: {
          DEFAULT: "#c3c6af",
          foreground: "#2a2b22",
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
        soft: "0 1px 2px 0 hsl(80 15% 14% / 0.04), 0 1px 3px 0 hsl(80 15% 14% / 0.06)",
        raised: "0 4px 16px -4px hsl(80 20% 16% / 0.12), 0 2px 6px -2px hsl(80 20% 16% / 0.08)",
        glow: "0 0 0 1px hsl(101 13% 45% / 0.1), 0 8px 24px -8px hsl(101 13% 45% / 0.4)",
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
