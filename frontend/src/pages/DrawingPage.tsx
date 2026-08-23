import { useEffect, useMemo, useRef, useState, type DragEvent } from 'react'
import { localize, useLocale } from '@/app/i18n'
import { BackTitle } from '@/shared/components/BackTitle'
import './DrawingPage.css'

type PreviewTab = 'preview' | 'line-map' | 'stroke-path'
type Tool = 'pencil' | 'pen' | 'marker' | 'brush'
type Preset = 'pencil' | 'ink' | 'whiteboard' | 'speed' | 'watercolor'
type DrawingJob = {
  id: string; filename?: string; status: 'queued' | 'processing' | 'done' | 'error' | 'cancelled'
  progress: number; step: string; error?: string
}

type DrawingSettings = {
  preset: Preset; mode: 'drawing' | 'hand'; tool: Tool; duration: number
  detail: number; thickness: number; fps: 24 | 30 | 60
  resolution: '720p' | '1080p' | '4k'; smartOrder: boolean; showOriginalEnd: boolean
}

const DRAWING_SETTINGS_KEY = 'zm-tool:drawing-settings:v1'
const DRAWING_JOBS_KEY = 'zm-tool:drawing-job-ids:v1'
const DEFAULT_SETTINGS: DrawingSettings = {
  preset: 'pencil', mode: 'drawing', tool: 'pencil', duration: 10, detail: 72,
  thickness: 2, fps: 30, resolution: '1080p', smartOrder: true, showOriginalEnd: true,
}

function cachedSettings(): DrawingSettings {
  try {
    const raw = window.localStorage.getItem(DRAWING_SETTINGS_KEY)
    const stored = raw ? JSON.parse(raw) as Partial<DrawingSettings> : {}
    const preset = Object.hasOwn(PRESETS, stored.preset ?? '') ? stored.preset as Preset : DEFAULT_SETTINGS.preset
    return {
      preset,
      mode: stored.mode === 'hand' ? 'hand' : stored.mode === 'drawing' ? 'drawing' : DEFAULT_SETTINGS.mode,
      tool: ['pencil', 'pen', 'marker', 'brush'].includes(stored.tool ?? '') ? stored.tool as Tool : DEFAULT_SETTINGS.tool,
      duration: Number.isFinite(stored.duration) ? Math.max(2, Math.min(60, Number(stored.duration))) : DEFAULT_SETTINGS.duration,
      detail: Number.isFinite(stored.detail) ? Math.max(10, Math.min(100, Number(stored.detail))) : DEFAULT_SETTINGS.detail,
      thickness: Number.isFinite(stored.thickness) ? Math.max(1, Math.min(8, Number(stored.thickness))) : DEFAULT_SETTINGS.thickness,
      fps: [24, 30, 60].includes(stored.fps ?? 0) ? stored.fps as 24 | 30 | 60 : DEFAULT_SETTINGS.fps,
      resolution: ['720p', '1080p', '4k'].includes(stored.resolution ?? '') ? stored.resolution as DrawingSettings['resolution'] : DEFAULT_SETTINGS.resolution,
      smartOrder: typeof stored.smartOrder === 'boolean' ? stored.smartOrder : DEFAULT_SETTINGS.smartOrder,
      showOriginalEnd: typeof stored.showOriginalEnd === 'boolean' ? stored.showOriginalEnd : DEFAULT_SETTINGS.showOriginalEnd,
    }
  } catch {
    return DEFAULT_SETTINGS
  }
}

function cachedJobIds(): string[] {
  try {
    const value = JSON.parse(window.localStorage.getItem(DRAWING_JOBS_KEY) || '[]')
    return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string').slice(0, 100) : []
  } catch {
    return []
  }
}

const PRESETS: Record<Preset, { duration: number; detail: number; thickness: number; tool: Tool; mode: 'drawing' | 'hand'; showOriginalEnd: boolean }> = {
  pencil: { duration: 10, detail: 72, thickness: 2, tool: 'pencil', mode: 'drawing', showOriginalEnd: true },
  ink: { duration: 8, detail: 84, thickness: 2, tool: 'pen', mode: 'drawing', showOriginalEnd: false },
  whiteboard: { duration: 12, detail: 55, thickness: 3, tool: 'marker', mode: 'hand', showOriginalEnd: false },
  speed: { duration: 5, detail: 68, thickness: 2, tool: 'pencil', mode: 'hand', showOriginalEnd: true },
  watercolor: { duration: 14, detail: 60, thickness: 4, tool: 'brush', mode: 'hand', showOriginalEnd: true },
}

