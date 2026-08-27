import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'

test('Flow retains a separate selected model for image and video tabs', async () => {
  const page = await readFile(new URL('../frontend/src/pages/FlowPage.tsx', import.meta.url), 'utf8')

  assert.match(page, /imageModel: "Nano Banana 2"/)
  assert.match(page, /videoModel: "Veo 3\.1 - Fast"/)
  assert.match(page, /function settingsForCreateKind\(/)
  assert.match(page, /const selectCreateKind = \(kind: CreateKind\) => \{\s*setCreateKind\(kind\);\s*setSettings\(\(current\) => settingsForCreateKind\(current, kind\)\);/)
  assert.match(page, /setSettings\(\(current\) => settingsWithSelectedModel\(current, createKind, model\)\)/)
  assert.doesNotMatch(page, /Automatically enhance prompt/)
  assert.doesNotMatch(page, /flow-enhance/)
  assert.doesNotMatch(page, /Chọn thư mục tải xuống trước để Flow lưu vào ZM_AIO_TOOL\/flow\./)
  assert.match(page, /function downloadFlowOutput\(/)
  assert.match(page, /downloadFlowOutput\(item\.job, item\.outputIndex\)/)
})
