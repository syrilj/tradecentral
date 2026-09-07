<script setup lang="ts">
/**
 * Repo knowledge graph — the graphify index of `edge/`, rendered as a chord
 * diagram.
 *
 * Why a chord diagram and not the usual force-directed blob:
 *
 *  · A force layout is non-deterministic. Reload the page and every node is
 *    somewhere else, so nothing can be compared against a previous look and
 *    no position carries meaning. That is the opposite of an instrument.
 *  · Physics simulation also implies a spatial metric that does not exist —
 *    "these two nodes are close" reads as a measurement when it is really an
 *    artifact of the solver's random seed.
 *
 * Here the layout is a pure function of (community, degree rank), so the same
 * graph always draws identically and position is readable: angle = which
 * community, radius tick = which node within it, chord = a real edge.
 */
import { computed, ref } from 'vue'
import { api, type GraphPayload, type GraphNode } from '@/api'
import { useResource } from '@/composables/useResource'
import { age, DASH } from '@/format'
import Panel from '@/components/Panel.vue'
import Readout from '@/components/Readout.vue'
import LoadingState from '@/components/LoadingState.vue'

const graph = useResource<GraphPayload>(() => api.graph(), { intervalMs: 300_000 })

const selected = ref<string | null>(null)
const hovered = ref<string | null>(null)
const activeCommunity = ref<string | null>(null)

const payload = computed(() => graph.data.value)
const available = computed(() => payload.value?.available === true)
const nodes = computed(() => payload.value?.nodes ?? [])
const edges = computed(() => payload.value?.edges ?? [])
const rawCommunities = computed(() => payload.value?.communities ?? [])
const stats = computed(() => payload.value?.stats ?? null)

/* ---- the long tail -------------------------------------------------------
   Louvain on a real repo returns a heavily skewed community distribution —
   this one produced 118 communities over 400 nodes, most of them two or three
   files. Drawing 118 sectors gives 118 unreadable slivers and 118 overlapping
   labels, and the handful of clusters that actually describe the codebase get
   the same visual weight as a pair of orphaned test fixtures.

   So the tail is collapsed into one explicit "other" sector rather than
   dropped. Collapsing keeps every node on the ring and keeps the node count
   honest; dropping would quietly change what the diagram claims to show. */
const TOP_COMMUNITIES = 11
const OTHER = '__other__'

const keptIds = computed(() => {
  const ranked = [...rawCommunities.value].sort((a, b) => b.size - a.size)
  return new Set(ranked.slice(0, TOP_COMMUNITIES).map((c) => c.id))
})

const collapsed = computed(() => rawCommunities.value.length > TOP_COMMUNITIES + 1)

/** Community id a node is drawn under, after tail collapsing. */
function displayCommunity(id: string | null | undefined): string {
  if (!id) return OTHER
  if (!collapsed.value) return id
  return keptIds.value.has(id) ? id : OTHER
}

/** Communities as rendered: the top slice, plus one aggregated tail row. */
const communities = computed(() => {
  const ranked = [...rawCommunities.value].sort((a, b) => b.size - a.size)
  if (!collapsed.value) return ranked.map((c, i) => ({ ...c, color_index: i % 8 }))
  const kept = ranked.slice(0, TOP_COMMUNITIES).map((c, i) => ({ ...c, color_index: i % 8 }))
  const tail = ranked.slice(TOP_COMMUNITIES)
  const tailNodes = nodes.value.filter((n) => !keptIds.value.has(n.community)).length
  return [
    ...kept,
    {
      id: OTHER,
      label: `other (${tail.length} clusters)`,
      size: tailNodes,
      color_index: 7,
    },
  ]
})

/* ---- geometry ------------------------------------------------------------
   A fixed 640-unit viewBox. Panels resize; the diagram scales with
   preserveAspectRatio rather than relaunching a layout on every resize. */
const SIZE = 640
const CX = SIZE / 2
const CY = SIZE / 2
const R_OUTER = 246
const R_INNER = 214
const GAP = 0.035 // radians of blank arc between communities

interface Placed {
  node: GraphNode
  /** Community as drawn, after long-tail collapsing — not the raw label. */
  dcom: string
  angle: number
  x: number
  y: number
  ix: number
  colorIndex: number
}

