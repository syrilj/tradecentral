import { describe, it, expect, beforeEach, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import {
  usePreferences,
  DEFAULT_PREFERENCES,
  PREFERENCES_STORAGE_KEY,
  type DensityMode,
  type AccentTheme,
  type UserPreferences,
} from '../composables/usePreferences'

const DASHBOARD_DIR = resolve(__dirname, '../..')
const APP_PATH = resolve(DASHBOARD_DIR, 'src/App.vue')
const DRAWER_PATH = resolve(DASHBOARD_DIR, 'src/components/ProfileDrawer.vue')
const PREFERENCES_PATH = resolve(DASHBOARD_DIR, 'src/composables/usePreferences.ts')
const TOKENS_PATH = resolve(DASHBOARD_DIR, 'src/styles/tokens.css')

describe('Milestone 3: Workstation Preferences & Profile Drawer Suite', () => {
  const appContent = readFileSync(APP_PATH, 'utf-8')
  const drawerContent = readFileSync(DRAWER_PATH, 'utf-8')
  const preferencesContent = readFileSync(PREFERENCES_PATH, 'utf-8')
  const tokensContent = readFileSync(TOKENS_PATH, 'utf-8')

  // Mock localStorage and document dataset
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
  })

  describe('1. usePreferences Composable Architecture & State Mechanics', () => {
    it('declares the designated localStorage key and default configuration', () => {
      expect(PREFERENCES_STORAGE_KEY).toBe('edge.preferences.v1')
      expect(preferencesContent).toContain('export const PREFERENCES_STORAGE_KEY')
      expect(tokensContent).toContain('--glass-shadow-drawer')
      expect(tokensContent).toContain('--glass-surface-hi')
      expect(DEFAULT_PREFERENCES).toEqual({
        density: 'compact',
        accent: 'phosphor',
        soundEnabled: false,
        streamUpdates: true,
      })
    })

    it('manages reactive density mode (compact vs comfortable)', () => {
      const { density, setDensity, toggleDensity } = usePreferences()
      const modeCompact: DensityMode = 'compact'
      const modeComfortable: DensityMode = 'comfortable'

      setDensity(modeCompact)
      expect(density.value).toBe('compact')

      setDensity(modeComfortable)
      expect(density.value).toBe('comfortable')

      toggleDensity()
      expect(density.value).toBe('compact')

      toggleDensity()
      expect(density.value).toBe('comfortable')
    })

    it('manages accent theme selection and updates reactive state', () => {
      const { accent, setAccent } = usePreferences()

      const accents: AccentTheme[] = ['phosphor', 'amber', 'cyan', 'monochrome']
      for (const a of accents) {
        setAccent(a)
        expect(accent.value).toBe(a)
      }
    })

    it('manages sound alert cues and real-time streaming updates toggles', () => {
      const { soundEnabled, streamUpdates, toggleSound, toggleStream } = usePreferences()

      const initialSound = soundEnabled.value
      toggleSound()
      expect(soundEnabled.value).toBe(!initialSound)
      toggleSound()
      expect(soundEnabled.value).toBe(initialSound)

      const initialStream = streamUpdates.value
      toggleStream()
      expect(streamUpdates.value).toBe(!initialStream)
      toggleStream()
      expect(streamUpdates.value).toBe(initialStream)
    })

    it('provides batch updatePreferences and resetPreferences capabilities', () => {
      const { preferences, updatePreferences, resetPreferences } = usePreferences()

      const patch: Partial<UserPreferences> = {
        density: 'comfortable',
        accent: 'cyan',
        soundEnabled: true,
        streamUpdates: false,
      }
      updatePreferences(patch)

      const expected: UserPreferences = {
        density: 'comfortable',
        accent: 'cyan',
        soundEnabled: true,
        streamUpdates: false,
      }
      expect(preferences.value).toEqual(expected)

      resetPreferences()
      expect(preferences.value).toEqual(DEFAULT_PREFERENCES)
    })

    it('synchronizes preferences across multiple composable consumer instances', () => {
      const instanceA = usePreferences()
      const instanceB = usePreferences()

      instanceA.setDensity('comfortable')
      expect(instanceB.density.value).toBe('comfortable')

      instanceB.setAccent('amber')
      expect(instanceA.accent.value).toBe('amber')
    })
  })

  describe('2. ProfileDrawer Component Structural & Visual Contracts', () => {
    it('declares essential props and emits interface for ProfileDrawer.vue', () => {
      expect(drawerContent).toMatch(/modelValue\??:\s*boolean/)
      expect(drawerContent).toContain('userEmail?: string')
      expect(drawerContent).toContain('userName?: string')
      expect(drawerContent).toContain('userAvatar?: string')
      expect(drawerContent).toContain('operatorRole?: string')
      expect(drawerContent).toContain('telemetry?: WorkstationTelemetry')
      expect(drawerContent).toContain("emit('update:modelValue', false)")
      expect(drawerContent).toContain("emit('close')")
      expect(drawerContent).toContain("emit('signOut')")
      expect(drawerContent).toContain("emit('updatePreferences', preferences.value)")
    })

    it('utilizes designated modern glassmorphism tokens in ProfileDrawer.vue', () => {
      expect(drawerContent).toContain('var(--glass-surface-hi)')
      expect(drawerContent).toContain('var(--glass-blur-lg)')
      expect(drawerContent).toContain('var(--glass-shadow-drawer)')
      expect(drawerContent).toContain('var(--glass-border-hi)')
      expect(drawerContent).toContain('var(--glass-specular)')
      expect(drawerContent).toContain('var(--glass-overlay)')
    })

    it('renders complete operator identification, clearance, and session uptime', () => {
      expect(drawerContent).toContain('Operator Profile')
      expect(drawerContent).toContain('OP·AUTH')
      expect(drawerContent).toContain('CLEARANCE')
      expect(drawerContent).toContain('VERIFIED · LEVEL 4')
      expect(drawerContent).toContain('UPTIME')
      expect(drawerContent).toContain('sessionUptime')
    })

    it('features interactive density segmented controls and accent swatches', () => {
      expect(drawerContent).toContain('Layout Spacing Density')
      expect(drawerContent).toContain('role="radiogroup"')
      expect(drawerContent).toContain('role="radio"')
      expect(drawerContent).toContain('Compact')
      expect(drawerContent).toContain('Comfortable')
      expect(drawerContent).toContain('Workstation Accent Tone')
      expect(drawerContent).toContain('Real-Time Stream Updates')
      expect(drawerContent).toContain('Auditory Flow Signals')
      expect(drawerContent).toContain('role="switch"')
    })

    it('features telemetry section with live API status, quant engine, and active desk', () => {
      expect(drawerContent).toContain('SYSTEM TELEMETRY')
      expect(drawerContent).toContain('API ENDPOINT')
      expect(drawerContent).toContain('127.0.0.1:8787')
      expect(drawerContent).toContain('QUANT KERNEL')
      expect(drawerContent).toContain('PYTHON 3.10 · NUMPY / SCIPY')
      expect(drawerContent).toContain('ACTIVE DESK')
    })

    it('includes operator sign-out action with keyboard accessibility (Esc)', () => {
      expect(drawerContent).toContain('btn-signout')
      expect(drawerContent).toContain('SIGN OUT OF OPERATOR WORKSTATION')
      expect(drawerContent).toContain("e.key === 'Escape'")
    })
  })

  describe('3. App.vue Integration & Dual Profile Triggers', () => {
    it('imports and initializes usePreferences in App.vue', () => {
      expect(appContent).toContain("import { usePreferences } from '@/composables/usePreferences'")
      expect(appContent).toContain('const { preferences } = usePreferences()')
      expect(appContent).toContain('const profileDrawerOpen = ref(false)')
    })

    it('mounts ProfileDrawer component with reactive bindings and handlers', () => {
      expect(appContent).toContain("import ProfileDrawer from '@/components/ProfileDrawer.vue'")
      expect(appContent).toContain('<ProfileDrawer')
      expect(appContent).toContain('v-model="profileDrawerOpen"')
      expect(appContent).toContain(':user-email="operatorEmail"')
      expect(appContent).toContain(':telemetry=')
      expect(appContent).toContain('@sign-out="void signOut()"')
    })

    it('places top-right operator profile trigger button in top strip header', () => {
      expect(appContent).toContain('class="strip-profile-btn"')
      expect(appContent).toContain('class="strip-profile-avatar"')
      expect(appContent).toContain('class="strip-operator-lamp"')
      expect(appContent).toContain('class="strip-profile-badge label"')
      expect(appContent).toContain('@click="profileDrawerOpen = true"')
      expect(appContent).toContain(':aria-expanded="profileDrawerOpen"')
    })

    it('connects side navigation rail account block to open ProfileDrawer', () => {
      expect(appContent).toContain('class="clerk-user"')
      expect(appContent).toContain('@click="profileDrawerOpen = true"')
    })

    it('dynamically synchronizes layout density on startup without hardcoded locks', () => {
      expect(appContent).toContain(
        'document.documentElement.dataset.density = preferences.value.density',
      )
      expect(appContent).not.toContain("document.documentElement.dataset.density = 'compact'")
    })
  })

  describe('4. Strict Design Conformance Verification for Milestone 3 Files', () => {
    it('verifies ProfileDrawer contains 0 hardcoded palette colors', () => {
      // Regex checking for non-structural hex / rgb colors
      const hexMatch = drawerContent.match(/#(?:[0-9a-fA-F]{3,8})\b/g)
      expect(hexMatch).toBeNull()

      const nonStructuralRgb = [
        ...drawerContent.matchAll(/rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/g),
      ].filter(([, r, g, b]) => {
        const isBlack = r === '0' && g === '0' && b === '0'
        const isWhite = r === '255' && g === '255' && b === '255'
        return !isBlack && !isWhite
      })
      expect(nonStructuralRgb.length).toBe(0)
    })

    it('verifies ProfileDrawer contains no forbidden glow effects or filters', () => {
      expect(drawerContent).not.toMatch(/box-shadow:\s*0\s*0\s*\d+px/i)
      expect(drawerContent).not.toMatch(/text-shadow/i)
      expect(drawerContent).not.toMatch(/filter:\s*brightness/i)
      expect(drawerContent).not.toMatch(/radial-gradient/i)
    })
  })
})
