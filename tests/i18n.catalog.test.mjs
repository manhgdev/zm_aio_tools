import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const catalog = JSON.parse(await readFile(new URL('../frontend/src/app/ui.en.json', import.meta.url), 'utf8'))

test('English catalog covers Configuration labels', () => {
  const expected = {
    'Thiết lập': 'Settings',
    'API dịch': 'Translation API',
    'Sẵn sàng': 'Ready',
    'Kiểm tra lại': 'Check again',
    'Bắt đầu': 'Start',
    '+ Thêm key': '+ Add key',
    'đoạn thoại': 'speech segments',
    'Sẵn sàng render.': 'Ready to render.',
    'Mẹo:': 'Tip:',
    'Bạn có thể dán link kênh, playlist hoặc nhiều link.': 'You can paste a channel link, playlist, or multiple links.',
    'Xóa lời': 'Remove vocals',
    'Xóa lời… đang tách': 'Removing vocals…',
    'Cài Demucs…': 'Installing Demucs…',
    'Cài Demucs CUDA': 'Install Demucs (CUDA)',
    'Đã cài thành công': 'Installed successfully',
  }
  for (const [vietnamese, english] of Object.entries(expected)) {
    assert.equal(catalog[vietnamese], english, vietnamese)
  }
})

test('English catalog has no empty entries', () => {
  const missing = Object.entries(catalog).filter(([, english]) => !String(english).trim())
  assert.deepEqual(missing, [])
})

test('interface locale is persisted through the app API', async () => {
  const [app, api, index] = await Promise.all([
    readFile(new URL('../frontend/src/app/App.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../frontend/src/features/project/project.api.ts', import.meta.url), 'utf8'),
    readFile(new URL('../frontend/index.html', import.meta.url), 'utf8'),
  ])
  assert.match(app, /getLocalePreference\(\)/)
  assert.match(app, /saveLocalePreference\(nextLocale\)/)
  assert.match(api, /ui-preferences/)
  assert.match(index, /ui-preferences/)
  assert.match(index, /localStorage\.setItem/)
})

test('English catalog covers interrupted TTS and Log UI text', () => {
  const expected = [
    'Lỗi job (Dịch / Lồng tiếng / Xuất), warm-models, crash hook. Copy gửi AI để sửa.',
    'Tiêu đề / tên',
    'Chưa có lịch sử — tạo giọng nói để bắt đầu',
    'Hoàn thành',
  ]
  for (const vietnamese of expected) {
    assert.notEqual(catalog[vietnamese], undefined, vietnamese)
    assert.notEqual(catalog[vietnamese], vietnamese, vietnamese)
  }
})

test('English catalog covers Review Phim and Batch queue', () => {
  const expected = {
    'Review Phim': 'Movie Review',
    'Clone Video và Review Phim': 'Clone Video and Movie Review',
    'Dự án của bạn': 'Your projects',
    'Tạo dự án mới': 'Create new project',
    'Tạo & Chạy': 'Create & Run',
    'Lưu nháp': 'Save draft',
    'Xóa cache': 'Clear cache',
    'Đã xóa cache': 'Cache cleared',
    'Xóa cache nhận dạng và kịch bản của video này. Video nguồn không bao giờ bị xóa.': 'Clear this video’s transcript and script cache. The source video is never deleted.',
    'Lần chạy sau sẽ nhận dạng và viết kịch bản lại.': 'The next run will re-transcribe and rewrite the script.',
    'Hủy': 'Cancel',
    'Đang xóa…': 'Deleting…',
    'Phân đoạn tích lũy': 'Cumulative segments',
    'Độ dài video review (phút)': 'Review length (minutes)',
    'Ngôn ngữ gốc': 'Original language',
    'Ngôn ngữ thoại': 'Spoken language',
    'Ngôn ngữ gốc là tiếng phim (Whisper / phụ đề nhúng). Ngôn ngữ thoại là lời kể TTS và caption.': 'Original language is the film (Whisper / embedded subs). Spoken language is the TTS narration and captions.',
    'Một video duy nhất — không chia thành nhiều phần.': 'One video — not split into parts.',
    'Bộ phong cách lời kể': 'Narration style packs',
    'Tiến độ phân đoạn': 'Segment progress',
    'Tải phần này': 'Download this part',
    'Xem trước': 'Preview',
    'Xoá': 'Delete',
    'Render lại': 'Render again',
    'Hàng loạt': 'Batch',
    'Thêm vào hàng đợi': 'Add to queue',
    'Hàng đợi chung': 'Unified queue',
    'Mỗi tab hiển thị hàng đợi riêng.': 'Each tab shows its own queue.',
    'Hàng đợi Clone hàng loạt': 'Clone batch queue',
    'Hàng đợi Review hàng loạt': 'Review batch queue',
    'Thao tác': 'Operation',
    'Mở Editor': 'Open Editor',
    'Xóa logo / watermark': 'Remove logo / watermark',
    'Tự nhận diện logo/watermark chữ': 'Automatic text-logo detection',
    'Quét mọi nhãn chữ ổn định ở góc video. Veo, Grok và Kling chỉ là ví dụ; logo thuần hình không có chữ cần xử lý thủ công.': 'Scans any stable text label at video edges. Veo, Grok, and Kling are examples; image-only logos need manual treatment.',
  }
  for (const [vietnamese, english] of Object.entries(expected)) {
    assert.equal(catalog[vietnamese], english, vietnamese)
  }
})

