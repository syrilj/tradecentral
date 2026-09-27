const major = Number(process.versions.node.split('.')[0])

if (!Number.isFinite(major) || major < 18) {
  console.error(
    `Node 18+ is required for this dashboard (found ${process.version}). ` +
      'Select a supported runtime before running Vite or Vitest.',
  )
  process.exit(1)
}
