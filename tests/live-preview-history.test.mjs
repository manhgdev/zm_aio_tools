import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'
import vm from 'node:vm'

async function loadEditorHistory() {
  const source = await readFile(new URL('../frontend/src/features/editor/lib/editorHistory.ts', import.meta.url), 'utf8')
  const compiled = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText
  const sandbox = { exports: {}, structuredClone }
  vm.runInNewContext(compiled, sandbox)
  return sandbox.exports
}

test('cloneSnap deep clones nested segment bbox, captionBox, settings, and overlays', async () => {
  const { cloneSnap } = await loadEditorHistory()

  const originalSnap = {
    segments: [
      {
        id: 'seg-1',
        start: 0,
        end: 2,
        text: 'hello',
        translation: 'xin chào',
        bbox: { x: 10, y: 20, w: 100, h: 30 },
        captionBox: { x: 10, y: 20, w: 100, h: 30 },
        captionLayout: { x: 10, y: 20, w: 100, h: 30, lines: ['xin chào'], fontSize: 24 },
        words: [{ text: 'hello', start: 0, end: 1 }],
      },
    ],
    overlays: [
      {
        id: 'ov-1',
        x: 50,
        y: 60,
        w: 200,
        h: 80,
        kind: 'effect',
        maskStyle: 'blur',
        maskColor: '#ffffff',
        maskOpacity: 0.8,
      },
    ],
    settings: {
      coverMaskStyle: 'blur',
      coverMaskColor: '#000000',
      coverMaskOpacity: 0.9,
      blurBandMode: 'off',
      subtitleFontSize: 24,
    },
    bookmarks: [1, 2],
    selectedId: 'seg-1',
    selectedOverlayId: 'ov-1',
    trackFocus: 'caption',
    videoClips: [{ id: 'vc-1', start: 0, end: 5 }],
    bgClips: [],
    selectedMediaId: null,
    bakedSpeed: 1,
    workClipSec: 0,
    mediaDuration: 10,
  }

  const snap = cloneSnap(originalSnap)

  // Mutate original objects
  originalSnap.segments[0].bbox.x = 999
  originalSnap.segments[0].captionBox.y = 888
  originalSnap.overlays[0].maskStyle = 'mosaic'
  originalSnap.settings.coverMaskStyle = 'solid'
  originalSnap.settings.blurBandMode = 'auto'

  // Cloned snap should be completely unaffected
  assert.equal(snap.segments[0].bbox.x, 10)
  assert.equal(snap.segments[0].captionBox.y, 20)
  assert.equal(snap.overlays[0].maskStyle, 'blur')
  assert.equal(snap.settings.coverMaskStyle, 'blur')
  assert.equal(snap.settings.blurBandMode, 'off')
})

test('LivePreviewEditor routes settings through editSettings to capture undo/redo history', async () => {
  const source = await readFile(new URL('../frontend/src/features/editor/LivePreviewEditor.tsx', import.meta.url), 'utf8')

  // Properties and project panels must use editSettings, not bare onSettings
  assert.match(source, /<EditorPropertiesPanel[\s\S]*?onSettings=\{editSettings\}/)
  assert.doesNotMatch(source, /<EditorPropertiesPanel[\s\S]*?onSettings=\{onSettings\}/)

  // applySnap must clear drafts and layout cache
  assert.match(source, /function applySnap\(snap: EditorSnap\) \{[\s\S]*?layoutCacheRef\.current = \{\}/)
  assert.match(source, /function applySnap\(snap: EditorSnap\) \{[\s\S]*?setBlurBandDraft\(null\)/)
  assert.match(source, /function applySnap\(snap: EditorSnap\) \{[\s\S]*?overlayDragDraftRef\.current = null/)

  // commitCoverBox updates coverBox
  assert.match(source, /commitCoverBox[\s\S]*?\.\.\.\(selected\.coverBox \? \{ coverBox: norm \} : \{\}\)/)

  // resetOcrRegion resets bbox, coverBox, and captionBox
  assert.match(source, /clearBbox[\s\S]*?coverBox: null/)
  assert.match(source, /clearBbox[\s\S]*?captionBox: null/)

  // blur band drag records history
  assert.match(source, /data-blur-band[\s\S]*?pushHistoryOnce\(histGate\)[\s\S]*?editSettings\(\{[\s\S]*?blurBandMode: 'manual'/)
})
