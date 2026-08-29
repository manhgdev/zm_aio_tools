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

test('desktop update check uses bilingual in-app dialog and platform updater API', async () => {
  const [config, api, system] = await Promise.all([
    readFile(new URL('../frontend/src/features/configuration/ConfigModal.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../frontend/src/features/project/project.api.ts', import.meta.url), 'utf8'),
    readFile(new URL('../backend/api/routes/system.py', import.meta.url), 'utf8'),
  ])
  assert.match(config, /Kiểm tra cập nhật/)
  assert.match(config, /Check for updates/)
  assert.match(config, /cfg-update-dialog/)
  assert.match(config, /cfg-update-layer/)
  assert.match(config, /Đã là phiên bản mới nhất/)
  assert.match(config, /You are up to date/)
  assert.match(config, /Tải cập nhật/)
  assert.match(config, /Download update/)
  assert.match(config, /aria-valuenow=\{updateProgress\}/)
  assert.match(config, /\{updateProgress\}%/)
  assert.match(api, /checkAppUpdate/)
  assert.match(api, /installAppUpdate/)
  assert.match(api, /getAppUpdateStatus/)
  assert.match(api, /applyAppUpdate/)
  assert.match(system, /\/api\/system\/update\/check/)
  assert.match(system, /\/api\/system\/update\/install/)
  assert.match(system, /\/api\/system\/update\/status/)
  assert.match(system, /_desktop_platform_asset_suffix/)
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

test('desktop persistence includes Flow settings across random localhost ports', async () => {
  const index = await readFile(new URL('../frontend/index.html', import.meta.url), 'utf8')
  assert.match(index, /key\.indexOf\('zm-'\) === 0/)
  assert.match(index, /GET', '\/api\/ui-preferences'/)
  assert.match(index, /PUT',/)
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

test('TTS Engine filter includes a bilingual All option', async () => {
  const source = await readFile(new URL('../frontend/src/features/tts/TtsStudio.tsx', import.meta.url), 'utf8')
  assert.match(source, /<option value="all">\{t\('Tất cả', 'All'\)\}<\/option>/)
})

test('TTS voice list pagination is bilingual', async () => {
  const source = await readFile(new URL('../frontend/src/features/tts/TtsStudio.tsx', import.meta.url), 'utf8')
  assert.match(source, /t\('Mỗi trang', 'Per page'\)/)
  assert.match(source, /t\('Phân trang danh sách giọng', 'Voice list pagination'\)/)
  assert.match(source, /t\('Trước', 'Previous'\)/)
  assert.match(source, /t\('Sau', 'Next'\)/)
})

test('TTS output actions distinguish desktop open from web download', async () => {
  const source = await readFile(new URL('../frontend/src/features/tts/TtsStudio.tsx', import.meta.url), 'utf8')
  const historySource = await readFile(new URL('../frontend/src/features/tts/TtsHistoryPanel.tsx', import.meta.url), 'utf8')
  assert.match(source, /t\('Mở thư mục audio \(WAV\)', 'Open audio folder \(WAV\)'\)/)
  assert.match(source, /t\('Tải audio \(WAV\)', 'Download audio \(WAV\)'\)/)
  assert.match(historySource, /isDesktopApp\s*\? onReveal\(h\.id, 'wav'\)/)
  assert.match(historySource, /t\('Mở kết quả — chọn định dạng', 'Open output — choose format'\)/)
  assert.match(historySource, /t\('Tải xuống — chọn định dạng', 'Download — choose format'\)/)
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

test('Render list is bilingual and covers Clone plus Review', async () => {
  const [page, messages] = await Promise.all([
    readFile(new URL('../frontend/src/pages/RendersPage.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../frontend/src/app/i18n.tsx', import.meta.url), 'utf8'),
  ])
  assert.match(page, /List render/)
  assert.match(page, /Render list/)
  assert.match(page, /All media exported from Clone, Review, and tools/)
  assert.match(messages, /'nav\.renders': \{ vi: 'List render', en: 'Render list' \}/)
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

test('Review quality-first duration and scene-indexing copy are bilingual', async () => {
  const [panel, i18n, batch, film] = await Promise.all([
    readFile(new URL('../frontend/src/features/studio/ReviewSettingsPanel.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../frontend/src/app/i18n.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../frontend/src/pages/BatchPage.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../frontend/src/pages/FilmPage.tsx', import.meta.url), 'utf8'),
  ])
  assert.match(panel, /Thời lượng review mong muốn/)
  assert.match(panel, /Preferred review length/)
  assert.match(panel, /không kéo dài bằng lời hoặc cảnh đệm/)
  assert.match(panel, /Review · AI Cloud/)
  assert.match(panel, /Review · Cloud AI/)
  assert.match(panel, /không gửi khung hình/)
  assert.match(batch, /reviewProvider: reviewSettings\.reviewProvider/)
  assert.match(i18n, /Indexing scenes and attaching transcript/)
  assert.match(i18n, /Summarizing speech beats/)
  assert.match(i18n, /Gemini rejected this request/)
  assert.match(film, /REVIEW_CLOUD_GEMINI_HTTP_403/)
})

test('CapCut pipeline progress logs are localized to English', async () => {
  const source = await readFile(new URL('../frontend/src/app/i18n.tsx', import.meta.url), 'utf8')
  assert.match(source, /recognizing and translating · \$1%/)
  assert.match(source, /CapCut: completed · \$1%/)
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
  assert.match(source, /Đường đi nét/)
  assert.match(source, /Stroke route/)
  assert.match(source, /Từ tâm lan ra/)
  assert.match(source, /Centre outward/)
  assert.match(source, /OutputFolderField/)
  assert.match(source, /appFolder="drawing"/)
})

test('APP outputs share one documented root with feature subfolders', async () => {
  const [paths, config, field, flow, drawing, batch, cleaner, subtitles, review, tts, download] = await Promise.all([
    readFile(new URL('../backend/pipeline/core/output_paths.py', import.meta.url), 'utf8'),
    readFile(new URL('../backend/pipeline/core/app_config.py', import.meta.url), 'utf8'),
    readFile(new URL('../frontend/src/shared/components/OutputFolderField.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../frontend/src/pages/FlowPage.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../frontend/src/pages/DrawingPage.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../frontend/src/pages/BatchPage.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../frontend/src/pages/VideoCleanerPage.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../frontend/src/pages/SrtExportPage.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../frontend/src/pages/FilmPage.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../frontend/src/features/tts/TtsStudio.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../frontend/src/features/download/DownloadStudio.tsx', import.meta.url), 'utf8'),
  ])
  assert.match(paths, /APP_OUTPUT_ROOT_NAME = "ZM_AIO_TOOL"/)
  assert.match(config, /"desktopOutputRoot"/)
  assert.match(field, /className="output-folder-combined"/)
  assert.match(field, /className="output-folder-prefix"/)
  assert.match(field, /className="output-folder-prefix-short"/)
  assert.match(field, /const tail = parts\.slice\(-[12]\)\.join\('\/'\)/)
  assert.match(field, /…\/\$\{tail\}\//)

  assert.match(field, /const compactPrefix = useMemo\(\(\) => compactOutputPrefix\(outputPrefix\)/)
  assert.doesNotMatch(field, /…\/\{appFolder\}\//)
  assert.match(field, /aria-disabled="true"/)
  assert.match(field, /className="output-folder-suffix"/)
  assert.match(field, /function chooseOutputFolder\(\)/)
  assert.match(field, /onChange\(`\$\{selected\.replace/)
  assert.match(field, /if \(\/\[\\\\\/]\$\/\.test\(entered\)\)/)
  assert.match(field, /appFolder: string/)
  for (const source of [flow, drawing, batch, cleaner, subtitles, review, tts, download]) {
    assert.match(source, /appFolder=/)
  }
})

test('output-folder pickers are APP-only across every tab', async () => {
  const files = [
    '../frontend/src/pages/FlowPage.tsx',
    '../frontend/src/pages/DrawingPage.tsx',
    '../frontend/src/pages/BatchPage.tsx',
    '../frontend/src/pages/VideoCleanerPage.tsx',
    '../frontend/src/pages/SrtExportPage.tsx',
    '../frontend/src/pages/FilmPage.tsx',
    '../frontend/src/features/editor/ExportModal.tsx',
    '../frontend/src/features/download/DownloadStudio.tsx',
    '../frontend/src/features/tts/TtsStudio.tsx',
  ]
  const sources = await Promise.all(files.map((file) => readFile(new URL(file, import.meta.url), 'utf8')))
  for (const source of sources) {
    assert.match(source, /<OutputFolderField/)
    assert.match(source, /onChoose=\{isDesktopApp \?/)
  }
})

test('Flow/Veo backend workspace uses bilingual localized UI', async () => {
  const [source, styles] = await Promise.all([
    readFile(new URL('../frontend/src/pages/FlowPage.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../frontend/src/pages/FlowPage.css', import.meta.url), 'utf8'),
  ])
  assert.match(source, /localize\(locale,/)
  assert.match(source, /Tạo video/, 'Vietnamese create-video label is present')
  assert.match(source, /Create video/, 'English create-video label is present')
  assert.match(source, /Tạo ảnh/, 'Vietnamese create-image label is present')
  assert.match(source, /Create image/, 'English create-image label is present')
  assert.match(source, /Nhập TXT \/ CSV \/ JSON/)
  assert.match(source, /Import TXT \/ CSV \/ JSON/)
  assert.match(source, /Gửi qua Chrome profile của tài khoản đã chọn/)
  assert.match(source, /Sent through the selected account Chrome profile/)
  assert.match(source, /Tài khoản Google Flow/)
  assert.match(source, /Google Flow accounts/)
  assert.match(source, /Thêm tài khoản/)
  assert.match(source, /Add account/)
  assert.match(source, /Ảnh → Ảnh/)
  assert.match(source, /Image → Image/)
  assert.match(source, /Tham chiếu → Ảnh/)
  assert.match(source, /Reference → Image/)
  assert.match(source, /Mức bám ảnh tham chiếu/)
  assert.match(source, /Reference strength/)
  assert.match(source, /Tiền tố tên file/)
  assert.match(source, /Filename prefix/)
  assert.match(source, /3\. Thư mục kết quả/)
  assert.match(source, /t\("Video", "Videos"\)/)
  assert.match(source, /t\("Ảnh", "Images"\)/)
  assert.match(source, /openSrtImageWithFlowFolder/)
  assert.match(source, /appFolder=\{`flow\/\$\{createKind\}`\}/)
  assert.doesNotMatch(source, /flowKindOutputFolder/)
  assert.match(source, /function normalizeLegacyFlowOutputDir/)
  assert.match(source, /3\. Output folder/)
  assert.match(source, /OutputFolderField/)
  assert.match(styles, /\.flow-check input[\s\S]*width: 16px/)
  assert.match(source, /Sửa tài khoản/)
  assert.match(source, /Edit account/)
  assert.match(source, /Chạy lại/)
  assert.match(source, /Retry/)
  assert.match(source, /Xóa job này khỏi danh sách/)
  assert.match(source, /Delete this job from the list/)
  assert.match(source, /Tự động tải về khi hoàn thành/)
  assert.match(source, /Auto-download when completed/)
  assert.match(source, /Log hoạt động Flow/)
  assert.match(source, /Flow activity logs/)
  assert.match(source, /Xóa toàn bộ log Flow/)
  assert.match(source, /Clear all Flow logs/)
  assert.match(source, /Sao chép log/)
  assert.match(source, /Copy logs/)
  assert.match(source, /Đã sao chép/)
  assert.match(source, /Copied/)
  assert.match(source, /Job gặp lỗi/)
  assert.match(source, /Job failed/)
  assert.doesNotMatch(source, /setInterval\(\(\) => void refresh\(\), 2500\)/, 'Flow must not poll every endpoint while idle')
  assert.match(source, /hasActiveFlowJobs/)
  assert.match(source, /setInterval\(refreshJobs, 5000\)/)
  assert.match(source, /tab !== "logs"/)
  assert.match(source, /setInterval\(refreshLogs, 10000\)/)
  assert.match(source, /readText\(RAIL_KEY, "1"\) === "1"/)
})

test('Tools output folders use bilingual labels', async () => {
  const [field, cleaner, exporter, drawing, flow, review, batch, editor] = await Promise.all([
    readFile(new URL('../frontend/src/shared/components/OutputFolderField.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../frontend/src/pages/VideoCleanerPage.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../frontend/src/pages/SrtExportPage.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../frontend/src/pages/DrawingPage.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../frontend/src/pages/FlowPage.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../frontend/src/pages/FilmPage.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../frontend/src/pages/BatchPage.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../frontend/src/features/editor/ExportModal.tsx', import.meta.url), 'utf8'),
  ])
  assert.match(field, /t\('Thư mục lưu', 'Save folder'\)/)
  assert.match(field, /t\('Chọn', 'Choose'\)/)
  assert.match(field, /t\('Lưu', 'Save'\)/)
  assert.doesNotMatch(field, /isDesktopApp \? 'APP' : 'WEB'/)
  for (const source of [cleaner, exporter, drawing, flow, review, batch, editor]) {
    assert.match(source, /OutputFolderField/)
  }
})

test('Download Video uses editable WEB output names without legacy Chrome copy', async () => {
  const [source, field] = await Promise.all([
    readFile(new URL('../frontend/src/features/download/DownloadStudio.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../frontend/src/shared/components/OutputFolderField.tsx', import.meta.url), 'utf8'),
  ])
  assert.match(source, /isDesktopApp/)
  assert.match(source, /OutputFolderField/)
  assert.doesNotMatch(field, /Nhập thư mục con hoặc tên file đầu ra do bạn muốn/)
  assert.doesNotMatch(field, /Enter your preferred output subfolder or file name/)
  assert.match(field, /placeholder=\{defaultPath\}/)
  assert.match(field, /const webPathPrefix/)
  assert.match(field, /export function normalizeWebOutputName/)
  assert.match(field, /if \(trimmed === appFolder\) return ''/)
  assert.match(field, /normalized\.toLowerCase\(\)\.indexOf\('\/zm_aio_tool\/'\)/)
  assert.match(field, /after\.startsWith\(folder \+ '\/'\) \? after\.slice\(folder\.length \+ 1\) : after/)
  assert.doesNotMatch(field, /Theo cài đặt tải xuống của/)
  assert.doesNotMatch(source, /Theo cài đặt tải xuống của Chrome/)
  assert.doesNotMatch(source, /Vị trí thực tế do Chrome quản lý/)
  assert.match(field, /`\/Downloads\/ZM_AIO_TOOL\/\$\{appFolder\.replace/)
  assert.match(field, /value=\{outputSuffix\}/)
  assert.match(field, /function changeOutputSuffix/)


  assert.doesNotMatch(field, /Choose download folder/)
  assert.doesNotMatch(field, /showDirectoryPicker/)
  assert.match(source, /Tải xuống/, 'web result provides browser download action')
})

test('Batch Drawing queue uses bilingual localized UI', async () => {
  const source = await readFile(new URL('../frontend/src/pages/BatchPage.tsx', import.meta.url), 'utf8')
  assert.match(source, /Tất cả/)
  assert.match(source, /All queues/)
  assert.match(source, /Clone, Review, and Drawing in one list/)
  assert.match(source, /Vẽ tay hàng loạt/)
  assert.match(source, /Drawing batch/)
  assert.match(source, /Thêm ảnh rồi bấm Chạy để xử lý hàng loạt/)
  assert.match(source, /Add images, then press Run to process the batch/)
  assert.match(source, /Xem trước/)
  assert.match(source, /Preview/)
  assert.match(source, /Đường đi nét/)
  assert.match(source, /Stroke route/)
})

test('Batch navigation uses Flow-inspired color states', async () => {
  const [batch, styles] = await Promise.all([
    readFile(new URL('../frontend/src/pages/BatchPage.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../frontend/src/pages/StudioPages.css', import.meta.url), 'utf8'),
  ])
  assert.match(batch, /batch-tab--clone/)
  assert.match(batch, /aria-selected=\{tab === 'clone'\}/)
  assert.match(batch, /batch-action--resume/)
  assert.match(batch, /batch-action--danger/)
  assert.match(batch, /studio-settings-chevron[\s\S]*runQueueJobs\(\)/)
  assert.match(styles, /--batch-flow-start/)
  assert.match(styles, /batch-action--view/)
  assert.match(styles, /prefers-reduced-motion/)
})

test('Batch queue actions use compact Flow-sized controls', async () => {
  const [source, styles, api, route] = await Promise.all([
    readFile(new URL('../frontend/src/pages/BatchPage.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../frontend/src/pages/StudioPages.css', import.meta.url), 'utf8'),
    readFile(new URL('../frontend/src/features/studio/studio.api.ts', import.meta.url), 'utf8'),
    readFile(new URL('../backend/api/routes/queue.py', import.meta.url), 'utf8'),
  ])
  assert.match(styles, /\.batch-page \.studio-job-actions\s*\{[^}]*gap: 4px;[^}]*min-width: 180px;/s)
  assert.match(styles, /\.studio-page\.batch-page \.studio-job-actions button,[\s\S]*?height: 28px;[\s\S]*?padding: 0 7px;[\s\S]*?font-size: \.68rem;/)
  assert.match(styles, /\.studio-table td\.studio-job-actions\s*\{[^}]*display: table-cell;/s)
  assert.match(styles, /\.studio-queue-table--all \.studio-queue-actions-column\s*\{ width: 35%; \}/)
  assert.match(source, /studio-queue-table--all/)
  assert.match(source, /studio-queue-table--feature/)
  assert.match(source, /drawingJobs\.map[\s\S]*batch-action--view[\s\S]*batch-action--open[\s\S]*batch-action--danger/)
  assert.match(styles, /\.drawing-job-actions \.batch-action--danger/)
  assert.equal((source.match(/studioApi\.thumbnailUrl\(job\.id\)/g) || []).length, 2)
  assert.match(source, /studioApi\.thumbnailUrl\(job\.id\)/)
  assert.match(api, /thumbnailUrl: \(jobId: string\)/)
  assert.match(route, /@router\.get\("\/api\/queue\/\{job_id\}\/thumbnail"\)/)
  assert.match(route, /resolve_job_thumbnail_source/)
  assert.match(route, /_existing_thumbnail/)
})

test('Batch file selection creates localized queue jobs immediately', async () => {
  const source = await readFile(new URL('../frontend/src/pages/BatchPage.tsx', import.meta.url), 'utf8')
  assert.match(source, /create jobs in the queue below, then press Run/)
  assert.doesNotMatch(source, /It only runs after you press Run/)
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

test('TTS exposes a bilingual APP/WEB output folder selector', async () => {
  const source = await readFile(new URL('../frontend/src/features/tts/TtsStudio.tsx', import.meta.url), 'utf8')
  assert.match(source, /OutputFolderField/)
  assert.match(source, /className="tts-output-folder"/)
  assert.match(source, /Thư mục đầu ra/)
  assert.match(source, /publishOutput/)
  assert.match(source, /webOutputStem/)
})

test('macOS form controls preserve each feature compact size', async () => {
  const [styles, headerStyles, main] = await Promise.all([
    readFile(new URL('../frontend/src/index.css', import.meta.url), 'utf8'),
    readFile(new URL('../frontend/src/shared/components/Header.css', import.meta.url), 'utf8'),
    readFile(new URL('../frontend/src/main.tsx', import.meta.url), 'utf8'),
  ])
  assert.doesNotMatch(styles, /html\.platform-macos select:not\(\[multiple\]\)/)
  assert.doesNotMatch(styles, /min-height: 38px !important/)
  assert.match(headerStyles, /html\.platform-macos select\.locale-select:not\(\[multiple\]\)/)
  assert.match(headerStyles, /width: 58px !important/)
  assert.match(headerStyles, /min-height: 28px !important/)
  assert.match(headerStyles, /appearance: none/)
  assert.match(main, /navigator\.platform/)
  assert.match(main, /userAgentData\?\.platform/)
})

test('macOS Download and TTS selects match Clone Recognition metrics', async () => {
  const [download, tts] = await Promise.all([
    readFile(new URL('../frontend/src/features/download/DownloadStudio.css', import.meta.url), 'utf8'),
    readFile(new URL('../frontend/src/features/tts/TtsStudio.css', import.meta.url), 'utf8'),
  ])
  for (const styles of [download, tts]) {
    assert.match(styles, /\.platform-macos[\s\S]*height: 35px;/)
    assert.match(styles, /padding: 0 30px 0 10px;/)
    assert.match(styles, /font-size: \.84rem;/)
    assert.match(styles, /calc\(100% - 16px\) 50%/)
  }
})

test('macOS Video Cleaner and subtitle export selects match Clone Recognition metrics', async () => {
  const [cleaner, subtitleExport] = await Promise.all([
    readFile(new URL('../frontend/src/pages/VideoCleanerPage.css', import.meta.url), 'utf8'),
    readFile(new URL('../frontend/src/pages/SrtExportPage.css', import.meta.url), 'utf8'),
  ])
  for (const styles of [cleaner, subtitleExport]) {
    assert.match(styles, /\.platform-macos[\s\S]*height: 35px;/)
    assert.match(styles, /padding: 0 30px 0 10px;/)
    assert.match(styles, /font-size: \.84rem;/)
    assert.match(styles, /calc\(100% - 16px\) 50%/)
  }
})

test('Download and Video Cleaner detailed logs are bilingual, copyable, clearable, and use compact actions', async () => {
  const [download, cleaner, downloadStyles, cleanerStyles] = await Promise.all([
    readFile(new URL('../frontend/src/features/download/DownloadStudio.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../frontend/src/pages/VideoCleanerPage.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../frontend/src/features/download/DownloadStudio.css', import.meta.url), 'utf8'),
    readFile(new URL('../frontend/src/pages/VideoCleanerPage.css', import.meta.url), 'utf8'),
  ])
  for (const source of [download, cleaner]) {
    assert.match(source, /copyDetailLog/)
    assert.match(source, /clearDetailLog/)
    assert.match(source, /Log chi tiết/)
    assert.match(source, /Detailed log/)
    assert.match(source, /Sao chép/)
    assert.match(source, /Copy/)
  }
  assert.match(download, /downloadApi\.clearLogs/)
  assert.match(cleaner, /cleanerApi\.clearLogs/)
  assert.match(download, /downloadOutput/)
  assert.match(download, /className="dl-result-action"/)
  assert.match(cleaner, /className="vc-result-action"/)
  assert.match(downloadStyles, /\.dl-log-actions button\s*\{[\s\S]*?min-height: 24px;/)
  assert.match(cleanerStyles, /\.vc-log-action\s*\{[\s\S]*?min-height: 24px;/)
  assert.match(downloadStyles, /\.dl-result-action\s*\{[\s\S]*?min-height:\s*(?:20|22|25)px;[\s\S]*?white-space:\s*nowrap;/)
  assert.match(cleanerStyles, /\.vc-result-action\s*\{[\s\S]*?min-height:\s*(?:20|22|25)px;[\s\S]*?white-space:\s*nowrap;/)
})

test('Download and Video Cleaner results separate APP reveal from WEB download', async () => {
  const [download, cleaner, cleanerApi] = await Promise.all([
    readFile(new URL('../frontend/src/features/download/DownloadStudio.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../frontend/src/pages/VideoCleanerPage.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../frontend/src/features/cleaner/cleaner.api.ts', import.meta.url), 'utf8'),
  ])
  assert.match(download, /!isDesktopApp[\s\S]*?Tải xuống[\s\S]*?isDesktopApp[\s\S]*?Mở thư mục/)
  assert.match(cleaner, /isDesktopApp \? [\s\S]*?cleanerApi\.reveal\(job\.id\)[\s\S]*?: [\s\S]*?downloadCleanerOutput\(job\.id\)/)
  assert.match(cleaner, /t\('Tải xuống', 'Download'\)/)
  assert.match(cleanerApi, /fileUrl\(id: string, download = false\)/)
  assert.match(cleanerApi, /\?download=1/)
})

test('Download output folder hint stays separated from option checkboxes', async () => {
  const styles = await readFile(new URL('../frontend/src/features/download/DownloadStudio.css', import.meta.url), 'utf8')
  assert.match(styles, /\.dl-studio \.output-folder-field\s*\{[^}]*margin-bottom: 10px;/s)
  assert.match(styles, /\.dl-studio \.output-folder-hint\s*\{[^}]*display: block;[^}]*min-height: 18px;[^}]*line-height: 18px;/s)
})

test('quick settings keep paired controls at equal widths', async () => {
  const styles = await readFile(new URL('../frontend/src/features/project/ProjectSidebar.css', import.meta.url), 'utf8')
  assert.match(styles, /\.locate-logo-filter\s*\{[^}]*grid-template-columns: repeat\(2, minmax\(0, 1fr\)\)/s)
  assert.match(styles, /\.workers-setting\s*\{\s*flex: 1 1 0;/)
  assert.match(styles, /\.preview-len\s*\{\s*flex: 1 1 0;\s*max-width: none;/)
  assert.match(styles, /\.platform-macos \.sidebar \.field select[\s\S]*height: 35px/)
  assert.match(styles, /calc\(100% - 16px\) 50%/)
  assert.doesNotMatch(styles, /\.audio-filter-toggle[\s\S]*height: 44px/)
})

test('Flow output options render as separate parent rows', async () => {
  const [source, styles] = await Promise.all([
    readFile(new URL('../frontend/src/pages/FlowPage.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../frontend/src/pages/FlowPage.css', import.meta.url), 'utf8'),
  ])
  assert.match(source, /onChoose=\{isDesktopApp \? pickOutputFolder : (?:pickWebOutputFolder|\(\) => void pickWebOutputFolder\(\))\}/)
})


test('Flow prompt file import is always visible and compact', async () => {
  const [source, styles] = await Promise.all([
    readFile(new URL('../frontend/src/pages/FlowPage.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../frontend/src/pages/FlowPage.css', import.meta.url), 'utf8'),
  ])
  assert.doesNotMatch(source, /importOpen|setImportOpen/)
  assert.match(source, /flow-import-row/)
  assert.match(source, /Nhập TXT \/ CSV \/ JSON/)
  assert.match(source, /Import TXT \/ CSV \/ JSON/)
  assert.match(styles, /\.flow-import-row > button\s*\{[^}]*height: 30px;/s)
})

test('Flow history uses persisted prompt input provenance', async () => {
  const source = await readFile(new URL('../frontend/src/pages/FlowPage.tsx', import.meta.url), 'utf8')
  assert.match(source, /inputType: promptInputType/)
  assert.match(source, /job\.inputType === "prompt"/)
  assert.match(source, /Nhập tay/)
  assert.match(source, /Manual/)
  assert.doesNotMatch(source, /index % 2 \? "TXT" : "Prompt"/)
})

test('Flow heading keeps description and backend state compact', async () => {
  const [source, styles] = await Promise.all([
    readFile(new URL('../frontend/src/pages/FlowPage.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../frontend/src/pages/FlowPage.css', import.meta.url), 'utf8'),
  ])
  assert.match(source, /className="flow-heading"/)
  assert.match(styles, /\.flow-heading\s*\{[^}]*display: flex;[^}]*flex-wrap: wrap;[^}]*margin-bottom: 8px;/s)
  assert.match(styles, /\.flow-page-title\s*\{[^}]*display: inline-flex;/s)
  assert.match(styles, /\.flow-api-state\s*\{[^}]*margin: 0 0 0 auto;/s)
  assert.match(source, /Tạo ảnh và video bằng tài khoản Google Pro\/Ultra\./)
  assert.match(source, /Create images and videos with Google Pro\/Ultra accounts\./)
})

test('Flow creation falls back to the connected account when an old saved label is missing', async () => {
  const source = await readFile(new URL('../frontend/src/pages/FlowPage.tsx', import.meta.url), 'utf8')
  assert.match(source, /function selectedFlowAccount\(accounts: FlowAccount\[\], accountLabel: string\)/)
  assert.match(source, /accounts\.find\(\(account\) => account\.status === "online"\)/)
  assert.match(source, /const account = selectedFlowAccount\(accounts, settings\.account\);/)
})

test('Flow default account selection updates the account cards immediately', async () => {
  const source = await readFile(new URL('../frontend/src/pages/FlowPage.tsx', import.meta.url), 'utf8')
  assert.match(source, /const setDefaultAccount = async \(id: string\)/)
  assert.match(source, /account\.id === saved\.id\s*\? \{ \.\.\.saved, isDefault: true \}\s*:\s*\{ \.\.\.account, isDefault: false \}/s)
  assert.match(source, /onClick=\{\(\) => void setDefaultAccount\(account\.id\)\}/)
})

test('Flow opens advanced quick settings by default for image and video creation', async () => {
  const source = await readFile(new URL('../frontend/src/pages/FlowPage.tsx', import.meta.url), 'utf8')
  assert.match(source, /const \[advancedOpen, setAdvancedOpen\] = useState\(true\)/)
  assert.match(source, /if \(item === "createVideo"\) setAdvancedOpen\(true\);/)
  assert.match(source, /t\("Luồng chạy", "Concurrent jobs"\)/)
  assert.match(source, /concurrency: "3"/)
  assert.match(source, /options=\{\["1", "2", "3", "4", "5", "6"\]\}/)
  assert.doesNotMatch(source, /Seed \(để trống = tự động\)/)
})

test('TTS history action menu layers above its pager', async () => {
  const [panel, styles] = await Promise.all([
    readFile(new URL('../frontend/src/features/tts/TtsHistoryPanel.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../frontend/src/features/tts/TtsStudio.css', import.meta.url), 'utf8'),
  ])
  assert.match(panel, /tts-dl-wrap\$\{downloadMenuId === h\.id \? ' is-open' : ''\}/)
  assert.match(styles, /\.tts-history-wrap:has\(\.tts-dl-wrap\.is-open\)\s*\{\s*z-index: 20;/s)
  assert.match(styles, /\.tts-dl-wrap\.is-open\s*\{\s*z-index: 30;/s)
  assert.match(styles, /\.tts-pager\s*\{\s*position: relative;\s*z-index: 1;/s)
  assert.match(panel, /className="tts-dl-menu tts-history-dl-menu"/)
  assert.match(styles, /\.tts-history-dl-menu\s*\{\s*top: auto;\s*bottom: calc\(100% \+ 8px\);/s)
  assert.match(styles, /\.tts-dl-submenu\s*\{\s*top: 0;\s*bottom: auto;/s)
})

test('TTS export SRT menu opens above every dashboard panel', async () => {
  const styles = await readFile(new URL('../frontend/src/features/tts/TtsStudio.css', import.meta.url), 'utf8')
  assert.match(styles, /\.tts-dash-item:has\(\.tts-export-srt-menu\)\s*\{\s*z-index: 40;/s)
  assert.match(styles, /\.tts-export-srt-menu\s*\{[^}]*top: auto;[^}]*bottom: calc\(100% \+ 8px\);/s)
})

test('TTS history playback toggles a bilingual stop action while audio is playing', async () => {
  const [studio, history] = await Promise.all([
    readFile(new URL('../frontend/src/features/tts/TtsStudio.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../frontend/src/features/tts/TtsHistoryPanel.tsx', import.meta.url), 'utf8'),
  ])
  assert.match(studio, /const \[playingHistoryId, setPlayingHistoryId\] = useState<string \| null>\(null\)/)
  assert.match(studio, /function stopHistoryPlayback\(\)/)
  assert.match(studio, /if \(playingHistoryId === h\.id\)/)
  assert.match(studio, /player\.onended = reset/)
  assert.match(history, /playingHistoryId: string \| null/)
  assert.match(history, /IconStop/)
  assert.match(history, /t\('Dừng phát', 'Stop playback'\)/)
  assert.match(history, /\{isPlaying \? <IconStop size=\{12\} \/> : <IconPlay size=\{12\} \/>\}/)
})

test('Flow manual prompt provides bilingual paste and clear actions', async () => {
  const [source, styles] = await Promise.all([
    readFile(new URL('../frontend/src/pages/FlowPage.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../frontend/src/pages/FlowPage.css', import.meta.url), 'utf8'),
  ])
  assert.match(source, /navigator\.clipboard\.readText\(\)/)
  assert.match(source, /t\("Dán", "Paste"\)/)
  assert.match(source, /t\("Xóa", "Clear"\)/)
  assert.match(source, /onClick=\{\(\) => \{[\s\S]*setPrompt\(""\);[\s\S]*setPromptInputType\("prompt"\);/)
  assert.match(styles, /\.flow-prompt-actions\s*\{[^}]*display: inline-flex;/s)
  assert.match(styles, /\.flow-workspace \.flow-prompt-actions > button\s*\{[^}]*height: 26px;/s)
})

test('Flow queue exposes bilingual bulk cancel and delete actions', async () => {
  const [source, styles, route] = await Promise.all([
    readFile(new URL('../frontend/src/pages/FlowPage.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../frontend/src/pages/FlowPage.css', import.meta.url), 'utf8'),
    readFile(new URL('../backend/api/routes/flow.py', import.meta.url), 'utf8'),
  ])
  assert.match(source, /t\("Hủy tất cả", "Cancel all"\)/)
  assert.match(source, /t\("Xóa tất cả", "Delete all"\)/)
  assert.match(source, /\/api\/flow\/jobs\/cancel-all/)
  assert.match(styles, /\.flow-queue-tools\s*\{[^}]*display: inline-flex;/s)
  assert.match(route, /@router\.post\("\/jobs\/cancel-all"\)/)
  assert.match(route, /@router\.delete\("\/jobs"\)/)
})

test('Flow destructive actions use an in-app bilingual confirmation modal', async () => {
  const [source, styles] = await Promise.all([
    readFile(new URL('../frontend/src/pages/FlowPage.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../frontend/src/pages/FlowPage.css', import.meta.url), 'utf8'),
  ])
  assert.doesNotMatch(source, /window\.confirm/)
  assert.match(source, /className="flow-confirm-dialog"/)
  assert.match(source, /t\("Xác nhận thao tác", "Confirm action"\)/)
  assert.match(source, /t\("Quay lại", "Go back"\)/)
  assert.match(styles, /\.flow-confirm-dialog\s*\{[^}]*width: min\(420px, 92vw\);/s)
})

test('Flow exposes live-account models through the authenticated UI path', async () => {
  const [source, service] = await Promise.all([
    readFile(new URL('../frontend/src/pages/FlowPage.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../backend/pipeline/flow/service.py', import.meta.url), 'utf8'),
  ])
  for (const model of ['Omni Flash', 'Veo 3.1 - Lite', 'Veo 3.1 - Lite [Lower Priority]', 'Veo 3.1 - Fast', 'Veo 3.1 - Quality', 'Nano Banana Pro', 'Nano Banana 2', 'Nano Banana 2 Lite']) {
    assert.match(source, new RegExp(model.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')))
  }
  assert.doesNotMatch(source, /Imagen 4/)
  assert.match(service, /await client\.generate_image\(/)
  assert.match(service, /await client\.generate_video\(/)
  assert.doesNotMatch(service, /batchAsyncGenerateVideoText/)
  assert.match(service, /await self\._prepare_ui_model\(page, "video", model/)
  assert.match(service, /Image\|(?:Hình ảnh|H\\u00ecnh \\u1ea3nh)/)
})

test("Flow queue renders each job's persisted generation settings", async () => {
  const source = await readFile(new URL('../frontend/src/pages/FlowPage.tsx', import.meta.url), 'utf8')
  assert.match(source, /raw\.settings/)
  assert.match(source, /job\.settings\.model/)
  assert.match(source, /job\.settings\.ratio/)
  assert.doesNotMatch(source, /Imagen 3 Fast · 1:1 · 1K/)
})

test('Flow WEB output saves automatically into a user-authorized folder', async () => {
  const [source, styles, field] = await Promise.all([
    readFile(new URL('../frontend/src/pages/FlowPage.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../frontend/src/pages/FlowPage.css', import.meta.url), 'utf8'),
    readFile(new URL('../frontend/src/shared/components/OutputFolderField.tsx', import.meta.url), 'utf8'),
  ])
  assert.match(source, /function defaultFlowOutputFolder/)
  assert.match(source, /outputDir: defaultFlowOutputFolder\(\)/)
  assert.match(source, /settings: effectiveSettings/)
  assert.match(source, /function flowOutputFolderName/)
  assert.match(source, /const queueGroups = useMemo/)
  assert.match(source, /const queueKindGroups = useMemo/)
  assert.match(source, /aria-label=\{t\("Loại hàng đợi", "Queue type"\)\}/)
  assert.match(source, /t\("Tất cả", "All"\)/)
  assert.match(source, /new Map<string, \{ kind: CreateKind; outputDir: string; outputFolder: string; displayOutputFolder: string; jobs: FlowJob\[\]; maxCreatedAt: number \}>\(\)/)
  assert.doesNotMatch(source, /outputDir: flowKindOutputFolder/)
  assert.match(source, /function flowConfiguredOutputFolder/)
  assert.match(source, /if \(\/\^\(\?:\[A-Za-z\]:\[\\\\\/\]\|\[\\\\\/\]\)\/\.test\(outputDir\)\) return `\$\{outputDir\}\/\$\{kind\}`/)
  assert.match(source, /`ZM_AIO_TOOL\/flow\/\$\{kind\}\/\$\{outputDir/)
  assert.match(source, /function flowOutputParentPath/)
  assert.match(source, /isDesktopApp \? flowOutputParentPath/)
  assert.match(source, /t\("Tiến độ tổng", "Overall progress"\)/)
  assert.match(source, /role="progressbar"/)
  assert.match(source, /job\.status === "done"/)
  assert.match(source, /summary\.completed}\/\$\{summary\.total} hoàn thành/)
  assert.match(source, /summary\.completed}\/\$\{summary\.total} completed/)
  assert.match(styles, /\.flow-queue-folder-summary/)
  assert.match(styles, /\.flow-queue-folder-progress/)
  assert.match(styles, /\.flow-queue-folder-progress\s*\{[^}]*height:\s*3px;/)
  assert.match(styles, /\.flow-queue-folder-actions\s*\{[^}]*margin-left:\s*auto;/)
  assert.match(source, /queueFolderLabel\(group\.kind, group\.outputDir, group\.outputFolder, group\.displayOutputFolder\)/)
  assert.match(source, /openSrtImageWithFlowFolder\(queueFolderLabel\(group\.kind, group\.outputDir, group\.outputFolder, group\.displayOutputFolder\)\)/)
  assert.match(source, /const deleteFolderJobs/)
  assert.match(source, /const cancelFolderJobs/)
  assert.match(source, /\/api\/flow\/jobs\/delete-folder/)
  assert.match(source, /\/api\/flow\/jobs\/cancel-folder/)
  assert.match(source, /async function writeFlowOutputToDirectory/)
  assert.match(source, /ZM_AIO_TOOL/)
  assert.match(source, /root\.name === "ZM_AIO_TOOL"/)
  assert.match(source, /showDirectoryPicker/)
  assert.match(source, /saveWebOutputRoot/)
  assert.match(source, /loadWebOutputRoot/)
  assert.match(source, /function flowOutputFolderParts/)
  assert.match(source, /setWebOutputRootReady\(true\)/)
  assert.match(source, /Đã lưu output Flow vào thư mục đã chọn\./)
  assert.match(source, /Flow output saved to the selected folder\./)
  assert.match(source, /flowOutputDirectory\(root, job\.kind, outputFolder, true\)/)
  assert.match(source, /writeFlowOutputToDirectory\(item\.job, item\.outputIndex, root, item\.job\.settings\.outputDir\)/)
  assert.match(source, /async function deleteFlowOutputFromDirectory/)
  assert.match(source, /await file\.getFile\(\)/)
  assert.match(source, /await target\.removeEntry\(sourceName\)/)
  assert.match(source, /await deleteWebFlowOutputs\(job\)/)
  assert.match(source, /onChoose=\{isDesktopApp \? pickOutputFolder : (?:pickWebOutputFolder|\(\) => void pickWebOutputFolder\(\))\}/)
  assert.match(field, /const webPathPrefix/)

  assert.match(field, /value=\{outputSuffix\}/)
})

test('Flow create-video screen exposes the latest completed video preview', async () => {
  const [source, styles] = await Promise.all([
    readFile(new URL('../frontend/src/pages/FlowPage.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../frontend/src/pages/FlowPage.css', import.meta.url), 'utf8'),
  ])
  assert.match(source, /latestCompletedVideo/)
  assert.match(source, /t\("Xem trước video", "Preview video"\)/)
  assert.match(source, /t\("Chưa có video", "No video yet"\)/)
  assert.match(styles, /\.flow-preview-latest/)
})

test('Flow output preview navigates and renders common media types', async () => {
  const [source, styles] = await Promise.all([
    readFile(new URL('../frontend/src/pages/FlowPage.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../frontend/src/pages/FlowPage.css', import.meta.url), 'utf8'),
  ])
  assert.match(source, /function flowOutputMediaKind/)
  assert.match(source, /"audio"/)
  assert.match(source, /"ArrowLeft"/)
  assert.match(source, /"ArrowRight"/)
  assert.match(source, /t\("Kết quả trước", "Previous output"\)/)
  assert.match(source, /t\("Kết quả tiếp theo", "Next output"\)/)
  assert.match(source, /<audio/)
  assert.match(source, /<iframe/)
  assert.match(source, /aria-live="polite"/)
  assert.match(styles, /\.flow-preview-nav/)
  assert.match(styles, /\.flow-preview-counter/)
})

test('Flow queue confines large batches to its own scroll area', async () => {
  const [flowStyles, studioStyles, cleanerStyles, batch] = await Promise.all([
    readFile(new URL('../frontend/src/pages/FlowPage.css', import.meta.url), 'utf8'),
    readFile(new URL('../frontend/src/pages/StudioPages.css', import.meta.url), 'utf8'),
    readFile(new URL('../frontend/src/pages/VideoCleanerPage.css', import.meta.url), 'utf8'),
    readFile(new URL('../frontend/src/pages/BatchPage.tsx', import.meta.url), 'utf8'),
  ])
  assert.match(flowStyles, /\.flow-queue-list\s*\{[\s\S]*max-height:\s*min\(68vh, 680px\)/)
  assert.match(flowStyles, /\.flow-result-grid\s*\{[\s\S]*max-height:\s*min\(58vh, 560px\)/)
  assert.match(flowStyles, /\.flow-history-scroll\s*\{[\s\S]*max-height:\s*min\(62vh, 620px\)/)
  assert.match(studioStyles, /\.studio-queue-scroll\s*\{[\s\S]*max-height:\s*min\(62vh, 620px\)/)
  assert.match(studioStyles, /\.drawing-job-list\{[\s\S]*max-height:min\(62vh,620px\)/)
  assert.match(cleanerStyles, /\.vc-table-wrap\s*\{\s*max-height:\s*min\(62vh, 620px\);\s*overflow:\s*auto/)
  assert.equal((batch.match(/className="studio-queue-scroll"/g) || []).length, 2)
})

test('SRT image merge accepts a media folder without a timeline file', async () => {
  const [page, route, pipeline, app] = await Promise.all([
    readFile(new URL('../frontend/src/pages/SrtImagePage.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../backend/api/routes/srt_image.py', import.meta.url), 'utf8'),
    readFile(new URL('../backend/pipeline/srt_image.py', import.meta.url), 'utf8'),
    readFile(new URL('../frontend/src/app/App.tsx', import.meta.url), 'utf8'),
  ])
  assert.match(page, /if \(!mediaFolder\) return/)
  assert.doesNotMatch(page, /!mediaFolder \|\| !timelinePath/)
  assert.match(page, /File timeline/)
  assert.match(page, /Timeline file/)
  assert.match(page, /Dán nội dung timeline/)
  assert.match(page, /Paste timeline content/)
  assert.match(page, /TXT, SRT, VTT, ASS\/SSA, CSV, TSV, JSON và LRC/)
  assert.match(page, /Vẽ ảnh tĩnh thành video/)
  assert.match(page, /Turn still images into drawing videos/)
  assert.match(page, /timelineMode === 'paste'/)
  assert.match(page, /Đổi', 'Switch'/)
  assert.match(page, /Đổi sang dán nội dung', 'Switch to pasted content'/)
  assert.match(page, /if \(timelineMode === 'paste'\) setTimelineMode\('file'\)/)
  assert.match(page, /setTimelineMode\('file'\); void chooseInputFile\('timeline'\)/)
  assert.match(page, /timelineMode === 'paste'\s*\? <textarea/)
  assert.match(page, /: <div className="siv-input">/)
  assert.match(page, /useState<'file' \| 'paste'>\('file'\)/)
  assert.match(page, /timelineMode === 'paste' && timelineText\.trim\(\)/)
  assert.match(page, /siv-row siv-row--timeline/)
  assert.match(page, /resolve-output-folder\?tab=subtitle-image/)
  assert.match(page, /ZM_AIO_TOOL\/subtitles\/image-video\//)
  assert.match(page, /Đổi', 'Switch'[\s\S]*Chọn', 'Choose'[\s\S]*Xóa', 'Clear'/)
  assert.match(page, /Nguồn timeline', 'Timeline source'/)
  assert.match(page, /aria-label=\{timelineMode === 'paste' \? t\('Đổi sang chọn file'/)
  const styles = await readFile(new URL('../frontend/src/pages/SrtImagePage.css', import.meta.url), 'utf8')
  assert.match(styles, /\.siv-source-switch\s*\{[\s\S]*gap:\s*6px/)
  assert.match(page, /form\.append\('timeline', new Blob\(\[timelineText\]/)
  assert.match(route, /TIMELINE_SUFFIXES = \{"\.txt", "\.srt", "\.vtt", "\.ass", "\.ssa", "\.csv", "\.tsv", "\.json", "\.lrc"\}/)
  assert.match(route, /copy_input\(timeline_path, timeline, "timeline", TIMELINE_SUFFIXES\)/)
  assert.match(route, /downloads_folder\("subtitle-image"\) \/ selected/)
  assert.match(pipeline, /def parse_timing_times/)
  assert.match(pipeline, /def sequential_media_times/)
  assert.match(pipeline, /parse_timing_times\(Path\(timeline\)\) if timeline else sequential_media_times\(media\)/)
  assert.match(page, /t\('Vẫn tạo', 'Create anyway'\)/)
  assert.match(page, /t\('Thiếu ảnh\/video', 'Missing image\/video'\)/)
  assert.match(page, /allowMissingMedia/)
  assert.match(page, /status === 409/)
  assert.match(route, /"code": "missing_media"/)
  assert.match(pipeline, /select_cues_for_media/)
  assert.match(styles, /\.siv-missing-dialog/)
  assert.match(page, /\{mediaFolder \? \(/)
  assert.doesNotMatch(page, /\{delogoEnabled && mediaFolder \? \(/)
  assert.match(page, /setMediaPreviewError\(false\)/)
  assert.match(page, /onError=\{\(\) => setMediaPreviewError\(true\)\}/)
  assert.match(page, /t\('Không tải được media xem trước', 'Unable to load preview media'\)/)
  assert.match(page, /logo=\{logoProp\}/)
  assert.match(page, /className="siv-live-logo"/)
  assert.match(page, /logoClock/)
  assert.match(route, /@router\.get\("\/api\/srt-image\/logo-preview"\)/)
  assert.match(styles, /\.siv-live-logo/)
  assert.match(page, /initialMediaFolder = ''/)
  assert.match(page, /setMediaFolder\(initialMediaFolder\)/)
  assert.match(app, /setSrtImageInitialMediaFolder\(mediaFolder\)/)
  assert.match(app, /initialMediaFolder=\{srtImageInitialMediaFolder\}/)
})

test('Flow never presents an empty-output job as a localized success', async () => {
  const [source, service] = await Promise.all([
    readFile(new URL('../frontend/src/pages/FlowPage.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../backend/pipeline/flow/service.py', import.meta.url), 'utf8'),
  ])
  assert.match(service, /FLOW_EMPTY_OUTPUT/)
  assert.match(service, /_outputs_exist\(outputs\)/)
  assert.match(source, /Flow không trả về file video\/ảnh\. Job chưa thành công\./)
  assert.match(source, /Flow returned no video\/image file\. The job did not succeed\./)
})

test('Flow Series keeps bilingual project, continuity, and scene actions', async () => {
  const [page, panel, service] = await Promise.all([
    readFile(new URL('../frontend/src/pages/FlowPage.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../frontend/src/pages/FlowSeriesPanel.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../backend/pipeline/flow/series.py', import.meta.url), 'utf8'),
  ])
  assert.match(page, /\["series", IconBook, t\("Series", "Series"\)\]/)
  assert.match(panel, /t\('Tạo keyframe', 'Create keyframe'\)/)
  assert.match(panel, /t\('Video', 'Video'\)/)
  assert.match(panel, /t\('Nối cảnh', 'Continue'\)/)
  assert.match(panel, /t\('Chưa có ảnh neo\. Bạn vẫn có thể tạo keyframe bằng prompt\.', 'No anchor image yet\. You can still create a keyframe from the prompt\.'\)/)
  assert.match(panel, /t\('Chưa có tập\. Thêm tập đầu tiên để tạo các cảnh\.', 'No episode yet\. Add the first episode to create scenes\.'\)/)
  assert.match(panel, /loading="lazy"/)
  assert.match(service, /"seriesSlug"/)
  assert.match(service, /"endFrame"/)
})

test('Flow Series generates a bilingual locked anchor through the connected Flow account', async () => {
  const [page, panel, route] = await Promise.all([
    readFile(new URL('../frontend/src/pages/FlowPage.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../frontend/src/pages/FlowSeriesPanel.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../backend/api/routes/flow.py', import.meta.url), 'utf8'),
  ])
  assert.match(panel, /t\('Tạo ảnh neo', 'Generate anchor image'\)/)
  assert.match(panel, /t\('Đã gửi job tạo ảnh neo\. Ảnh hoàn thành sẽ tự thêm và khóa\.', 'Anchor image job queued\. The completed image will be added and locked automatically\.'\)/)
  assert.match(page, /\/anchors\/generate/)
  assert.match(route, /@router\.post\("\/series\/\{series_id\}\/anchors\/generate"\)/)
})

test('Flow Series offers a bilingual guide and server-side Cloud TXT drafting', async () => {
  const panel = await readFile(new URL('../frontend/src/pages/FlowSeriesPanel.tsx', import.meta.url), 'utf8')
  const route = await readFile(new URL('../backend/api/routes/flow.py', import.meta.url), 'utf8')
  assert.match(panel, /t\('Hướng dẫn nhập Series', 'Series input guide'\)/)
  assert.match(panel, /t\('Soạn TXT bằng Cloud', 'Draft TXT with Cloud'\)/)
  assert.match(panel, /t\('Nhập TXT thành Series', 'Import TXT as Series'\)/)
  assert.match(panel, /request<\{ text: string \}>\('\/series\/draft'/)
  assert.match(route, /@router\.post\("\/series\/draft"\)/)
})

test('Flow Series panel is addressable and keeps legacy Series rows safe', async () => {
  const [page, panel, series] = await Promise.all([
    readFile(new URL('../frontend/src/pages/FlowPage.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../frontend/src/pages/FlowSeriesPanel.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../backend/pipeline/flow/series.py', import.meta.url), 'utf8'),
  ])
  assert.match(page, /URLSearchParams\(window\.location\.search\)\.get\("p"\)/)
  assert.match(page, /writeFlowRoutePanel\("series"\)/)
  assert.match(panel, /function normalizeSeries/)
  assert.match(series, /normalized\.setdefault\("assets", \[\]\)/)
})

test('Flow rail gives utility panels a single active item', async () => {
  const page = await readFile(new URL('../frontend/src/pages/FlowPage.tsx', import.meta.url), 'utf8')
  assert.match(page, /\(!utilityView && id === tab\) \|\|\s*id === utilityView/)
  assert.match(page, /\};\s*applyRoute\(\);\s*window\.addEventListener\("popstate", applyRoute\)/)
})

test('desktop APP and detailed logs allow selecting and copying text', async () => {
  const [launcher, styles, clipboard, srtImage] = await Promise.all([
    readFile(new URL('../build_app/launcher.py', import.meta.url), 'utf8'),
    readFile(new URL('../frontend/src/index.css', import.meta.url), 'utf8'),
    readFile(new URL('../frontend/src/shared/lib/clipboard.ts', import.meta.url), 'utf8'),
    readFile(new URL('../frontend/src/pages/SrtImagePage.tsx', import.meta.url), 'utf8'),
  ])
  assert.match(launcher, /text_select=True/)
  assert.match(styles, /-webkit-user-select: text/)
  assert.match(clipboard, /document\.execCommand\('copy'\)/)
  assert.match(srtImage, /copyText\(logText\)/)
})

test('Flow offers bilingual prompt guides, templates showcase, preview, copy, and download', async () => {
  const [page, tplComp, tplData] = await Promise.all([
    readFile(new URL('../frontend/src/pages/FlowPage.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../frontend/src/features/flow/FlowTemplatesPanel.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../frontend/src/features/flow/flowTemplates.ts', import.meta.url), 'utf8'),
  ])
  assert.match(page, /FlowTemplatesPanel/)
  assert.match(page, /utilityView === "help"/)
  assert.match(tplComp, /Thư viện Prompt Hệ Thống & Hướng dẫn Flow/)
  assert.match(tplComp, /Flow System Prompt Guides & Engines/)
  assert.match(tplComp, /downloadText/)
  assert.match(tplComp, /Tải về \(\.txt\)/)
  assert.match(tplData, /v1\.0-base-vietnam-2D-image\.txt/)
  assert.match(tplData, /v1\.0-base-english-2D-image\.txt/)
  assert.match(tplData, /ZMTOOL AUDIO-FIRST VIDEO PRODUCTION ENGINE V1\.0/)
})
