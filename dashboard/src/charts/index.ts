/**
 * Dependency-free SVG charting primitives: scales, path-string builders,
 * and pure return/risk statistics. Re-exports everything from the three
 * modules so consumers can `import { ... } from '@/charts'` without
 * caring which file a given symbol lives in.
 */

export * from './scale'
export * from './path'
export * from './stats'
