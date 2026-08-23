import { describe, expect, it, vi, beforeEach } from 'vitest'
import { api, clearApiCache } from '@/api'

describe('API request coalescing and in-memory caching', () => {
  beforeEach(() => {
    clearApiCache()
    vi.restoreAllMocks()
  })

  it('coalesces simultaneous identical GET requests into a single in-flight fetch', async () => {
    let fetchCount = 0
    const mockData = { gates: [{ id: 'pead_catalyst', name: 'PEAD', verdict: 'GO' }] }

    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        fetchCount++
        await new Promise((r) => setTimeout(r, 20))
        return {
          ok: true,
          status: 200,
          statusText: 'OK',
          json: async () => mockData,
        } as unknown as Response
      }),
    )

    // Fire 3 simultaneous calls to api.gates()
    const [res1, res2, res3] = await Promise.all([api.gates(), api.gates(), api.gates()])

    expect(res1).toEqual(mockData)
    expect(res2).toEqual(mockData)
    expect(res3).toEqual(mockData)
    // Coalescing ensures fetch was only called once
    expect(fetchCount).toBe(1)
  })

  it('serves subsequent calls from memory cache within TTL without hitting fetch again', async () => {
    let fetchCount = 0
    const mockProfile = {
      symbol: 'AAPL',
      name: 'Apple Inc.',
      price: 230.5,
      market_cap: 3500000000000,
    }

    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        fetchCount++
        return {
          ok: true,
          status: 200,
          statusText: 'OK',
          json: async () => mockProfile,
        } as unknown as Response
      }),
    )

    const first = await api.companyProfile('AAPL')
    expect(first).toEqual(mockProfile)
    expect(fetchCount).toBe(1)

    const second = await api.companyProfile('AAPL')
    expect(second).toEqual(mockProfile)
    // Hit cache, no additional fetch
    expect(fetchCount).toBe(1)

    // After clearing cache, fetch is triggered again
    clearApiCache('/api/company-profile')
    const third = await api.companyProfile('AAPL')
    expect(third).toEqual(mockProfile)
    expect(fetchCount).toBe(2)
  })
})
