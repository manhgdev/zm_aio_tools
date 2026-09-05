import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'
import vm from 'node:vm'

async function loadTranslatorOptions() {
  const source = await readFile(new URL('../frontend/src/app/appSettings.ts', import.meta.url), 'utf8')
  const standalone = source.replace(/^import[^\n]+\n/gm, '')
  const compiled = ts.transpileModule(standalone, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText
  const sandbox = { exports: {} }
  vm.runInNewContext(compiled, sandbox)
  return sandbox.exports.translatorOptions
}

test('translator dropdown uses each provider once with a display label', async () => {
  const translatorOptions = await loadTranslatorOptions()
  const options = translatorOptions('whisper')

  assert.equal(options.length, new Set(options.map((option) => option.id)).size)
  assert.deepEqual(
    Array.from(options.slice(0, 3), (option) => ({ id: option.id, label: option.label })),
    [
      { id: 'google', label: 'Google Translate' },
      { id: 'mymemory', label: 'MyMemory' },
      { id: 'tiktok', label: 'TikTok Translate' },
    ],
  )
})
