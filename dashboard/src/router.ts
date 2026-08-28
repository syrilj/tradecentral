import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { isLocalAuthMode } from './auth'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    name: 'landing',
    component: () => import('@/views/LandingView.vue'),
    meta: { title: 'About', public: true },
  },
  {
    path: '/about',
    redirect: { name: 'landing' },
  },
  {
    path: '/auth/:pathMatch(.*)*',
    name: 'auth',
    component: () => import('@/views/AuthView.vue'),
    meta: { title: 'Operator access', public: true },
  },
  {
    path: '/desk',
    name: 'desk',
    component: () => import('@/views/DeskView.vue'),
    meta: { title: 'Desk', index: '01' },
  },
  {
    path: '/plays',
    name: 'plays',
    component: () => import('@/views/PlaysView.vue'),
    meta: { title: 'Plays', index: '02' },
  },
  {
    path: '/market',
    name: 'market',
    component: () => import('@/views/MarketView.vue'),
    meta: { title: 'Market', index: '02' },
  },
  {
    path: '/sectors',
    name: 'sectors',
    component: () => import('@/views/SectorsView.vue'),
    meta: { title: 'Sectors', index: '03' },
  },
  {
    path: '/sentiment',
    name: 'sentiment',
    component: () => import('@/views/SentimentView.vue'),
    meta: { title: 'Pulse', index: '04' },
  },
  {
    path: '/macro',
    name: 'macro',
    component: () => import('@/views/MacroView.vue'),
    meta: { title: 'Macro', index: '04' },
  },
  /* Legacy path — structure + outliers now live on /sentiment */
  {
    path: '/anomalies',
    name: 'anomalies',
    redirect: (to) => ({
      name: 'sentiment',
      query: { ...to.query, tab: 'outliers' },
    }),
  },
  {
    path: '/options',
    name: 'options',
    component: () => import('@/views/OptionsView.vue'),
    meta: { title: 'Options Drift', index: '05' },
  },
  {
    path: '/drift',
    name: 'drift',
    component: () => import('@/views/DriftView.vue'),
    meta: { title: 'Drift', index: '05' },
  },
  {
    path: '/flow',
    name: 'flow',
    component: () => import('@/views/FlowView.vue'),
    meta: { title: 'Market Flow', index: '06' },
  },
  {
    path: '/absorption',
    name: 'absorption',
    component: () => import('@/views/AbsorptionView.vue'),
    meta: { title: 'Absorption', index: '07' },
  },
  {
    path: '/livestack',
    name: 'livestack',
    component: () => import('@/views/LiveStackView.vue'),
    meta: { title: 'Live Stack', index: '07' },
  },
  {
    path: '/chain',
    name: 'chain',
    component: () => import('@/views/ChainView.vue'),
    meta: { title: 'Supply Chain', index: '05' },
  },
  {
    path: '/gates',
    name: 'gates',
    component: () => import('@/views/GatesView.vue'),
    meta: { title: 'Gates', index: '06' },
  },
  {
    path: '/cloud',
    name: 'cloud',
    component: () => import('@/views/CloudView.vue'),
    meta: { title: 'Cloud', index: '07' },
  },
  {
    path: '/evolution',
    name: 'evolution',
    component: () => import('@/views/EvolutionView.vue'),
    meta: { title: 'Evolution', index: '08' },
  },
  {
    path: '/research',
    name: 'research',
    component: () => import('@/views/ResearchView.vue'),
    meta: { title: 'Research', index: '09' },
  },
  {
    path: '/quantitative-research',
    name: 'quantitative-research',
    redirect: (to) => ({
      name: 'market',
      query: {
        ...to.query,
        tab: 'financials',
        highlight: 'model-forecast',
        symbol: typeof to.query.symbol === 'string' && to.query.symbol ? to.query.symbol : 'ASTS',
      },
    }),
    meta: { title: 'Quantitative Research' },
  },
  {
    path: '/graph',
    name: 'graph',
    component: () => import('@/views/GraphView.vue'),
    meta: { title: 'Graph', index: '10' },
  },
  {
    path: '/adaptive',
    name: 'adaptive',
    component: () => import('@/views/AdaptiveView.vue'),
    meta: { title: 'Live Blend', index: '11' },
  },
  {
    path: '/fintel',
    name: 'fintel',
    component: () => import('@/views/FintelView.vue'),
    meta: { title: 'Fintel', index: '12' },
  },
  {
    path: '/insiders',
    name: 'insiders',
    redirect: (to) => ({
      name: 'market',
      query: { ...to.query, tab: 'insiders' },
    }),
    meta: { title: 'Insiders', index: '15' },
  },
  {
    path: '/changepoints',
    name: 'changepoints',
    component: () => import('@/views/ChangepointsView.vue'),
    meta: { title: 'Breaks', index: '13' },
  },
  {
    path: '/kalman',
    name: 'kalman',
    component: () => import('@/views/KalmanView.vue'),
    meta: { title: 'Kalman', index: '14' },
  },
  {
    path: '/momentum',
    name: 'momentum',
    component: () => import('@/views/MomentumView.vue'),
    meta: { title: 'Momentum', index: '14' },
  },
  {
    path: '/suggest',
    name: 'suggest',
    component: () => import('@/views/SuggestView.vue'),
    meta: { title: 'Setups', index: '05' },
  },
  {
    path: '/calculator',
    name: 'calculator',
    component: () => import('@/views/CalculatorView.vue'),
    meta: { title: 'Calculator', index: '05' },
  },
  {
    path: '/flow-state',
    name: 'flowstate',
    redirect: (to) => ({
      name: 'flow',
      query: { ...to.query, tab: 'states' },
    }),
  },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 }),
})

export function safeRedirect(value: unknown, fallback = '/flow'): string {
  if (typeof value !== 'string') return fallback
  if (!value.startsWith('/') || value.startsWith('//') || value.startsWith('/auth')) return fallback
  return value
}

/*
 * EDGE_AUTH_MODE=local never installs the Clerk plugin (see main.ts), so
 * AuthView's useClerk()/<SignIn> would throw and render a blank screen. There
 * is no sign-in step in local mode — the operator is already the session — so
 * send /auth straight to the requested desk surface instead.
 */
router.beforeEach((to) => {
  if (to.name === 'auth' && isLocalAuthMode()) {
    return safeRedirect(to.query.redirect, '/flow')
  }
  return true
})

router.afterEach((to) => {
  const t = to.meta.title as string | undefined
  const symRaw = to.query.symbol || to.query.setup
  const sym = typeof symRaw === 'string' && symRaw ? symRaw.trim().toUpperCase() : ''
  if (t) {
    document.title = sym ? `TradeCentral · ${t} (${sym})` : `TradeCentral · ${t}`
  } else {
    document.title = 'TradeCentral · Research instrument'
  }
})