function artifact(job: DrawingJob | null, kind: 'input' | 'lineMap' | 'strokePath' | 'output') {
  return job ? `/api/drawing/jobs/${job.id}/${kind}?t=${job.progress}` : ''
}

export default function DrawingPage({ onBack }: { onBack: () => void }) {
  const { locale } = useLocale()
  const t = (vi: string, en: string) => localize(locale, vi, en)
  const [saved] = useState(cachedSettings)
  const inputRef = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [batchFiles, setBatchFiles] = useState<File[]>([])
  const [localPreview, setLocalPreview] = useState('')
  const [previewTab, setPreviewTab] = useState<PreviewTab>('preview')
  const [preset, setPreset] = useState<Preset>(saved.preset)
  const [mode, setMode] = useState<'drawing' | 'hand'>(saved.mode)
  const [tool, setTool] = useState<Tool>(saved.tool)
  const [duration, setDuration] = useState(saved.duration)
  const [detail, setDetail] = useState(saved.detail)
  const [thickness, setThickness] = useState(saved.thickness)
  const [fps, setFps] = useState<24 | 30 | 60>(saved.fps)
  const [resolution, setResolution] = useState<'720p' | '1080p' | '4k'>(saved.resolution)
  const [smartOrder, setSmartOrder] = useState(saved.smartOrder)
  const [showOriginalEnd, setShowOriginalEnd] = useState(saved.showOriginalEnd)
  const [job, setJob] = useState<DrawingJob | null>(null)
  const [batchJobs, setBatchJobs] = useState<DrawingJob[]>([])
  const [dragging, setDragging] = useState(false)
  const [artifactError, setArtifactError] = useState<PreviewTab | null>(null)
  const [jobsRestored, setJobsRestored] = useState(false)
  const [runRequested, setRunRequested] = useState(false)

  // A selected source is saved as a queued backend job immediately.  Queued
  // means safely cached and ready to start; only processing blocks edits.
  const active = [job, ...batchJobs].some((item) => item?.status === 'processing')
  const queuedJobs = [job, ...batchJobs].filter((item): item is DrawingJob => item?.status === 'queued')
  const hasCachedSource = Boolean(job)
  const [savingSource, setSavingSource] = useState(false)
  const visual = useMemo(() => {
    if (previewTab === 'line-map' && job && artifactError !== 'line-map') return artifact(job, 'lineMap')
    if (previewTab === 'stroke-path' && job && artifactError !== 'stroke-path') return artifact(job, 'strokePath')
    return localPreview || (job ? artifact(job, 'input') : '')
  }, [artifactError, job, localPreview, previewTab])

  useEffect(() => () => { if (localPreview) URL.revokeObjectURL(localPreview) }, [localPreview])
  useEffect(() => {
    const ids = cachedJobIds()
    if (!ids.length) { setJobsRestored(true); return }
    void fetch('/api/drawing/jobs').then(async (response) => {
      if (!response.ok) return [] as DrawingJob[]
      const all = await response.json() as DrawingJob[]
      const byId = new Map(all.map((item) => [item.id, item]))
      return ids.map((id) => byId.get(id)).filter((item): item is DrawingJob => Boolean(item))
    }).then((restored) => {
      setJob(restored[0] ?? null)
      setBatchJobs(restored.slice(1))
    }).catch(() => undefined).finally(() => setJobsRestored(true))
  }, [])
  useEffect(() => {
    const settings: DrawingSettings = { preset, mode, tool, duration, detail, thickness, fps, resolution, smartOrder, showOriginalEnd }
    window.localStorage.setItem(DRAWING_SETTINGS_KEY, JSON.stringify(settings))
  }, [preset, mode, tool, duration, detail, thickness, fps, resolution, smartOrder, showOriginalEnd])
  useEffect(() => {
    if (!jobsRestored) return
    const ids = [job, ...batchJobs].filter((item): item is DrawingJob => Boolean(item)).map((item) => item.id)
    window.localStorage.setItem(DRAWING_JOBS_KEY, JSON.stringify(ids))
  }, [batchJobs, job, jobsRestored])
  useEffect(() => { setArtifactError(null) }, [job?.id, job?.progress, previewTab])
  useEffect(() => {
    const ids = [job, ...batchJobs].filter((item): item is DrawingJob => Boolean(item && (item.status === 'processing' || (runRequested && item.status === 'queued')))).map((item) => item.id)
    if (!ids.length) return
    const timer = window.setInterval(async () => {
      const results = await Promise.all(ids.map(async (id) => {
        const response = await fetch(`/api/drawing/jobs/${id}`)
        return response.ok ? await response.json() as DrawingJob : null
      }))
      const updates = new Map(results.filter((item): item is DrawingJob => Boolean(item)).map((item) => [item.id, item]))
      if (!updates.size) return
      setJob((current) => current ? updates.get(current.id) ?? current : current)
      setBatchJobs((current) => current.map((item) => updates.get(item.id) ?? item))
    }, 800)
    return () => window.clearInterval(timer)
  }, [active, batchJobs, job?.id, runRequested])
  useEffect(() => {
    if (runRequested && [job, ...batchJobs].every((item) => !item || ['done', 'error', 'cancelled'].includes(item.status))) setRunRequested(false)
  }, [batchJobs, job, runRequested])

  const selectFiles = async (next: FileList | File[] | null | undefined) => {
    const accepted = Array.from(next ?? []).filter((item) => item.type.startsWith('image/'))
    if (!accepted.length) return
    setFile(accepted[0])
    setBatchFiles(accepted)
    setArtifactError(null)
    setPreviewTab('preview')
    setLocalPreview(URL.createObjectURL(accepted[0]))
    setSavingSource(true)
    try {
      const body = new FormData()
      accepted.forEach((item) => body.append('images', item))
      body.append('options', JSON.stringify({ preset, mode, tool, duration, detail, thickness, fps, resolution, smartOrder, showOriginalEnd }))
      body.append('start_now', 'false')
      const response = await fetch('/api/drawing/jobs/batch', { method: 'POST', body })
      if (!response.ok) throw new Error(await response.text())
      const result = await response.json() as { jobs: DrawingJob[] }
      setJob(result.jobs[0] ?? null)
      setBatchJobs(result.jobs.slice(1))
      setRunRequested(false)
    } catch (error) {
      setJob({ id: '', status: 'error', progress: 0, step: 'error', error: error instanceof Error ? error.message : String(error) })
      setBatchJobs([])
    } finally {
      setSavingSource(false)
    }
  }
  const applyPreset = (id: Preset) => {
    const value = PRESETS[id]
    setPreset(id); setDuration(value.duration); setDetail(value.detail); setThickness(value.thickness)
    setTool(value.tool); setMode(value.mode); setShowOriginalEnd(value.showOriginalEnd)
  }
  const generate = async () => {
    if (!queuedJobs.length || active || savingSource) return
    try {
      const options = { preset, mode, tool, duration, detail, thickness, fps, resolution, smartOrder, showOriginalEnd }
      const updates = await Promise.all(queuedJobs.map(async (item) => {
        const response = await fetch(`/api/drawing/jobs/${item.id}`, {
          method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(options),
        })
        if (!response.ok) throw new Error(await response.text())
        return await response.json() as DrawingJob
      }))
      const response = await fetch('/api/drawing/jobs/start', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ids: updates.map((item) => item.id) }),
      })
      if (!response.ok) throw new Error(await response.text())
      setJob(updates[0] ?? null)
      setBatchJobs(updates.slice(1))
      setRunRequested(true)
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      setJob((current) => current ? { ...current, error: message } : { id: '', status: 'error', progress: 0, step: 'error', error: message })
    }
  }
  const cancelJob = async (jobId: string) => {
    await fetch(`/api/drawing/jobs/${jobId}/cancel`, { method: 'POST' })
    setJob((current) => current?.id === jobId ? { ...current, status: 'cancelled' } : current)
    setBatchJobs((current) => current.map((item) => item.id === jobId ? { ...item, status: 'cancelled' } : item))
  }
  const statusText = job?.status === 'done' ? t('Video đã sẵn sàng', 'Video ready')
    : job?.status === 'error' ? t('Không thể tạo video', 'Could not create video')
    : job?.status === 'cancelled' ? t('Đã hủy', 'Cancelled')
    : job?.step === 'line_map' ? t('Đang tách nét từ ảnh', 'Extracting lines from image')
    : job?.step === 'stroke_path' ? t('Đang sắp thứ tự nét vẽ', 'Ordering drawing strokes')
    : job?.step === 'ink' ? t('Đang vẽ từng nét', 'Drawing stroke by stroke')
    : job?.step === 'color' ? t('Đang tô màu', 'Adding colour')
    : job?.step === 'encoding' ? t('Đang mã hóa video', 'Encoding video')
    : savingSource ? t('Đang lưu ảnh vào hàng đợi', 'Saving image to queue')
    : queuedJobs.length ? t('Đã lưu, sẵn sàng tạo video', 'Saved, ready to create video')
    : active ? t('Đang tạo video vẽ tay', 'Creating drawing video') : t('Sẵn sàng render cục bộ', 'Ready for local rendering')

  return (
    <main className="drawing-page">
      <div className="drawing-head">
        <BackTitle onBack={onBack}>{t('Vẽ tay', 'Drawing')}</BackTitle>
        <p>{t('Ảnh → Video vẽ tay', 'Image → Drawing Video')}</p>
      </div>
      <div className="drawing-grid">
        <section className="drawing-card drawing-input-card">
          <h2>{t('Ảnh nguồn', 'Source image')}</h2>
          <button className={`drawing-dropzone${dragging ? ' is-dragging' : ''}`} type="button"
            onClick={() => inputRef.current?.click()} onDragOver={(event) => { event.preventDefault(); setDragging(true) }}
            onDragLeave={() => setDragging(false)} onDrop={(event: DragEvent<HTMLButtonElement>) => { event.preventDefault(); setDragging(false); void selectFiles(event.dataTransfer.files) }}>
            {localPreview ? <img src={localPreview} alt="" /> : <><b>＋</b><strong>{t('Kéo ảnh vào đây', 'Drop an image here')}</strong><span>JPG · PNG · WebP</span></>}
          </button>
          <input ref={inputRef} className="drawing-visually-hidden" type="file" multiple accept="image/jpeg,image/png,image/webp,image/bmp" onChange={(event) => void selectFiles(event.target.files)} />
          {file ? <div className="drawing-file"><span>{batchFiles.length > 1 ? t(`${batchFiles.length} ảnh đã chọn`, `${batchFiles.length} images selected`) : file.name}</span><button type="button" onClick={() => { setFile(null); setBatchFiles([]); setJob(null); setBatchJobs([]); setLocalPreview('') }}>{t('Đổi ảnh', 'Change')}</button></div> : null}
          <label className="drawing-field"><span>{t('Chế độ vẽ', 'Drawing mode')}</span><select value={mode} onChange={(event) => setMode(event.target.value as 'drawing' | 'hand')}><option value="drawing">{t('Vẽ nét liên tục', 'Continuous strokes')}</option><option value="hand">{t('Tay cầm bút vẽ nét', 'Hand drawing strokes')}</option></select></label>
          <span className="drawing-label">{t('Loại dụng cụ', 'Tool')}</span>
          <div className="drawing-tools">{(['pencil', 'pen', 'marker', 'brush'] as Tool[]).map((id) => <button key={id} type="button" className={tool === id ? 'is-active' : ''} onClick={() => setTool(id)}>{({ pencil: t('Chì', 'Pencil'), pen: t('Bút', 'Pen'), marker: 'Marker', brush: t('Cọ', 'Brush') })[id]}</button>)}</div>
          <label className="drawing-toggle"><input type="checkbox" checked={smartOrder} onChange={(event) => setSmartOrder(event.target.checked)} /><span>{t('Thứ tự nét thông minh', 'Smart stroke order')}</span></label>
          <label className="drawing-toggle"><input type="checkbox" checked={showOriginalEnd} onChange={(event) => setShowOriginalEnd(event.target.checked)} /><span>{t('Hiện ảnh gốc ở cuối', 'Reveal original at end')}</span></label>
        </section>

        <section className="drawing-card drawing-preview-card">
          <div className="drawing-preview-tabs" role="tablist">
            {([{ id: 'preview', vi: 'Xem trước', en: 'Preview' }, { id: 'line-map', vi: 'Bản đồ nét', en: 'Line Map' }, { id: 'stroke-path', vi: 'Đường nét', en: 'Stroke Path' }] as const).map((item) => <button key={item.id} type="button" className={previewTab === item.id ? 'is-active' : ''} onClick={() => setPreviewTab(item.id)}>{t(item.vi, item.en)}</button>)}
          </div>
          <div className={`drawing-canvas drawing-canvas--${previewTab}`}>
            {visual ? <img src={visual} alt={t('Xem trước ảnh vẽ', 'Drawing image preview')} onError={() => {
              if (previewTab !== 'preview') setArtifactError(previewTab)
            }} /> : <div>{t('Chọn một ảnh để bắt đầu', 'Choose an image to begin')}</div>}
          </div>
          <div className="drawing-progress"><span style={{ width: `${job?.progress ?? 0}%` }} /></div>
          <div className="drawing-stats"><div><span>{t('Trạng thái', 'Status')}</span><strong>{statusText}</strong></div><div><span>{t('Chế độ', 'Mode')}</span><strong>{mode === 'hand' ? t('Tay + bút', 'Hand + pen') : t('Vẽ nét', 'Stroke drawing')}</strong></div><div><span>{t('Ước tính', 'Estimate')}</span><strong>{duration}s · {fps} FPS</strong></div></div>
          {job?.status === 'done' ? <video className="drawing-result" controls src={artifact(job, 'output')} /> : null}
          {job?.error ? <p className="drawing-error">{job.error}</p> : null}
        </section>

        <section className="drawing-card drawing-settings-card">
          <h2>{t('Xuất video', 'Video export')}</h2>
          <label className="drawing-field"><span>Preset</span><select value={preset} onChange={(event) => applyPreset(event.target.value as Preset)}><option value="pencil">{t('Chì chân dung', 'Portrait pencil')}</option><option value="ink">{t('Nét mực', 'Ink line art')}</option><option value="whiteboard">Whiteboard</option><option value="speed">{t('Vẽ nhanh', 'Speed drawing')}</option><option value="watercolor">{t('Lộ màu nước', 'Watercolor reveal')}</option></select></label>
          <Range label={t('Thời lượng', 'Duration')} value={duration} min={2} max={60} suffix={t(' giây', ' sec')} onChange={setDuration} />
          <Range label={t('Độ chi tiết', 'Detail')} value={detail} min={10} max={100} suffix="%" onChange={setDetail} />
          <Range label={t('Độ dày nét', 'Stroke thickness')} value={thickness} min={1} max={8} suffix=" px" onChange={setThickness} />
          <div className="drawing-setting-row"><label className="drawing-field"><span>FPS</span><select value={fps} onChange={(event) => setFps(Number(event.target.value) as 24 | 30 | 60)}><option value="24">24</option><option value="30">30</option><option value="60">60</option></select></label><label className="drawing-field"><span>{t('Độ phân giải', 'Resolution')}</span><select value={resolution} onChange={(event) => setResolution(event.target.value as '720p' | '1080p' | '4k')}><option value="720p">720p</option><option value="1080p">1080p</option><option value="4k">4K</option></select></label></div>
          <button className="drawing-generate" type="button" disabled={!hasCachedSource || !queuedJobs.length || active || savingSource} onClick={() => void generate()}>{savingSource ? t('Đang lưu ảnh…', 'Saving image…') : active ? `${Math.round(job?.progress ?? 0)}% · ${t('Đang tạo', 'Creating')}` : batchFiles.length > 1 ? t(`▶ Vẽ tay hàng loạt (${batchFiles.length})`, `▶ Batch draw (${batchFiles.length})`) : t('▶ Tạo video vẽ tay', '▶ Create drawing video')}</button>
          {(active || queuedJobs.length) ? <button className="drawing-cancel" type="button" onClick={() => [job, ...batchJobs].filter((item): item is DrawingJob => Boolean(item && (item.status === 'queued' || item.status === 'processing'))).forEach((item) => void cancelJob(item.id))}>{t('Hủy tất cả', 'Cancel all')}</button> : null}
          {job?.status === 'done' ? <a className="drawing-download" href={artifact(job, 'output')} download>{t('Tải video MP4', 'Download MP4 video')}</a> : null}
          {batchJobs.length ? <div className="drawing-batch" aria-label={t('Tiến độ vẽ tay hàng loạt', 'Batch drawing progress')}><b>{t('Hàng loạt · chạy tuần tự', 'Batch · sequential rendering')}</b>{[job, ...batchJobs].filter((item): item is DrawingJob => Boolean(item)).map((item, index) => <div key={item.id}><span>{index + 1}. {item.filename || (index === 0 ? file?.name : batchFiles[index]?.name) || t('Ảnh vẽ tay', 'Drawing image')}</span><em>{item.status === 'done' ? t('Xong', 'Done') : item.status === 'cancelled' ? t('Đã hủy', 'Cancelled') : item.status === 'error' ? t('Lỗi', 'Error') : `${item.progress}%`}</em>{item.status === 'queued' || item.status === 'processing' ? <button type="button" onClick={() => void cancelJob(item.id)}>{t('Hủy', 'Cancel')}</button> : null}</div>)}</div> : null}
        </section>
      </div>
      <footer className="drawing-pipeline">{t('Pipeline: Ảnh → Line/Stroke → Sắp thứ tự nét → Animation → Tay/Bút (tùy chọn) → Màu → MP4', 'Pipeline: Image → Line/Stroke → Stroke order → Animation → Hand/Pen (optional) → Color → MP4')}</footer>
    </main>
  )
}

function Range({ label, value, min, max, suffix, onChange }: { label: string; value: number; min: number; max: number; suffix: string; onChange: (value: number) => void }) {
  return <label className="drawing-range"><span><b>{label}</b><em>{value}{suffix}</em></span><input type="range" min={min} max={max} value={value} onChange={(event) => onChange(Number(event.target.value))} /></label>
}
