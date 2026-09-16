import type { Config } from "tailwindcss";
import typography from "@tailwindcss/typography";

const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["var(--font-sans)", "ui-sans-serif", "system-ui", "sans-serif"],
      },
      maxWidth: {
        chat: "48rem",
      },
      boxShadow: {
        capsule: "0 1px 3px rgba(0,0,0,.08), 0 8px 24px rgba(60,64,67,.12)",
      },
    },
  },
  plugins: [typography],
};

export default config;
