import { computed, ref, watch, type ComputedRef, type Ref } from 'vue'

export type DensityMode = 'compact' | 'comfortable'
export type AccentTheme = 'phosphor' | 'amber' | 'cyan' | 'monochrome'

export interface UserPreferences {
  density: DensityMode
  accent: string
  soundEnabled: boolean
  streamUpdates: boolean
}

export const PREFERENCES_STORAGE_KEY = 'edge.preferences.v1'

export const DEFAULT_PREFERENCES: UserPreferences = {
  density: 'compact',
  accent: 'phosphor',
  soundEnabled: false,
  streamUpdates: true,
}

function loadInitialPreferences(): UserPreferences {
  if (typeof window === 'undefined' || typeof localStorage === 'undefined') {
    return { ...DEFAULT_PREFERENCES }
  }
  try {
    const raw = localStorage.getItem(PREFERENCES_STORAGE_KEY)
    if (!raw) return { ...DEFAULT_PREFERENCES }
    const parsed = JSON.parse(raw) as Partial<UserPreferences>
    return {
      density: parsed.density === 'comfortable' ? 'comfortable' : 'compact',
      accent: typeof parsed.accent === 'string' && parsed.accent ? parsed.accent : 'phosphor',
      soundEnabled: Boolean(parsed.soundEnabled),
      streamUpdates: parsed.streamUpdates !== false,
    }
  } catch {
    return { ...DEFAULT_PREFERENCES }
  }
}

function applyDomAttributes(prefs: UserPreferences): void {
  if (typeof document === 'undefined' || !document.documentElement) return
  document.documentElement.dataset.density = prefs.density
  document.documentElement.dataset.accent = prefs.accent
}

// Global shared state across workstation composable invocations
const preferences = ref<UserPreferences>(loadInitialPreferences())
applyDomAttributes(preferences.value)

// Watch and persist changes
if (typeof window !== 'undefined') {
  watch(
    preferences,
    (val) => {
      applyDomAttributes(val)
      try {
        localStorage.setItem(PREFERENCES_STORAGE_KEY, JSON.stringify(val))
      } catch {
        /* ignore storage quota or private browsing errors */
      }
    },
    { deep: true, immediate: true },
  )
}

export function usePreferences(): {
  preferences: Ref<UserPreferences>
  density: ComputedRef<DensityMode>
  accent: ComputedRef<string>
  soundEnabled: ComputedRef<boolean>
  streamUpdates: ComputedRef<boolean>
  setDensity: (mode: DensityMode) => void
  setAccent: (accent: string) => void
  toggleDensity: () => void
  toggleSound: () => void
  toggleStream: () => void
  updatePreferences: (patch: Partial<UserPreferences>) => void
  resetPreferences: () => void
} {
  const density = computed(() => preferences.value.density)
  const accent = computed(() => preferences.value.accent)
  const soundEnabled = computed(() => preferences.value.soundEnabled)
  const streamUpdates = computed(() => preferences.value.streamUpdates)

  function setDensity(mode: DensityMode): void {
    preferences.value.density = mode
  }

  function setAccent(newAccent: string): void {
    preferences.value.accent = newAccent
  }

  function toggleDensity(): void {
    preferences.value.density = preferences.value.density === 'compact' ? 'comfortable' : 'compact'
  }

  function toggleSound(): void {
    preferences.value.soundEnabled = !preferences.value.soundEnabled
  }

  function toggleStream(): void {
    preferences.value.streamUpdates = !preferences.value.streamUpdates
  }

  function updatePreferences(patch: Partial<UserPreferences>): void {
    preferences.value = {
      ...preferences.value,
      ...patch,
    }
  }

  function resetPreferences(): void {
    preferences.value = { ...DEFAULT_PREFERENCES }
  }

  return {
    preferences,
    density,
    accent,
    soundEnabled,
    streamUpdates,
    setDensity,
    setAccent,
    toggleDensity,
    toggleSound,
    toggleStream,
    updatePreferences,
    resetPreferences,
  }
}
