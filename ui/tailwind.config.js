/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#0f172a",
        sand: "#f6efe5",
        ember: "#b45309",
        pine: "#14532d",
        slateglass: "rgba(15, 23, 42, 0.72)"
      },
      boxShadow: {
        panel: "0 24px 70px rgba(15, 23, 42, 0.12)"
      },
      fontFamily: {
        sans: ["'Manrope'", "ui-sans-serif", "system-ui"],
        display: ["'Space Grotesk'", "ui-sans-serif", "system-ui"]
      }
    }
  },
  plugins: []
};

