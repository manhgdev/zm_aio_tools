import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'
import vm from 'node:vm'

async function loadExpandOverlappingSubtitleBand() {
  const source = await readFile(new URL('../frontend/src/features/editor/lib/coverBox.ts', import.meta.url), 'utf8')
  const standalone = source.replace(/^import[^\n]+\n/gm, '')
  const compiled = ts.transpileModule(standalone, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText
  const sandbox = { exports: {} }
  vm.runInNewContext(compiled, sandbox)
  return sandbox.exports.expandOverlappingSubtitleBand
}

async function loadCoverBoxHelpers() {
  const source = await readFile(new URL('../frontend/src/features/editor/lib/coverBox.ts', import.meta.url), 'utf8')
  const standalone = source.replace(/^import[^\n]+\n/gm, '')
  const compiled = ts.transpileModule(standalone, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText
  const sandbox = { exports: {} }
  vm.runInNewContext(compiled, sandbox)
  return sandbox.exports
}

test('Live Preview expands overlapping one-row OCR boxes into a two-row subtitle band', async () => {
  const expandOverlappingSubtitleBand = await loadExpandOverlappingSubtitleBand()
  const band = expandOverlappingSubtitleBand([
    { x: 0, y: 1411, w: 1080, h: 90 },
    { x: 180, y: 1411, w: 714, h: 90 },
  ], 1080, 1920, 48)

  assert.ok(band)
  assert.deepEqual({ ...band }, {
    x: 0,
    y: 1334,
    w: 1080,
    h: 167,
  })
})

test('Live Preview unions all rows and keeps a small safety margin', async () => {
  const expandOverlappingSubtitleBand = await loadExpandOverlappingSubtitleBand()
  const band = expandOverlappingSubtitleBand([
    { x: 240, y: 1200, w: 600, h: 50 },
    { x: 220, y: 1255, w: 640, h: 50 },
    { x: 250, y: 1310, w: 580, h: 50 },
  ], 1080, 1920, 48)

  assert.ok(band)
  assert.ok(band.y < 1200)
  assert.ok(band.y + band.h > 1360)
  assert.ok(band.x <= 220)
  assert.ok(band.x + band.w >= 860)
})

test('Live Preview renders inherited bbox while reserving verified bbox for row expansion', async () => {
  const source = await readFile(new URL('../frontend/src/features/editor/LivePreviewEditor.tsx', import.meta.url), 'utf8')

  assert.match(source, /const hasPreviewCoverBbox = .*Boolean\(segment\?\.bbox\)/)
  assert.match(source, /const hasVerifiedCoverBbox = .*hasPreviewCoverBbox\(segment\)/)
  assert.match(source, /return hasPreviewCoverBbox\(s\)/)
  assert.match(source, /getCachedPreviewLayout\(s, s\.id === selected\?\.id/)
  assert.doesNotMatch(source, /layoutSegment = overCoverMode/)
})

test('caption cover expands from the first row through the last rendered row', async () => {
  const { expandCoverForCaptionLines } = await loadCoverBoxHelpers()
  const cover = expandCoverForCaptionLines(
    { x: 60, y: 450, w: 270, h: 32 },
    2,
    24,
    360,
    640,
  )

  assert.ok(cover.y < 450)
  assert.ok(cover.y + cover.h > 482)
  assert.ok(cover.h >= Math.ceil(2 * 24 * 1.1 + 8))
  assert.ok(Math.abs(cover.y + cover.h / 2 - 466) <= 0.5)
})
