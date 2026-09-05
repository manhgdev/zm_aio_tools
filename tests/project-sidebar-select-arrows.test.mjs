import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

test('macOS sidebar uses one centered select arrow for fields, OCR mode, and workers', async () => {
  const css = await readFile(
    new URL('../frontend/src/features/project/ProjectSidebar.css', import.meta.url),
    'utf8',
  )

  assert.match(
    css,
    /\.platform-macos \.sidebar \.field select,\s*\.platform-macos \.sidebar \.blur-zone-select,\s*\.platform-macos \.sidebar \.workers-setting select/,
  )
  assert.match(css, /appearance: none;/)
  assert.match(css, /background-position:\s*calc\(100% - 16px\) 50%,\s*calc\(100% - 12px\) 50%;/)
})