/**
 * Deterministic placement. Communities take arc length in proportion to their
 * node count, so a large community is visibly large; within a community nodes
 * are ordered by descending degree, so the hubs of each cluster all sit at the
 * same edge of their sector and can be compared across sectors.
 */
const placed = computed<Placed[]>(() => {
  const ns = nodes.value
  if (!ns.length) return []

  const byCommunity = new Map<string, GraphNode[]>()
  for (const n of ns) {
    const key = displayCommunity(n.community)
    const bucket = byCommunity.get(key)
    if (bucket) bucket.push(n)
    else byCommunity.set(key, [n])
  }

  const order = communities.value.map((c) => c.id).filter((id) => byCommunity.has(id))
  for (const key of byCommunity.keys()) if (!order.includes(key)) order.push(key)

  const colorOf = new Map<string, number>()
  communities.value.forEach((c, i) => colorOf.set(c.id, c.color_index ?? i))

  const total = ns.length
  const totalGap = GAP * order.length
  const usable = Math.PI * 2 - totalGap

  const out: Placed[] = []
  let cursor = -Math.PI / 2 + GAP / 2

  order.forEach((key, ci) => {
    const bucket = (byCommunity.get(key) ?? []).slice().sort((a, b) => b.degree - a.degree)
    const span = (bucket.length / total) * usable
    bucket.forEach((node, i) => {
      // +0.5 centres each node in its own slice rather than stacking the
      // first one exactly on the sector boundary.
      const angle = cursor + ((i + 0.5) / bucket.length) * span
      out.push({
        node,
        dcom: key,
        angle,
        x: CX + Math.cos(angle) * R_INNER,
        y: CY + Math.sin(angle) * R_INNER,
        ix: out.length,
        colorIndex: (colorOf.get(key) ?? ci) % 8,
      })
    })
    cursor += span + GAP
  })
  return out
})

const positionOf = computed(() => {
  const m = new Map<string, Placed>()
  for (const p of placed.value) m.set(p.node.id, p)
  return m
})

/** Community sector arcs, for the outer ring. */
/** Minimum arc, in radians, before a sector earns a printed label. Below this
 *  the text collides with its neighbours and the ring becomes unreadable. */
const LABEL_MIN_ARC = 0.16

const sectors = computed(() => {
  const groups = new Map<string, Placed[]>()
  for (const p of placed.value) {
    const b = groups.get(p.dcom)
    if (b) b.push(p)
    else groups.set(p.dcom, [p])
  }
  const meta = new Map(communities.value.map((c) => [c.id, c]))
  return [...groups.entries()].map(([id, ps]) => {
    const a0 = Math.min(...ps.map((p) => p.angle)) - 0.012
    const a1 = Math.max(...ps.map((p) => p.angle)) + 0.012
    const mid = (a0 + a1) / 2
    const label = meta.get(id)?.label ?? id
    return {
      id,
      label: label.length > 22 ? `${label.slice(0, 21)}…` : label,
      size: ps.length,
      colorIndex: ps[0]?.colorIndex ?? 0,
      d: arcPath(a0, a1, R_OUTER),
      showLabel: a1 - a0 >= LABEL_MIN_ARC,
      labelX: CX + Math.cos(mid) * (R_OUTER + 22),
      labelY: CY + Math.sin(mid) * (R_OUTER + 22),
      anchor: Math.cos(mid) > 0.15 ? 'start' : Math.cos(mid) < -0.15 ? 'end' : 'middle',
    }
  })
})

function arcPath(a0: number, a1: number, r: number): string {
  const x0 = CX + Math.cos(a0) * r
  const y0 = CY + Math.sin(a0) * r
  const x1 = CX + Math.cos(a1) * r
  const y1 = CY + Math.sin(a1) * r
  const large = a1 - a0 > Math.PI ? 1 : 0
  return `M${x0.toFixed(2)},${y0.toFixed(2)}A${r},${r} 0 ${large} 1 ${x1.toFixed(2)},${y1.toFixed(2)}`
}

/**
 * Chords bow toward the centre. The control point is pulled further in for
 * long-range edges, so a link across the diagram reads as one clean sweep
 * instead of a straight line cutting through every other node.
 */
