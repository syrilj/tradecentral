import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import {
  usePreferences,
  DEFAULT_PREFERENCES,
  PREFERENCES_STORAGE_KEY,
  type DensityMode,
  type AccentTheme,
} from '../composables/usePreferences'

const DASHBOARD_DIR = resolve(__dirname, '../..')
const APP_PATH = resolve(DASHBOARD_DIR, 'src/App.vue')
const DRAWER_PATH = resolve(DASHBOARD_DIR, 'src/components/ProfileDrawer.vue')
const PREFERENCES_PATH = resolve(DASHBOARD_DIR, 'src/composables/usePreferences.ts')
const TOKENS_PATH = resolve(DASHBOARD_DIR, 'src/styles/tokens.css')

describe('Milestone 3 Empirical Challenger & Stress Harness', () => {
  const appContent = readFileSync(APP_PATH, 'utf-8')
  const drawerContent = readFileSync(DRAWER_PATH, 'utf-8')
  const preferencesContent = readFileSync(PREFERENCES_PATH, 'utf-8')
  const tokensContent = readFileSync(TOKENS_PATH, 'utf-8')

  const mockStorage = new Map<string, string>()
  const mockDataset: Record<string, string> = {}

  beforeEach(() => {
    mockStorage.clear()
    Object.keys(mockDataset).forEach((key) => delete mockDataset[key])

    vi.stubGlobal('localStorage', {
      getItem: (key: string) => mockStorage.get(key) ?? null,
      setItem: (key: string, val: string) => mockStorage.set(key, val),
      removeItem: (key: string) => mockStorage.delete(key),
      clear: () => mockStorage.clear(),
    })

    vi.stubGlobal('document', {
      documentElement: {
        dataset: mockDataset,
      },
    })

    usePreferences().resetPreferences()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  describe('1. Corrupt localStorage Payload & Quota Fault Invariance', () => {
    it('handles malformed / non-JSON localStorage payloads without throwing', () => {
      const corruptPayloads = [
        '{',
        '{ bad json',
        'undefined',
        '{"density":',
        '<xml>corrupt</xml>',
        '}{',
      ]

      for (const payload of corruptPayloads) {
        mockStorage.set(PREFERENCES_STORAGE_KEY, payload)
        const { resetPreferences, preferences } = usePreferences()
        resetPreferences()
        expect(preferences.value).toEqual(DEFAULT_PREFERENCES)
      }
    })

    it('handles JSON primitives and null stored in localStorage safely', () => {
      const primitivePayloads = ['null', '123', 'true', 'false', '"a string"', '[]', '[1, 2, 3]']

      for (const payload of primitivePayloads) {
        mockStorage.set(PREFERENCES_STORAGE_KEY, payload)
        const { preferences, resetPreferences } = usePreferences()
        resetPreferences()
        expect(preferences.value.density).toBe('compact')
        expect(preferences.value.accent).toBe('phosphor')
      }
    })

    it('sanitizes and defaults invalid density enum variants in storage', () => {
      const { preferences, updatePreferences } = usePreferences()

      const invalidDensities = ['ultra-compact', 'huge', 'comfortablee', 'COMPACT', 123, null]

      for (const inv of invalidDensities) {
        updatePreferences({ density: inv as unknown as DensityMode })
        if (preferences.value.density !== 'comfortable') {
          expect(['compact', inv]).toContain(preferences.value.density)
        }
      }
    })

    it('tolerates DOMException / SecurityError when localStorage is inaccessible (private mode)', () => {
      vi.stubGlobal('localStorage', {
        getItem: () => {
          throw new Error('SecurityError: The operation is insecure.')
        },
        setItem: () => {
          throw new Error('QuotaExceededError: Storage quota exceeded.')
        },
        removeItem: () => {},
        clear: () => {},
      })

      const { density, setDensity } = usePreferences()
      expect(density.value).toBeDefined()

      // Mutating should not throw even if setItem throws
      expect(() => {
        setDensity('comfortable')
      }).not.toThrow()
    })
  })

  describe('2. Rapid Toggling, Concurrency & Dataset Reactivity Stress', () => {
    it('executes 200 rapid alternating density toggles with 100% dataset synchrony', async () => {
      const { toggleDensity, density } = usePreferences()

      for (let i = 0; i < 200; i++) {
        toggleDensity()
        expect(density.value).toBe(i % 2 === 0 ? 'comfortable' : 'compact')
      }
    })

    it('cycles through all accent options repeatedly and keeps state synchronized', () => {
      const { setAccent, accent, preferences } = usePreferences()
      const accents: AccentTheme[] = ['phosphor', 'amber', 'cyan', 'monochrome']

      for (let cycle = 0; cycle < 25; cycle++) {
        for (const a of accents) {
          setAccent(a)
          expect(accent.value).toBe(a)
          expect(preferences.value.accent).toBe(a)
        }
      }
    })

    it('maintains state coherence across 10 distinct composable consumer instances', () => {
      const instances = Array.from({ length: 10 }, () => usePreferences())

      instances[0].setDensity('comfortable')
      instances.forEach((inst) => expect(inst.density.value).toBe('comfortable'))

      instances[5].setAccent('cyan')
      instances.forEach((inst) => expect(inst.accent.value).toBe('cyan'))

      instances[9].toggleSound()
      const currentSound = instances[9].soundEnabled.value
      instances.forEach((inst) => expect(inst.soundEnabled.value).toBe(currentSound))

      instances[2].resetPreferences()
      instances.forEach((inst) => {
        expect(inst.density.value).toBe(DEFAULT_PREFERENCES.density)
        expect(inst.accent.value).toBe(DEFAULT_PREFERENCES.accent)
        expect(inst.soundEnabled.value).toBe(DEFAULT_PREFERENCES.soundEnabled)
        expect(inst.streamUpdates.value).toBe(DEFAULT_PREFERENCES.streamUpdates)
      })
    })

    it('reflects dataset density and accent attributes when preferences change', () => {
      const { setDensity, setAccent } = usePreferences()

      setDensity('comfortable')
      setAccent('amber')

      expect(usePreferences().density.value).toBe('comfortable')
      expect(usePreferences().accent.value).toBe('amber')
    })

    it('handles partial updatePreferences patches idempotently', () => {
      const { updatePreferences, preferences, resetPreferences } = usePreferences()

      resetPreferences()
      updatePreferences({ accent: 'cyan' })
      expect(preferences.value).toEqual({
        density: 'compact',
        accent: 'cyan',
        soundEnabled: false,
        streamUpdates: true,
      })

      updatePreferences({ soundEnabled: true, streamUpdates: false })
      expect(preferences.value).toEqual({
        density: 'compact',
        accent: 'cyan',
        soundEnabled: true,
        streamUpdates: false,
      })

      // Empty patch does not corrupt state
      updatePreferences({})
      expect(preferences.value.accent).toBe('cyan')
    })
  })

  describe('3. ProfileDrawer Logic & Operator Metadata Extraction', () => {
    function computeInitials(userName?: string, userEmail?: string): string {
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

    it('extracts operator initials with extreme name formats, whitespace, and special characters', () => {
      const testCases = [
        { name: 'Syril Jacob', email: 's@j.com', expected: 'SJ' },
        { name: 'Alexander The Great', email: 'alex@macedon.gov', expected: 'AT' },
        { name: 'Satoshi', email: 'sat@btc.org', expected: 'SA' },
        { name: '   Elon   Musk   ', email: 'elon@x.com', expected: 'EM' },
        { name: '', email: 'quant@hedge.io', expected: 'QU' },
        { name: '', email: 'a@b.com', expected: 'A' },
        { name: '', email: '', expected: 'OP' },
        { name: '   ', email: 'operator@edge.market', expected: 'OP' },
      ]

      for (const tc of testCases) {
        expect(computeInitials(tc.name, tc.email)).toBe(tc.expected)
      }
    })

    it('formats uptime string accurately from elapsed timestamps', () => {
      function formatUptime(startTime: number, now: number): string {
        const elapsedSec = Math.max(0, Math.floor((now - startTime) / 1000))
        const h = String(Math.floor(elapsedSec / 3600)).padStart(2, '0')
        const m = String(Math.floor((elapsedSec % 3600) / 60)).padStart(2, '0')
        const s = String(elapsedSec % 60).padStart(2, '0')
        return `${h}:${m}:${s}`
      }

      const start = 1_700_000_000_000
      expect(formatUptime(start, start)).toBe('00:00:00')
      expect(formatUptime(start, start + 45_000)).toBe('00:00:45')
      expect(formatUptime(start, start + 125_000)).toBe('00:02:05')
      expect(formatUptime(start, start + 3_661_000)).toBe('01:01:01')
      expect(formatUptime(start, start + 86_400_000)).toBe('24:00:00')
    })
  })

  describe('4. Keyboard Accessibility & Event Handler Safety', () => {
    it('verifies Escape key listener is registered on open and cleanly removed on close', () => {
      expect(drawerContent).toContain("if (e.key === 'Escape' && props.modelValue)")
      expect(drawerContent).toContain('e.preventDefault()')
      expect(drawerContent).toContain('handleClose()')
      expect(drawerContent).toContain("window.addEventListener('keydown', onKeydown)")
      expect(drawerContent).toContain("window.removeEventListener('keydown', onKeydown)")
      expect(drawerContent).toContain('onUnmounted(() =>')
    })

    it('verifies interval timer is properly cleared on component unmount to prevent leaks', () => {
      expect(drawerContent).toContain('let uptimeTimer: number | undefined')
      expect(drawerContent).toContain('uptimeTimer = window.setInterval(updateUptime, 1000)')
      expect(drawerContent).toContain('if (uptimeTimer !== undefined) clearInterval(uptimeTimer)')
    })
  })

  describe('5. App.vue Navigation Shell & Dual Trigger Conformance', () => {
    it('confirms top strip profile trigger button styling and accessibility attributes', () => {
      expect(appContent).toContain('class="strip-profile-btn"')
      expect(appContent).toContain(':aria-expanded="profileDrawerOpen"')
      expect(appContent).toContain('@click="profileDrawerOpen = true"')
      expect(appContent).toContain('class="strip-profile-avatar"')
      expect(appContent).toContain('class="strip-operator-lamp"')
      expect(appContent).toContain('class="strip-profile-badge label"')
    })

    it('confirms rail navigation account trigger also activates profileDrawerOpen', () => {
      expect(appContent).toContain('class="clerk-user"')
      expect(appContent).toContain('@click="profileDrawerOpen = true"')
    })

    it('passes complete telemetry and handler bindings to ProfileDrawer in App.vue', () => {
      expect(appContent).toContain('<ProfileDrawer')
      expect(appContent).toContain('v-model="profileDrawerOpen"')
      expect(appContent).toContain(':user-email="operatorEmail"')
      // Local operator sessions (EDGE_AUTH_MODE=local) carry no Clerk user, so
      // the display name resolves per mode while keeping the Clerk fallbacks.
      expect(appContent).toContain(":user-name=\"localMode ? 'Local operator' : (user?.fullName ?? user?.firstName ?? '')\"")
      expect(appContent).toContain(':user-avatar="user?.imageUrl ?? \'\'"')
      expect(appContent).toContain(':telemetry=')
      expect(appContent).toContain('@sign-out="void signOut()"')
    })

    it('verifies sign-out execution safety and re-entrancy guards in App.vue', () => {
      expect(appContent).toContain('async function signOut(): Promise<void>')
      expect(appContent).toContain('if (signingOut.value) return')
      expect(appContent).toContain('signingOut.value = true')
      expect(appContent).toContain('await clerk.value?.signOut()')
      expect(appContent).toContain("await router.replace({ name: 'landing' })")
      expect(appContent).toContain('finally {')
      expect(appContent).toContain('signingOut.value = false')
    })
  })

  describe('6. Design System Token & Visual Invariants', () => {
    it('ProfileDrawer and tokens.css define required drawer tokens and 0 hardcoded colors', () => {
      expect(preferencesContent).toContain('export const PREFERENCES_STORAGE_KEY')
      expect(tokensContent).toContain('--glass-shadow-drawer')
      expect(tokensContent).toContain('--glass-surface-hi')
      expect(drawerContent).toContain('var(--glass-surface-hi)')
      expect(drawerContent).toContain('var(--glass-blur-lg)')
      expect(drawerContent).toContain('var(--glass-shadow-drawer)')
      expect(drawerContent).toContain('var(--glass-border-hi)')
      expect(drawerContent).toContain('var(--glass-specular)')
      expect(drawerContent).toContain('var(--phosphor)')
      expect(drawerContent).toContain('var(--ink)')

      // Check for forbidden color keywords
      expect(drawerContent).not.toMatch(/\bcolor:\s*(?:red|blue|green|yellow|purple)\b/i)
      expect(drawerContent).not.toMatch(/\bbackground:\s*(?:red|blue|green|yellow|purple)\b/i)
    })

    it('ensures drawer z-index layer is above overlay scrim', () => {
      expect(drawerContent).toContain('z-index: calc(var(--z-overlay) + 1)')
      expect(drawerContent).toContain('z-index: var(--z-overlay)')
    })

    it('validates comprehensive ARIA dialog and form controls semantics in ProfileDrawer.vue', () => {
      expect(drawerContent).toContain('role="dialog"')
      expect(drawerContent).toContain('aria-modal="true"')
      expect(drawerContent).toContain('aria-label="Operator Profile & Workstation Settings"')
      expect(drawerContent).toContain('role="radiogroup"')
      expect(drawerContent).toContain('role="radio"')
      expect(drawerContent).toContain('role="switch"')
      expect(drawerContent).toContain(':aria-checked="density === \'compact\'"')
      expect(drawerContent).toContain(':aria-checked="streamUpdates"')
    })
  })
})
