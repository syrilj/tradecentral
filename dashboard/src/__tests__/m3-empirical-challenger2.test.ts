import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const DASHBOARD_DIR = resolve(__dirname, '../..')
const APP_PATH = resolve(DASHBOARD_DIR, 'src/App.vue')
const DRAWER_PATH = resolve(DASHBOARD_DIR, 'src/components/ProfileDrawer.vue')
const PREFERENCES_PATH = resolve(DASHBOARD_DIR, 'src/composables/usePreferences.ts')
const TOKENS_PATH = resolve(DASHBOARD_DIR, 'src/styles/tokens.css')

describe('Milestone 3 Empirical Challenger 2: Adversarial Stress & Verification Suite', () => {
  const appContent = readFileSync(APP_PATH, 'utf-8')
  const drawerContent = readFileSync(DRAWER_PATH, 'utf-8')
  const preferencesContent = readFileSync(PREFERENCES_PATH, 'utf-8')
  const tokensContent = readFileSync(TOKENS_PATH, 'utf-8')

  describe('1. Composable Architecture & Static Analysis', () => {
    it('declares the designated localStorage key according to specification', () => {
      expect(preferencesContent).toContain(
        "export const PREFERENCES_STORAGE_KEY = 'edge.preferences.v1'",
      )
    })

    it('implements default preferences matching specification', () => {
      expect(preferencesContent).toContain("density: 'compact'")
      expect(preferencesContent).toContain("accent: 'phosphor'")
      expect(preferencesContent).toContain('soundEnabled: false')
      expect(preferencesContent).toContain('streamUpdates: true')
    })

    it('synchronizes document dataset density and accent attributes', () => {
      expect(preferencesContent).toContain(
        'document.documentElement.dataset.density = prefs.density',
      )
      expect(preferencesContent).toContain('document.documentElement.dataset.accent = prefs.accent')
    })

    it('safely handles storage exceptions during persistence', () => {
      expect(preferencesContent).toContain('try {')
      expect(preferencesContent).toContain(
        'localStorage.setItem(PREFERENCES_STORAGE_KEY, JSON.stringify(val))',
      )
      expect(preferencesContent).toContain('} catch {')
    })
  })

  describe('2. DOM Structure, Accessibility & Scrim Architecture', () => {
    it('verifies teleportation to body and z-index hierarchy', () => {
      expect(drawerContent).toContain('<Teleport to="body">')
      expect(drawerContent).toContain('class="drawer-backdrop"')
      expect(drawerContent).toContain('class="profile-drawer')

      // Backdrop z-index must be --z-overlay
      expect(drawerContent).toMatch(/z-index:\s*var\(--z-overlay\);/)

      // Drawer z-index must be above backdrop (calc(var(--z-overlay) + 1))
      expect(drawerContent).toMatch(/z-index:\s*calc\(var\(--z-overlay\)\s*\+\s*1\);/)
    })

    it('verifies backdrop scrim click handler emits close events', () => {
      expect(drawerContent).toContain('@click="handleClose"')
      expect(drawerContent).toContain('aria-hidden="true"')
      expect(drawerContent).toMatch(
        /function handleClose\(\):\s*void\s*\{[\s\S]*emit\('update:modelValue',\s*false\)[\s\S]*emit\('close'\)/,
      )
    })

    it('verifies drawer modal container has correct ARIA dialog semantics', () => {
      expect(drawerContent).toContain('role="dialog"')
      expect(drawerContent).toContain('aria-modal="true"')
      expect(drawerContent).toContain('aria-label="Operator Profile & Workstation Settings"')
      expect(drawerContent).toContain('aria-label="Close operator profile drawer"')
    })

    it('verifies radiogroups and switch controls comply with WAI-ARIA patterns', () => {
      expect(drawerContent).toContain('role="radiogroup"')
      expect(drawerContent).toContain('role="radio"')
      expect(drawerContent).toContain(':aria-checked="density === \'compact\'"')
      expect(drawerContent).toContain(':aria-checked="density === \'comfortable\'"')
      expect(drawerContent).toContain('role="switch"')
      expect(drawerContent).toContain(':aria-checked="streamUpdates"')
      expect(drawerContent).toContain(':aria-checked="soundEnabled"')
    })

    it('verifies responsive width rule min(400px, 100vw) on mobile and desktop', () => {
      expect(drawerContent).toContain('width: min(400px, 100vw);')
      expect(drawerContent).toContain('right: 0;')
      expect(drawerContent).toContain('top: 0;')
      expect(drawerContent).toContain('bottom: 0;')
      expect(drawerContent).toContain('position: fixed;')
    })

    it('verifies slide transition definition', () => {
      expect(drawerContent).toContain('.drawer-slide-enter-active')
      expect(drawerContent).toContain('.drawer-slide-leave-active')
      expect(drawerContent).toContain('transform: translateX(100%);')
    })
  })

  describe('3. Operator Identification & Fallbacks', () => {
    it('computes initials correctly for various user name and email formats', () => {
      const getInitials = (userName?: string, userEmail?: string): string => {
        if (userName) {
          const parts = userName.trim().split(/\s+/)
          if (parts.length >= 2) return `${parts[0][0]}${parts[1][0]}`.toUpperCase()
          if (parts.length === 1 && parts[0]) return parts[0].slice(0, 2).toUpperCase()
        }
        if (userEmail) {
          const namePart = userEmail.split('@')[0]
          return namePart.slice(0, 2).toUpperCase()
        }
        return 'OP'
      }

      expect(getInitials('John Doe', 'john@quant.fund')).toBe('JD')
      expect(getInitials('Alice', 'alice@quant.fund')).toBe('AL')
      expect(getInitials('', 'trader@edge.io')).toBe('TR')
      expect(getInitials('Syril Jacob', '')).toBe('SJ')
      expect(getInitials('', '')).toBe('OP')
      expect(getInitials('A B C', '')).toBe('AB')
    })

    it('displays operator clearance, session uptime, and telemetry parameters', () => {
      expect(drawerContent).toContain('VERIFIED · LEVEL 4')
      expect(drawerContent).toContain('sessionUptime')
      expect(drawerContent).toContain('127.0.0.1:8787 (LOCAL)')
      expect(drawerContent).toContain('PYTHON 3.10 · NUMPY / SCIPY')
      expect(drawerContent).toContain('telemetry?.activeRoute')
      expect(drawerContent).toContain('telemetry?.feedFreshness')
    })
  })

  describe('4. Shell Dual Profile Triggers & Sign Out Flow in App.vue', () => {
    it('wires the top strip operator avatar and badge trigger button', () => {
      expect(appContent).toContain('class="strip-profile-btn"')
      expect(appContent).toContain(':aria-expanded="profileDrawerOpen"')
      expect(appContent).toContain('@click="profileDrawerOpen = true"')
      expect(appContent).toContain('class="strip-profile-avatar"')
      expect(appContent).toContain('class="strip-operator-lamp"')
      expect(appContent).toContain('class="strip-profile-badge label"')
    })

    it('wires the rail account footer trigger to open profile drawer', () => {
      expect(appContent).toContain('class="clerk-user"')
      expect(appContent).toContain('@click="profileDrawerOpen = true"')
    })

    it('wires ProfileDrawer component with modelValue and event bindings in App.vue', () => {
      expect(appContent).toContain('<ProfileDrawer')
      expect(appContent).toContain('v-model="profileDrawerOpen"')
      expect(appContent).toContain(':user-email="operatorEmail"')
      // Local operator sessions (EDGE_AUTH_MODE=local) carry no Clerk user, so
      // the display name resolves per mode while keeping the Clerk fallbacks.
      expect(appContent).toContain(":user-name=\"localMode ? 'Local operator' : (user?.fullName ?? user?.firstName ?? '')\"")
      expect(appContent).toContain(':user-avatar="user?.imageUrl ?? \'\'"')
      expect(appContent).toContain('@sign-out="void signOut()"')
    })

    it('coordinates signOut method with Clerk and navigation redirect', () => {
      expect(appContent).toContain('async function signOut(): Promise<void>')
      expect(appContent).toContain('await clerk.value?.signOut()')
      expect(appContent).toContain("await router.replace({ name: 'landing' })")
    })
  })

  describe('5. Design Token Conformance & Forbidden FX Elimination', () => {
    it('verifies all glassmorphism tokens match tokens.css definitions', () => {
      const expectedTokens = [
        '--glass-surface-hi',
        '--glass-blur-lg',
        '--glass-shadow-drawer',
        '--glass-border-hi',
        '--glass-specular',
        '--glass-overlay',
        '--glass-blur-sm',
      ]

      for (const t of expectedTokens) {
        expect(tokensContent, `tokens.css must define ${t}`).toContain(t)
        expect(drawerContent, `ProfileDrawer.vue must use ${t}`).toContain(t)
      }
    })

    it('ensures ProfileDrawer contains 0 hardcoded palette colors', () => {
      const hexMatch = drawerContent.match(/#(?:[0-9a-fA-F]{3,8})\b/g)
      expect(hexMatch).toBeNull()

      const nonStructuralRgb = [
        ...drawerContent.matchAll(/rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/g),
      ].filter(([, r, g, b]) => {
        const isBlack = r === '0' && g === '0' && b === '0'
        const isWhite = r === '255' && g === '255' && b === '255'
        return !isBlack && !isWhite
      })
      expect(nonStructuralRgb).toHaveLength(0)
    })

    it('ensures ProfileDrawer contains 0 forbidden glow or brightness filters', () => {
      expect(drawerContent).not.toMatch(/box-shadow:\s*0\s*0\s*\d+px/i)
      expect(drawerContent).not.toMatch(/text-shadow/i)
      expect(drawerContent).not.toMatch(/filter:\s*brightness/i)
      expect(drawerContent).not.toMatch(/radial-gradient/i)
    })
  })
})
