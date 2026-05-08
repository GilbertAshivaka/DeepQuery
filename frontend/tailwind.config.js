/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // ── Anthropic-Inspired Warm Brown Palette ──────────
        cream: {
          50:  '#FDFAF6',   // Page background — warm parchment
          100: '#F7F3ED',   // Card backgrounds
          200: '#EDE5D8',   // Borders, sidebar bg
          300: '#DFD3C1',   // Hover backgrounds
          400: '#C9B89E',   // Muted elements
          500: '#B5A088',   // Decorative borders
        },
        sand: {
          300: '#E8D5B7',   // Light accents
          400: '#D4B896',   // Highlights, secondary text
          500: '#C19A6B',   // Active accents
          600: '#A67C52',   // Attention elements
        },
        amber: {
          50:  '#FFF8ED',
          100: '#FFEFD4',
          200: '#FFD9A8',
          300: '#FFBE71',
          400: '#FF9A38',
          500: '#FF7E11',
          600: '#F06307',
          700: '#C74A08',
          800: '#9E3B0F',
          900: '#7F3210',   // Deep rich brown — primary accent
          950: '#452012',   // Darkest brown
        },
        terra: {
          500: '#D95F4E',   // Errors, destructive
          600: '#C24D3D',
        },
        forest: {
          400: '#34D399',
          500: '#10B981',   // Success states
        },
        violet: {
          400: '#A78BFA',
          500: '#8B5CF6',   // CTA buttons, links
          600: '#7C3AED',
        },
        ink: {
          900: '#1C1917',   // Primary text — stone-900
          800: '#292524',   // Secondary text
          700: '#44403C',   // Muted text
          600: '#57534E',   // Lighter muted
        },
        slate: {
          200: '#E2E8F0',
        },
        sidebar: '#E5D0B5',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
        serif: ['DM Serif Display', 'Georgia', 'serif'],
        mono: ['Courier New', 'Courier', 'monospace'],
      },
      borderRadius: {
        'warm': '12px',
      },
      boxShadow: {
        'warm-sm': '0 1px 3px rgba(28, 25, 23, 0.05)',
        'warm':    '0 2px 8px rgba(28, 25, 23, 0.06), 0 1px 2px rgba(28, 25, 23, 0.04)',
        'warm-lg': '0 4px 16px rgba(28, 25, 23, 0.08), 0 2px 4px rgba(28, 25, 23, 0.04)',
        'warm-xl': '0 8px 30px rgba(28, 25, 23, 0.10), 0 4px 8px rgba(28, 25, 23, 0.04)',
        'glow-violet': '0 0 20px rgba(139, 92, 246, 0.15)',
        'glow-amber':  '0 0 20px rgba(194, 65, 12, 0.10)',
      },
      backgroundImage: {
        'gradient-warm': 'linear-gradient(135deg, #FDFAF6 0%, #F7F3ED 50%, #EDE5D8 100%)',
        'gradient-sidebar': 'linear-gradient(180deg, #E5D0B5 0%, #E5D0B5 100%)',
        'gradient-hero': 'linear-gradient(135deg, #FFF8ED 0%, #FDFAF6 30%, #F7F3ED 70%, #EDE5D8 100%)',
        'gradient-card': 'linear-gradient(135deg, rgba(255,255,255,0.9) 0%, rgba(247,243,237,0.9) 100%)',
      },
      animation: {
        'fade-in': 'fadeIn 0.3s ease-out',
        'slide-up': 'slideUp 0.3s ease-out',
        'slide-right': 'slideRight 0.3s ease-out',
        'float': 'float 6s ease-in-out infinite',
        'shimmer': 'shimmer 2s linear infinite',
        'pulse-slow': 'pulse 3s ease-in-out infinite',
      },
      keyframes: {
        fadeIn: {
          from: { opacity: '0' },
          to: { opacity: '1' },
        },
        slideUp: {
          from: { opacity: '0', transform: 'translateY(8px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        slideRight: {
          from: { opacity: '0', transform: 'translateX(-8px)' },
          to: { opacity: '1', transform: 'translateX(0)' },
        },
        float: {
          '0%, 100%': { transform: 'translateY(0)' },
          '50%': { transform: 'translateY(-10px)' },
        },
        shimmer: {
          '0%': { backgroundPosition: '-200% 0' },
          '100%': { backgroundPosition: '200% 0' },
        },
      },
    },
  },
  plugins: [
    require('@tailwindcss/typography'),
  ],
}
