/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        brand: {
          50: '#e6e8f0',
          100: '#cdd1e1',
          200: '#9ba3c4',
          300: '#6875a6',
          400: '#364789',
          500: '#04196b', // Base Brand Color (Approximated from Logo)
          600: '#031456',
          700: '#020f40',
          800: '#020a2b',
          900: '#010515',
        }
      }
    },
  },
  plugins: [],
}