const chords = computed(() => {
  const pos = positionOf.value
  const out: {
    key: string
    d: string
    source: string
    target: string
    weight: number
    colorIndex: number
    tail: boolean
  }[] = []
  for (const e of edges.value) {
    const a = pos.get(e.source)
    const b = pos.get(e.target)
    if (!a || !b) continue // endpoint was truncated away; drop, never fake it
    let delta = Math.abs(a.angle - b.angle)
    if (delta > Math.PI) delta = Math.PI * 2 - delta
    const pull = 1 - delta / Math.PI
    const mx = CX + ((a.x + b.x) / 2 - CX) * pull * 0.55
    const my = CY + ((a.y + b.y) / 2 - CY) * pull * 0.55
    out.push({
      key: `${e.source}\u0000${e.target}`,
      d: `M${a.x.toFixed(2)},${a.y.toFixed(2)}Q${mx.toFixed(2)},${my.toFixed(2)} ${b.x.toFixed(2)},${b.y.toFixed(2)}`,
      source: e.source,
      target: e.target,
      weight: e.weight,
      colorIndex: a.colorIndex,
      // Only a chord with BOTH ends inside the collapsed bucket is "tail" and
      // gets pushed into the background. A link from a named cluster into the
      // tail is still information about that cluster, so it keeps the
      // cluster's colour and its normal weight.
      tail: a.dcom === OTHER && b.dcom === OTHER,
    })
  }
  return out
})

/** The node under inspection: explicit click wins over transient hover. */
const focus = computed(() => selected.value ?? hovered.value)

const neighbours = computed(() => {
  const f = focus.value
  if (!f) return new Set<string>()
  const s = new Set<string>([f])
  for (const e of edges.value) {
    if (e.source === f) s.add(e.target)
    else if (e.target === f) s.add(e.source)
  }
  return s
})

const focusNode = computed(() => {
  const f = selected.value
  if (!f) return null
  return nodes.value.find((n) => n.id === f) ?? null
})

const focusEdges = computed(() => {
  const f = selected.value
  if (!f) return []
  return edges.value
    .filter((e) => e.source === f || e.target === f)
    .map((e) => ({ other: e.source === f ? e.target : e.source, weight: e.weight, kind: e.kind }))
    .sort((a, b) => b.weight - a.weight)
})

const labelOf = computed(() => {
  const m = new Map<string, string>()
  for (const n of nodes.value) m.set(n.id, n.label)
  return m
})

function chordState(c: { source: string; target: string }): string {
  if (activeCommunity.value) {
    const a = positionOf.value.get(c.source)
    const b = positionOf.value.get(c.target)
    const inSet = a?.dcom === activeCommunity.value || b?.dcom === activeCommunity.value
    return inSet ? 'lit' : 'mute'
  }
  if (!focus.value) return 'idle'
  return c.source === focus.value || c.target === focus.value ? 'lit' : 'mute'
}

function nodeState(p: Placed): string {
  if (activeCommunity.value) {
    return p.dcom === activeCommunity.value ? 'lit' : 'mute'
  }
  if (!focus.value) return 'idle'
  if (p.node.id === focus.value) return 'focus'
  return neighbours.value.has(p.node.id) ? 'lit' : 'mute'
}

/** Hub tier drives tick length — degree is the only size encoding here. */
function tickLength(degree: number): number {
  const max = Math.max(1, ...nodes.value.map((n) => n.degree))
  return 5 + (degree / max) * 13
}

function pickNode(p: Placed) {
  selected.value = selected.value === p.node.id ? null : p.node.id
  activeCommunity.value = null
}

function pickCommunity(id: string) {
  activeCommunity.value = activeCommunity.value === id ? null : id
  selected.value = null
}

const indexedAt = computed(() => payload.value?.generated_at ?? null)
</script>

