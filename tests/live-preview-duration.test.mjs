import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'
import vm from 'node:vm'

async function loadResolveTimelineDuration() {
  const source = await readFile(new URL('../frontend/src/features/editor/lib/mediaClips.ts', import.meta.url), 'utf8')
  const standalone = source.replace(/^import[^\n]+\n/gm, '')
  const compiled = ts.transpileModule(standalone, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText
  const sandbox = { exports: {} }
  vm.runInNewContext(compiled, sandbox)
  return sandbox.exports.resolveTimelineDuration
}

test('full Live Preview expands its default Video clip after a 20-second preview', async () => {
  const resolveTimelineDuration = await loadResolveTimelineDuration()

  assert.equal(resolveTimelineDuration({
    sourceDuration: 310.752993,
    lastSegmentEnd: 310.48,
    videoTrackEnd: 20,
    previousMediaDuration: 20,
  }), 310.752993)
})

test('full Live Preview preserves an actual right trim', async () => {
  const resolveTimelineDuration = await loadResolveTimelineDuration()

  assert.equal(resolveTimelineDuration({
    sourceDuration: 310.752993,
    lastSegmentEnd: 310.48,
    videoTrackEnd: 18,
    previousMediaDuration: 20,
  }), 18)
})
