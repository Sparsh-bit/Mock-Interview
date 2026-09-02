import type { Config } from 'tailwindcss';

const config: Config = {
  content: [
    './src/pages/**/*.{js,ts,jsx,tsx,mdx}',
    './src/components/**/*.{js,ts,jsx,tsx,mdx}',
    './src/app/**/*.{js,ts,jsx,tsx,mdx}',
    './src/lib/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  darkMode: ['class'],
  theme: {
    container: {
      center: true,
      padding: '2rem',
      screens: {
        '2xl': '1400px',
      },
    },
    extend: {
      /*
       * ── A breakpoint on HEIGHT, not width ────────────────────────────────
       *
       * WHY THIS EXISTS. Every other breakpoint in this file is about width, and width is not
       * what broke the live interview. The interview workspace pins itself to the viewport —
       * `h-[100dvh] overflow-hidden` with each pane scrolling inside — so that the microphone
       * and Submit do not move under the candidate's thumb as the panel talks. That model has
       * a floor it cannot compress below, and the floor is REAL PIXELS:
       *
       *     h-16 header                                    64
       *     mobile pane switcher (p-2 + min-h-10 + border)  57
       *     grid padding (p-3, top and bottom)              24
       *     pane padding (p-4, top and bottom)              32
       *     phase badges row + its mb-4                      38
       *     the pinned question (line-clamp-3 + py-3)        87
       *     the answer channel: pt-4 + py-4 + 80px mic
       *       + prompt + hands-free pill + the 96px
       *       transcript floor + the button row            390
       *     ------------------------------------------------------
       *                                                    692  with the panel thread at ZERO
       *
       * Under 692 CSS px of viewport height the button row is simply outside the root box, and
       * because the root is `overflow-hidden` there is no scrollbar and no gesture anywhere on
       * the page that reaches it. The candidate cannot submit their answer. Not a hypothetical:
       * BROWSER ZOOM IS EXACTLY THIS. Zoom does not shrink CSS pixels, it shrinks how many of
       * them the window holds, so a 900px-tall window is a 450px viewport at 200% and a 225px
       * one at 400% — and WCAG 1.4.4 requires the page to still work at 200%. A landscape phone
       * (844x390) is under the floor before any zoom at all.
       *
       * 700px is the measured floor rounded up to the next hundred. Above it, nothing changes
       * anywhere in the app — this is a `raw` media query, so it emits no CSS unless a
       * `short:` variant is actually used, and today only the interview workspace uses it, to
       * hand back the ordinary page scroll: `short:h-auto short:min-h-[100dvh]
       * short:overflow-visible` on the root, and `short:overflow-visible` on each pane that
       * would otherwise still be clipping inside a page that now scrolls.
       *
       * It is deliberately a height-only query with no width term, because the failure has
       * nothing to do with width: a 3440px-wide ultrawide window dragged to 400px tall loses
       * the Submit button exactly the same way a phone in landscape does.
       *
       * Tailwind orders extended screens after the built-in ones, so `short:` wins against a
       * `lg:` rule on the same property. That is the intent — a short viewport needs the
       * escape hatch whatever its width.
       */
      screens: {
        short: { raw: '(max-height: 700px)' },
      },
      colors: {
        border: 'hsl(var(--border))',
        input: 'hsl(var(--input))',
        ring: 'hsl(var(--ring))',
        background: 'hsl(var(--background))',
        foreground: 'hsl(var(--foreground))',
        surface: {
          DEFAULT: 'hsl(var(--surface))',
          elevated: 'hsl(var(--surface-elevated))',
          overlay: 'hsl(var(--surface-overlay))',
        },
        primary: {
          DEFAULT: 'hsl(var(--primary))',
          foreground: 'hsl(var(--primary-foreground))',
        },
        secondary: {
          DEFAULT: 'hsl(var(--secondary))',
          foreground: 'hsl(var(--secondary-foreground))',
        },
        destructive: {
          DEFAULT: 'hsl(var(--destructive))',
          foreground: 'hsl(var(--destructive-foreground))',
        },
        muted: {
          DEFAULT: 'hsl(var(--muted))',
          foreground: 'hsl(var(--muted-foreground))',
        },
        // ── The six working colours ──────────────────────────────────────
        // Namespaced under `accent` deliberately. `indigo`, `amber`, `emerald`
        // and `teal` are built-in Tailwind palette names — declaring them at the
        // top level of `extend.colors` replaces the whole default scale, which
        // would silently break `text-emerald-600`, `bg-amber-50` and the badge
        // classes in globals.css. Nesting also keeps `bg-accent` and the older
        // `text-accent-violet` usages working unchanged.
        //
        // Each colour is bound to one meaning (see globals.css). Three tones:
        //   -ink   text — the only tone safe under ~18px, all ≥4.5:1 on paper
        //   (bare) fills, strokes, graphics
        //   -soft  tinted backgrounds
        // `text-accent-amber` on body copy is a bug, not a style choice: it
        // measures 2.9:1. That is what the ink tone is for.
        accent: {
          DEFAULT: 'hsl(var(--accent))',
          foreground: 'hsl(var(--accent-foreground))',

          indigo: 'hsl(var(--accent-indigo))',
          'indigo-ink': 'hsl(var(--accent-indigo-ink))',
          'indigo-soft': 'hsl(var(--accent-indigo-soft))',

          amber: 'hsl(var(--accent-amber))',
          'amber-ink': 'hsl(var(--accent-amber-ink))',
          'amber-soft': 'hsl(var(--accent-amber-soft))',
          'amber-hot': 'hsl(var(--accent-amber-hot))',

          emerald: 'hsl(var(--accent-emerald))',
          'emerald-ink': 'hsl(var(--accent-emerald-ink))',
          'emerald-soft': 'hsl(var(--accent-emerald-soft))',

          coral: 'hsl(var(--accent-coral))',
          'coral-ink': 'hsl(var(--accent-coral-ink))',
          'coral-soft': 'hsl(var(--accent-coral-soft))',

          teal: 'hsl(var(--accent-teal))',
          'teal-ink': 'hsl(var(--accent-teal-ink))',
          'teal-soft': 'hsl(var(--accent-teal-soft))',

          plum: 'hsl(var(--accent-plum))',
          'plum-ink': 'hsl(var(--accent-plum-ink))',
          'plum-soft': 'hsl(var(--accent-plum-soft))',

          // Older names, resolved to the palette above so screens not yet
          // migrated pick up the new colour instead of keeping two systems.
          violet: 'hsl(var(--accent-plum))',
          cyan: 'hsl(var(--accent-teal))',
        },
        card: {
          DEFAULT: 'hsl(var(--card))',
          foreground: 'hsl(var(--card-foreground))',
        },
        popover: {
          DEFAULT: 'hsl(var(--popover))',
          foreground: 'hsl(var(--popover-foreground))',
        },
        // Custom brand colors
        brand: {
          50: '#eff6ff',
          100: '#dbeafe',
          200: '#bfdbfe',
          300: '#93c5fd',
          400: '#60a5fa',
          500: '#3b82f6',
          600: '#2563eb',
          700: '#1d4ed8',
          800: '#1e40af',
          900: '#1e3a8a',
          950: '#172554',
        },
        // Semantic colors
        success: {
          DEFAULT: 'hsl(var(--success))',
          foreground: 'hsl(var(--success-foreground))',
        },
        warning: {
          DEFAULT: 'hsl(var(--warning))',
          foreground: 'hsl(var(--warning-foreground))',
        },
      },
      // Mapped onto the ladder in globals.css so the Tailwind name and the
      // design step mean the same thing. See the comment there for the nesting
      // rule these exist to make possible.
      borderRadius: {
        sm: 'var(--radius-xs)',   //  6px — chips
        md: 'var(--radius-sm)',   // 10px — inputs, buttons
        lg: 'var(--radius)',      // 14px — inner panels, rows
        xl: 'var(--radius-lg)',   // 20px — cards
        '2xl': 'var(--radius-xl)', // 28px — page surfaces, sheets
      },

      transitionTimingFunction: {
        'out-expo': 'var(--ease-out-expo)',
        spring: 'var(--ease-spring)',
        smooth: 'var(--ease-in-out-smooth)',
      },
      fontFamily: {
        sans: ['var(--font-inter)', 'system-ui', 'sans-serif'],
        mono: ['var(--font-jetbrains-mono)', 'Menlo', 'monospace'],
        /*
         * THE DISPLAY FACE. Fraunces, loaded in app/layout.tsx alongside Inter.
         *
         * It arrived with the public-site retheme and it is deliberately available inside the
         * product too, for exactly ONE job: the page title. Every screen in the app is a
         * dashboard made of white cards on warm paper, and the single cheapest way to make a
         * dashboard look considered rather than generated is for the largest piece of type on
         * it to be a serif set at a normal weight. Everything below the title stays Inter,
         * because a serif at 13px in a table is unreadable and a serif everywhere is a
         * different product.
         *
         * The variable font carries an optical-size axis, so the same file holds its
         * proportions from a 24px page title to the 100px hero on the landing page. That is
         * why this costs one file rather than two cuts.
         */
        display: ['var(--font-fraunces)', 'Georgia', 'serif'],
      },
      keyframes: {
        'accordion-down': {
          from: { height: '0' },
          to: { height: 'var(--radix-accordion-content-height)' },
        },
        'accordion-up': {
          from: { height: 'var(--radix-accordion-content-height)' },
          to: { height: '0' },
        },
        'fade-in': {
          from: { opacity: '0', transform: 'translateY(8px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        'slide-in-left': {
          from: { opacity: '0', transform: 'translateX(-16px)' },
          to: { opacity: '1', transform: 'translateX(0)' },
        },
        'scale-in': {
          from: { opacity: '0', transform: 'scale(0.96)' },
          to: { opacity: '1', transform: 'scale(1)' },
        },
        shimmer: {
          '0%': { backgroundPosition: '-200% 0' },
          '100%': { backgroundPosition: '200% 0' },
        },
        pulse: {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.4' },
        },
        float: {
          '0%, 100%': { transform: 'translateY(0px)' },
          '50%': { transform: 'translateY(-8px)' },
        },
        glow: {
          '0%, 100%': { boxShadow: '0 0 20px hsl(var(--primary) / 0.2)' },
          '50%': { boxShadow: '0 0 40px hsl(var(--primary) / 0.4)' },
        },
      },
      animation: {
        'accordion-down': 'accordion-down 0.2s ease-out',
        'accordion-up': 'accordion-up 0.2s ease-out',
        'fade-in': 'fade-in 0.4s ease-out',
        'slide-in-left': 'slide-in-left 0.3s ease-out',
        'scale-in': 'scale-in 0.2s ease-out',
        shimmer: 'shimmer 2s linear infinite',
        float: 'float 3s ease-in-out infinite',
        glow: 'glow 2s ease-in-out infinite',
      },
      boxShadow: {
        // The elevation ladder. Each level pairs a wide ambient shadow with a
        // tighter contact shadow, which is how a real object sits on a surface;
        // a single large blur reads as a sticker. Values live in globals.css so
        // they can differ between light and dark — the same alpha over a dark
        // surface is invisible.
        'elev-1': 'var(--elev-1)',
        'elev-2': 'var(--elev-2)',
        'elev-3': 'var(--elev-3)',
        // Soft, diffuse Apple-style elevation — no colored glows.
        glow: '0 1px 2px rgba(20,20,25,0.04), 0 8px 24px rgba(20,20,25,0.06)',
        'glow-lg': '0 2px 4px rgba(20,20,25,0.05), 0 20px 48px rgba(20,20,25,0.10)',
        card: '0 1px 2px rgba(20,20,25,0.04), 0 8px 24px rgba(20,20,25,0.05)',
        'card-hover': '0 2px 4px rgba(20,20,25,0.05), 0 16px 40px rgba(20,20,25,0.08)',
        'btn-primary': '0 1px 2px rgba(0,113,227,0.25), 0 4px 12px rgba(0,113,227,0.20)',
      },
      backgroundImage: {
        'gradient-radial': 'radial-gradient(var(--tw-gradient-stops))',
        'gradient-conic': 'conic-gradient(from 180deg at 50% 50%, var(--tw-gradient-stops))',
        'grid-pattern':
          'linear-gradient(rgba(59,130,246,0.05) 1px, transparent 1px), linear-gradient(to right, rgba(59,130,246,0.05) 1px, transparent 1px)',
        'noise': "url('/noise.svg')",
      },
      backgroundSize: {
        grid: '48px 48px',
      },
    },
  },
  plugins: [require('tailwindcss-animate')],
};

export default config;
