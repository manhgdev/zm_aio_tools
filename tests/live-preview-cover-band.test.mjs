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