test('English catalog covers Live Preview empty page', () => {
  const expected = {
    'Chưa có video để xem trước': 'No video to preview yet',
    'Mở hoặc tải video ở Clone Video rồi quay lại đây để chỉnh sửa theo timeline.': 'Open or upload a video in Clone Video, then return here to edit it on the timeline.',
    'Đi tới Clone Video': 'Go to Clone Video',
  }
  for (const [vietnamese, english] of Object.entries(expected)) {
    assert.equal(catalog[vietnamese], english, vietnamese)
  }
})

test('SRT exporter CapCut translation UI is bilingual', () => {
  const expected = {
    'Nhận dạng & dịch': 'Recognition & translation',
    'CapCut dịch (không dùng Whisper)': 'CapCut Translate (no Whisper)',
    'CapCut nhận dạng và dịch trực tiếp trên cloud, rồi trả SRT có timecode. Không chạy Whisper hoặc API dịch khác.': 'CapCut recognizes and translates in the cloud, then returns a timed SRT. Whisper and other translation APIs are not used.',
    'CapCut dịch & tải SRT': 'Translate with CapCut & download SRT',
  }
  for (const [vietnamese, english] of Object.entries(expected)) assert.equal(catalog[vietnamese], english, vietnamese)
})

test('Review CapCut recognition UI is bilingual', () => {
  const expected = {
    'Nhận dạng': 'Recognition',
    'CapCut cloud': 'CapCut cloud',
    'Gửi video lên CapCut để nhận dạng; không chạy Whisper.': 'Uploads the video to CapCut for recognition; Whisper is not used.',
    'Cần mạng. Transcript được cache riêng theo CapCut để không lẫn với Whisper.': 'Requires internet. The transcript is cached separately from Whisper.',
  }
  for (const [vietnamese, english] of Object.entries(expected)) assert.equal(catalog[vietnamese], english, vietnamese)
})

test('Clone CapCut recognition and translation UI is bilingual', () => {
  const expected = {
    'Giọng nói (CapCut cloud)': 'Speech (CapCut cloud)',
    'CapCut cloud': 'CapCut cloud',
    'CapCut nhận dạng cloud — chạy Dịch toàn bộ': 'CapCut cloud recognition — run Full Translation',
  }
  for (const [vietnamese, english] of Object.entries(expected)) assert.equal(catalog[vietnamese], english, vietnamese)
})

test('Drawing tab uses bilingual localized UI', async () => {
  const source = await readFile(new URL('../frontend/src/pages/DrawingPage.tsx', import.meta.url), 'utf8')
  assert.match(source, /localize\(locale,/)
  assert.match(source, /Image → Drawing Video/)
  assert.match(source, /Tạo video vẽ tay/)
})

test('Batch Drawing queue uses bilingual localized UI', async () => {
  const source = await readFile(new URL('../frontend/src/pages/BatchPage.tsx', import.meta.url), 'utf8')
  assert.match(source, /Vẽ tay hàng loạt/)
  assert.match(source, /Drawing batch/)
  assert.match(source, /Xem trước/)
  assert.match(source, /Preview/)
})

test('Batch file selection creates localized queue jobs immediately', async () => {
  const source = await readFile(new URL('../frontend/src/pages/BatchPage.tsx', import.meta.url), 'utf8')
  assert.match(source, /create jobs in the queue below, then press Run/)
  assert.match(source, /It only runs after you press Run/)
  assert.match(source, /Run \$\{readyQueueJobs\.length\} jobs/)
})

test('License gate is bilingual and accepts keyboard focus', async () => {
  const [license, app] = await Promise.all([
    readFile(new URL('../frontend/src/features/license/LicensePage.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../frontend/src/app/App.tsx', import.meta.url), 'utf8'),
  ])
  assert.match(license, /localize\(locale,/)
  assert.match(license, /autoFocus/)
  assert.match(license, /inputRef\.current\?\.focus/)
  assert.match(app, /app-license-gate/)
  assert.match(app, /appMode === 'license' && !licenseBlocked/)
})

test('ZM AIO TOOL branding keeps the SRT logo label bilingual', async () => {
  const [header, license, srt] = await Promise.all([
    readFile(new URL('../frontend/src/shared/components/Header.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../frontend/src/features/license/LicensePage.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../frontend/src/pages/SrtImagePage.tsx', import.meta.url), 'utf8'),
  ])
  assert.match(header, /ZM AIO TOOL/)
  assert.match(license, /ZM AIO TOOL/)
  assert.match(srt, /Logo \/ Watermark ZM AIO TOOL/)
  assert.match(srt, /ZM AIO TOOL logo \/ watermark/)
})