<template>
  <div class="graph-view">
    <Panel
      label="Repo knowledge graph"
      index="10"
      :meta="indexedAt ? `indexed ${age(indexedAt)} ago` : 'not indexed'"
      class="w-full"
    >
      <LoadingState v-if="graph.loading.value && !payload" label="reading graph index" />
      <p v-else-if="graph.error.value" class="err">{{ graph.error.value }}</p>

      <template v-else-if="available">
        <div class="counts">
          <Readout label="Nodes" :value="String(stats?.n_nodes ?? 0)" tone="accent" />
          <Readout label="Edges" :value="String(stats?.n_edges ?? 0)" tone="flat" />
          <Readout label="Communities" :value="String(stats?.n_communities ?? 0)" tone="flat" />
          <Readout
            label="Rendered"
            :value="stats?.truncated ? 'capped' : 'complete'"
            :sub="stats?.truncated ? 'top nodes by degree' : 'all nodes shown'"
            :tone="stats?.truncated ? 'put' : 'flat'"
          />
        </div>
      </template>

      <div v-else class="empty">
        <p class="note">
          No graph index yet{{ payload?.reason ? ` — ${payload.reason}` : '' }}. Build one:
        </p>
        <ul class="cmds">
          <li>
            <code>python3 edge/tools/graphify_index.py</code>
            <span class="dim">incremental — skips work when nothing changed</span>
          </li>
          <li>
            <code>python3 edge/tools/graphify_index.py --force</code>
            <span class="dim">full rebuild</span>
          </li>
          <li>
            <code>python3 edge/tools/graphify_index.py --status</code>
            <span class="dim">staleness only, indexes nothing</span>
          </li>
        </ul>
      </div>
    </Panel>

    <div v-if="available" class="split">
      <Panel label="Chord map" :meta="`${placed.length} placed`" :delay="40" flush>
        <div class="stage">
          <svg
            :viewBox="`0 0 ${SIZE} ${SIZE}`"
            class="chart"
            role="img"
            aria-label="Repository knowledge graph as a chord diagram"
          >
            <g class="chords">
              <path
                v-for="c in chords"
                :key="c.key"
                :d="c.d"
                :class="['chord', chordState(c), { tail: c.tail }]"
                :style="c.tail ? undefined : { stroke: `var(--cat-${c.colorIndex + 1})` }"
                :stroke-width="0.5 + Math.min(c.weight, 4) * 0.35"
              />
            </g>

            <g class="sectors">
              <path
                v-for="s in sectors"
                :key="s.id"
                :d="s.d"
                :class="[
                  'sector',
                  {
                    on: activeCommunity === s.id,
                    off: activeCommunity && activeCommunity !== s.id,
                    tail: s.id === OTHER,
                  },
                ]"
                :style="s.id === OTHER ? undefined : { stroke: `var(--cat-${s.colorIndex + 1})` }"
                @click="pickCommunity(s.id)"
              />
              <text
                v-for="s in sectors.filter((x) => x.showLabel || activeCommunity === x.id)"
                :key="`t-${s.id}`"
                :x="s.labelX"
                :y="s.labelY"
                :text-anchor="s.anchor"
                :class="['sector-label', { on: activeCommunity === s.id }]"
              >
                {{ s.label }}
              </text>
            </g>

            <g class="nodes">
              <line
                v-for="p in placed"
                :key="p.node.id"
                :x1="CX + Math.cos(p.angle) * (R_INNER - 3)"
                :y1="CY + Math.sin(p.angle) * (R_INNER - 3)"
                :x2="CX + Math.cos(p.angle) * (R_INNER - 3 - tickLength(p.node.degree))"
                :y2="CY + Math.sin(p.angle) * (R_INNER - 3 - tickLength(p.node.degree))"
                :class="['tick', nodeState(p), { tail: p.dcom === OTHER }]"
                :style="p.dcom === OTHER ? undefined : { stroke: `var(--cat-${p.colorIndex + 1})` }"
                @mouseenter="hovered = p.node.id"
                @mouseleave="hovered = null"
                @click="pickNode(p)"
              />
            </g>

            <text v-if="focus" class="centre-label" :x="CX" :y="CY - 4" text-anchor="middle">
              {{ labelOf.get(focus) }}
            </text>
            <text v-if="focus" class="centre-sub" :x="CX" :y="CY + 14" text-anchor="middle">
              {{ neighbours.size - 1 }} link{{ neighbours.size === 2 ? '' : 's' }}
            </text>
          </svg>
        </div>
      </Panel>

      <div class="side">
        <Panel
          label="Communities"
          :meta="
            collapsed
              ? `top ${TOP_COMMUNITIES} of ${rawCommunities.length}`
              : `${communities.length}`
          "
          :delay="80"
          flush
        >
          <table class="grid">
            <thead>
              <tr>
                <th class="label">Cluster</th>
                <th class="label num">Nodes</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="(c, i) in communities"
                :key="c.id"
                class="row-click"
                :class="{ active: activeCommunity === c.id }"
                @click="pickCommunity(c.id)"
              >
                <td class="row-select-cell">
  <button type="button" class="row-select-btn" @click.stop="pickCommunity(c.id)"><span class="sr-only">Select row</span></button>
                  <span
                    class="swatch"
                    :class="{ tail: c.id === OTHER }"
                    :style="
                      c.id === OTHER
                        ? undefined
                        : { background: `var(--cat-${((c.color_index ?? i) % 8) + 1})` }
                    "
                  />
                  <span class="cname" :class="{ tail: c.id === OTHER }">{{ c.label }}</span>
                </td>
                <td class="fig num">{{ c.size }}</td>
              </tr>
            </tbody>
          </table>
        </Panel>

        <Panel
          label="Inspector"
          :meta="focusNode ? focusNode.kind : 'nothing selected'"
          :delay="120"
        >
          <template v-if="focusNode">
            <div class="insp-head">
              <span class="insp-name fig">{{ focusNode.label }}</span>
              <span v-if="focusNode.path" class="insp-path label">{{ focusNode.path }}</span>
            </div>
            <div class="insp-counts">
              <Readout label="Degree" :value="String(focusNode.degree)" tone="accent" size="sm" />
              <Readout label="Cluster" :value="focusNode.community || DASH" tone="flat" size="sm" />
            </div>
            <table v-if="focusEdges.length" class="grid links">
              <thead>
                <tr>
                  <th class="label">Linked to</th>
                  <th class="label num">W</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="e in focusEdges"
                  :key="e.other"
                  class="row-click"
                  @click="selected = e.other"
                >
                  <td class="row-select-cell cname">
  <button type="button" class="row-select-btn" @click.stop="selected = e.other"><span class="sr-only">Select row</span></button>{{ labelOf.get(e.other) ?? e.other }}</td>
                  <td class="fig num">{{ e.weight.toFixed(1) }}</td>
                </tr>
              </tbody>
            </table>
          </template>
          <p v-else class="note">
            Click a tick on the ring to inspect a node, or a sector to isolate a cluster.
          </p>
        </Panel>
      </div>
    </div>
  </div>
