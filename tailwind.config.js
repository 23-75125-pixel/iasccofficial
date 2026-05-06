/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./templates/**/*.html",
    "./static/js/**/*.js"
  ],
  theme: {
    extend: {
      colors: {
        brand: {
          50: "#fff1f1",
          600: "#c10a0a",
          700: "#9f0808"
        }
      }
    }
  },
  plugins: []
};
