import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..', '..')

function source(path: string): string {
  return readFileSync(join(root, path), 'utf8')
}

describe('Flow workspace request and rendering budget', () => {
  const flow = source('views/FlowView.vue')
  const states = source('views/FlowStateView.vue')

  it('loads expensive panes on demand and only polls the active pane', () => {
    expect(flow).toMatch(/defineAsyncComponent\(\(\) => import\('@\/views\/FlowStateView\.vue'\)\)/)
    expect(flow).toMatch(/enabled: \(\) => tab\.value === 'live'/)
    expect(flow).toMatch(/immediate: false, enabled: \(\) => tab\.value === 'opportunities'/)
    expect(flow).toMatch(/v-if="showStructureBoard"/)
  })

  it('keeps the selected tab shareable through the route query', () => {
    expect(flow).toMatch(/flowTab\(route\.query\.tab\)/)
    expect(flow).toMatch(/router\.replace\(\{ query \}\)/)
    expect(flow).toContain('aria-controls="flow-states-panel"')
  })

  it('batches the large event ledger instead of mounting every row', () => {
    expect(states).toMatch(/const eventLimit = ref\(100\)/)
    expect(states).toMatch(/filteredEvents\.value\.slice\(0, eventLimit\.value\)/)
    expect(states).toMatch(/v-for="\(e, i\) in visibleEvents"/)
  })
})