</template>

<style scoped>
.graph-view {
  display: flex;
  flex-direction: column;
  gap: var(--s4);
}

.counts {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--s3);
}

.split {
  display: grid;
  grid-template-columns: minmax(0, 1.45fr) minmax(280px, 0.55fr);
  gap: var(--s4);
  align-items: start;
}

.side {
  display: flex;
  flex-direction: column;
  gap: var(--s4);
  min-width: 0;
}

.stage {
  padding: var(--s3);
  display: flex;
  justify-content: center;
}

.chart {
  display: block;
  /* Sized by HEIGHT, not width. A square viewBox in a wide panel would
     otherwise be laid out at the panel's full width and run a long way below
     the fold — the diagram has to be seen whole to be read at all, since the
     whole point is comparing sectors against each other.

     56vh, measured rather than guessed: the stats panel above consumes ~285px
     before this element starts, so on a 720px-tall laptop viewport (the
     smallest this desk realistically runs at) 68vh put the bottom of the ring
     55px below the fold. */
  height: min(56vh, 560px);
  width: auto;
  max-width: 100%;
  /* Sector labels are drawn outside the viewBox radius. */
  overflow: visible;
}

/* ---- chords -------------------------------------------------------------- */
.chord {
  fill: none;
  opacity: 0.16;
  transition: opacity var(--dur-fast) var(--ease-out);
}
.chord.lit {
  opacity: 0.85;
}
.chord.mute {
  opacity: 0.04;
}

/* ---- the collapsed tail --------------------------------------------------
   107 of this repo's 118 Louvain communities are two- or three-file clusters.
   Collapsed into one bucket they hold most of the nodes, so if the tail were
   drawn in a categorical colour it would be the loudest object on screen and
   would read as the most important cluster — the exact inverse of the truth.

   The tail therefore gets no hue at all. It is drawn on the ink ramp, which
   also keeps the categorical palette honest: eight colours, eight real
   clusters, and "everything else" is visibly not one of them. This is the
   same reasoning that reserves phosphor for live state. */
.chord.tail {
  stroke: var(--ink-ghost);
  opacity: 0.05;
}
.chord.tail.lit {
  opacity: 0.4;
}

/* ---- sectors ------------------------------------------------------------- */
.sector {
  fill: none;
  stroke-width: 6;
  opacity: 0.5;
  cursor: pointer;
  transition: opacity var(--dur-fast) var(--ease-out);
}
.sector:hover,
.sector.on {
  opacity: 1;
}
.sector.off {
  opacity: 0.14;
}
.sector.tail {
  stroke: var(--rule-hi);
  stroke-width: 3;
  opacity: 0.7;
}

.sector-label {
  font-family: var(--font-display);
  font-size: 10px;
  letter-spacing: var(--track-label);
  text-transform: uppercase;
  fill: var(--ink-faint);
  pointer-events: none;
}
.sector-label.on {
  fill: var(--ink);
}

/* ---- node ticks ---------------------------------------------------------- */
.tick {
  stroke-width: 2;
  opacity: 0.55;
  cursor: pointer;
  transition: opacity var(--dur-fast) var(--ease-out);
}
.tick:hover {
  opacity: 1;
}
.tick.lit {
  opacity: 1;
}
.tick.mute {
  opacity: 0.12;
}
.tick.tail {
  stroke: var(--ink-ghost);
  opacity: 0.3;
  stroke-width: 1.5;
}
.tick.tail:hover {
  opacity: 1;
}
.tick.focus {
  stroke: var(--phosphor) !important;
  stroke-width: 3;
  opacity: 1;
}

.centre-label {
  font-family: var(--font-data);
  font-size: 13px;
  fill: var(--ink);
  pointer-events: none;
}
.centre-sub {
  font-family: var(--font-display);
  font-size: var(--t-nano);
  letter-spacing: var(--track-label);
  text-transform: uppercase;
  fill: var(--ink-faint);
  pointer-events: none;
}

/* ---- side panels --------------------------------------------------------- */
.row-click {
  cursor: pointer;
}
.row-click:hover td {
  background: var(--panel-hi);
}
.row-click.active td {
  background: var(--phosphor-glow);
}

.swatch {
  display: inline-block;
  width: 8px;
  height: 8px;
  margin-right: var(--s2);
  vertical-align: baseline;
}
/* Hollow, not filled — the tail is an aggregate, not a cluster. */
.swatch.tail {
  background: none;
  border: var(--hair) solid var(--ink-ghost);
}
.cname.tail {
  color: var(--ink-faint);
}

.cname {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 15rem;
  display: inline-block;
  vertical-align: bottom;
}

.insp-head {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-bottom: var(--s3);
}
.insp-name {
  color: var(--ink);
  font-weight: 500;
  word-break: break-word;
}
.insp-path {
  color: var(--ink-faint);
  text-transform: none;
  letter-spacing: 0;
  font-family: var(--font-data);
}
.insp-counts {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--s3);
  margin-bottom: var(--s3);
}
.links {
  margin: 0 calc(-1 * var(--s4));
}

.empty {
  padding-top: var(--s2);
}
.cmds {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: var(--s2);
  margin-top: var(--s3);
}
.cmds li {
  display: flex;
  flex-wrap: wrap;
  gap: var(--s3);
  align-items: baseline;
}
.cmds code {
  font-family: var(--font-data);
  font-size: var(--t-tiny);
  padding: 2px var(--s1);
  background: var(--panel-raise);
  color: var(--ink-soft);
}

.note {
  font-size: var(--t-small);
  color: var(--ink-dim);
}
.err {
  font-size: var(--t-small);
  color: var(--short);
}
.dim {
  color: var(--ink-faint);
  font-size: var(--t-tiny);
}

@media (max-width: 1100px) {
  .split {
    grid-template-columns: 1fr;
  }
  .counts {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
