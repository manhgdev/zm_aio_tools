import { Fragment, useCallback, useEffect, useRef, useState } from 'react'
import { localize, useLocale } from '@/app/i18n'
import { FLOW_IMAGE_MODELS } from '@/features/flow/flow.helpers'
import { ConfirmDialog } from '@/shared/components/ConfirmDialog'
import { MediaPreviewModal, type MediaPreviewAction, type MediaPreviewItem } from '@/shared/components/MediaPreviewModal'
import { OutputFolderField } from '@/shared/components/OutputFolderField'
import './AutomationPage.css'

type InputMode = 'topic' | 'ai_topic' | 'script' | 'bundle'
type AutomationSettingsTab = 'text' | 'tts' | 'flow' | 'compose'
type JobStatus = 'queued' | 'running' | 'awaiting_topic' | 'paused' | 'interrupted' | 'completed' | 'cancelled' | 'failed'
type AutomationJob = {
  id: string
  title: string
  input_mode: InputMode
  status: JobStatus
  stage: string
  progress: number
  input?: { topic?: string; selectedTopic?: string; topicCandidates?: string[]; script?: string; audio?: string; srt?: string; prompts?: string }
  settings?: Partial<AutomationSettings>
  artifacts?: Record<string, { available?: boolean; filename?: string }>
  error?: { code?: string; message?: string } | null
  logs?: { id?: number; level: string; stage: string; message: string; createdAt?: string }[]
}

type AutomationSettings = {
  language: 'vi' | 'en'
  textProvider: string
  textModel: string
  chatModel: string
  systemPrompt?: string
  tts: { voice: string; speed: number; volume: number; pitch: number; style: string }
  flow: { accountId: string; model: string; ratio: string; resolution: string; concurrency: string; promptEngine: 'vi' | 'en'; count?: string }
  compose: {
    resolution: string; targetPlatform: string; fps: number; crf: number; encoder: 'auto' | 'gpu' | 'cpu'
    effect: string; transitionDuration: number; zoom: string; speed: number; volume: number; previewSeconds: number
    allowMissingMedia: boolean; subtitleEnabled: boolean; removeMetadata: boolean
    subtitleFontFamily: string; subtitleSize: number; subtitleOffset: number; subtitleMargin: number
    subtitleBackground: string; subtitleColor: string; subtitleBgColor: string; subtitleOpacity: number
    drawingEnabled: boolean; drawingMode: string; drawingTool: string; drawingDetail: number; drawingThickness: number; drawingStrokeOrder: string
    delogoEnabled: boolean; delogoAuto: boolean; delogoX: number; delogoY: number; delogoW: number; delogoH: number
    logoEnabled: boolean; logoSource: 'text' | 'image' | 'icon'; logoText: string; logoIcon: string; logoFontSize: number; logoColor: string; logoSize: number; logoOpacity: number; logoX: number; logoY: number; logoMotion: string; logoScope: string; logoStart: number; logoEnd: number; logoVisibleSec: number; logoHiddenSec: number; logoFadeSec: number; logoSafeMargin: number
  }
  outputDir: string
}

type FlowAccountOption = {
  id: string
  label: string
  status: string
  plan?: string
  credits?: number | null
  isDefault?: boolean
}

type TtsVoiceOption = {
  id: string
  name?: string
  label?: string
  engine?: string
  language?: string
  available?: boolean
}
type ChatModelOption = { id: string; label: string; provider: string; free: boolean; capabilities?: string[]; available?: boolean }
type ChatProviderOption = { id: string; label: string; kind: 'api' | 'browser'; configured: boolean; status: string; models: ChatModelOption[] }

const API = '/api/automation'
const fetchWithTimeout = (input: RequestInfo | URL, init: RequestInit = {}, timeoutMs = 8000) =>
  fetch(input, { ...init, signal: init.signal || AbortSignal.timeout(timeoutMs) })
const AUTOMATION_SETTINGS_OPEN_KEY = 'videoclone.automation-settings-open.v1'
const AUTOMATION_PANEL_WIDTH_KEY = 'videoclone.automation-panel-width.v1'
const AUTOMATION_SETTINGS_TAB_KEY = 'videoclone.automation-settings-tab.v1'
const DEFAULT_SETTINGS: AutomationSettings = {
  language: 'vi', textProvider: 'openrouter', textModel: 'openrouter/free', chatModel: 'GPT-5.6 Sol',
  tts: { voice: 'system', speed: 1, volume: 1, pitch: 0, style: 'tu_nhien' },
  flow: { accountId: '', model: 'Nano Banana 2', ratio: '16:9', resolution: '1K', concurrency: '3', promptEngine: 'vi', count: '1' },
  compose: { resolution: 'auto', targetPlatform: 'auto', fps: 30, crf: 20, encoder: 'auto', effect: 'none', transitionDuration: .28, zoom: 'off', speed: 100, volume: 100, previewSeconds: 0, allowMissingMedia: false, subtitleEnabled: true, removeMetadata: false, subtitleFontFamily: 'system', subtitleSize: 8, subtitleOffset: 0, subtitleMargin: 34, subtitleBackground: 'solid', subtitleColor: '#ffffff', subtitleBgColor: '#000000', subtitleOpacity: 55, drawingEnabled: false, drawingMode: 'hand', drawingTool: 'pencil', drawingDetail: 72, drawingThickness: 2, drawingStrokeOrder: 'natural', delogoEnabled: false, delogoAuto: true, delogoX: 80, delogoY: 82, delogoW: 18, delogoH: 12, logoEnabled: false, logoSource: 'text', logoText: 'ZM AIO TOOL', logoIcon: '★', logoFontSize: 32, logoColor: '#ffffff', logoSize: 8, logoOpacity: 85, logoX: 88, logoY: 88, logoMotion: 'fixed', logoScope: 'full', logoStart: 0, logoEnd: 10, logoVisibleSec: 4, logoHiddenSec: 2, logoFadeSec: .5, logoSafeMargin: 4 }, outputDir: '',
}

const modeLabel = (mode: InputMode, t: (vi: string, en: string) => string) => ({
  topic: t('Chủ đề', 'Topic'),
  ai_topic: t('AI đề xuất chủ đề', 'AI topic ideas'),
  script: t('Đã có script', 'Existing script'),
  bundle: t('Đã có bộ file', 'Existing bundle'),
}[mode])

const stageLabel = (stage: string, t: (vi: string, en: string) => string) => ({
  input: t('Chuẩn bị đầu vào', 'Preparing input'), topic: t('Chọn chủ đề', 'Choose topic'), script: t('Tạo script', 'Creating script'),
  tts: t('Tạo audio + SRT', 'Creating audio + SRT'), srt: t('Chuẩn bị SRT', 'Preparing SRT'), image_prompt: t('Tạo prompt ảnh', 'Creating image prompts'),
  flow_images: t('Tạo ảnh bằng Flow', 'Generating images with Flow'), compose: t('Ghép video SRT', 'Composing SRT video'), done: t('Hoàn thành', 'Complete'),
}[stage] || stage)

const statusLabel = (status: JobStatus, t: (vi: string, en: string) => string) => ({
  queued: t('Đang xếp hàng', 'Queued'), running: t('Đang chạy', 'Running'), awaiting_topic: t('Chờ chọn chủ đề', 'Waiting for topic'),
  paused: t('Tạm dừng do lỗi', 'Paused on error'), interrupted: t('Bị gián đoạn', 'Interrupted'), completed: t('Hoàn thành', 'Completed'),
  cancelled: t('Đã hủy', 'Cancelled'), failed: t('Thất bại', 'Failed'),
}[status])

function mergeSettings(value: Partial<AutomationSettings>): AutomationSettings {
  const merged = {
    ...DEFAULT_SETTINGS, ...value,
    tts: { ...DEFAULT_SETTINGS.tts, ...(value.tts || {}) },
    flow: { ...DEFAULT_SETTINGS.flow, ...(value.flow || {}) },
    compose: { ...DEFAULT_SETTINGS.compose, ...(value.compose || {}) },
  }
  if (!value.textProvider && value.chatModel) {
    merged.textProvider = 'chatgpt_web'
    merged.textModel = value.chatModel
  }
  return merged
}

function normalizeFlowAccounts(raw: unknown): FlowAccountOption[] {
  const rows = raw && typeof raw === 'object' && Array.isArray((raw as { accounts?: unknown }).accounts)
    ? (raw as { accounts: unknown[] }).accounts
    : []
  return rows.reduce<FlowAccountOption[]>((result, item) => {
    if (!item || typeof item !== 'object') return result
    const row = item as Record<string, unknown>
    const id = String(row.id || '').trim()
    const label = String(row.label || row.email || id).trim()
    if (!id || !label || result.some((account) => account.id === id)) return result
    result.push({
      id,
      label,
      status: String(row.status || ''),
      plan: row.plan ? String(row.plan) : undefined,
      credits: typeof row.credits === 'number' ? row.credits : null,
      isDefault: Boolean(row.isDefault),
    })
    return result
  }, [])
}

function normalizeTtsVoices(raw: unknown): TtsVoiceOption[] {
  if (!Array.isArray(raw)) return []
  return raw.reduce<TtsVoiceOption[]>((result, item) => {
    if (!item || typeof item !== 'object') return result
    const row = item as Record<string, unknown>
    const id = String(row.id || '').trim()
    if (!id || result.some((voice) => voice.id === id)) return result
    result.push({
      id,
      name: row.name ? String(row.name) : undefined,
      label: row.label ? String(row.label) : undefined,
      engine: row.engine ? String(row.engine) : undefined,
      language: row.language ? String(row.language) : undefined,
      available: row.available !== false,
    })
    return result
  }, [])
}

function normalizeChatProviders(raw: unknown): ChatProviderOption[] {
  const values = raw && typeof raw === 'object' && Array.isArray((raw as { providers?: unknown }).providers)
    ? (raw as { providers: unknown[] }).providers : []
  return values.reduce<ChatProviderOption[]>((result, item) => {
    if (!item || typeof item !== 'object') return result
    const row = item as Record<string, unknown>
    const id = String(row.id || '').trim()
    if (!id || result.some(current => current.id === id)) return result
    const models = Array.isArray(row.models) ? row.models.reduce<ChatModelOption[]>((items, value) => {
      if (!value || typeof value !== 'object') return items
      const model = value as Record<string, unknown>
      const modelId = String(model.id || '').trim()
      if (!modelId || items.some(current => current.id === modelId)) return items
      items.push({ id: modelId, label: String(model.label || modelId), provider: String(model.provider || id), free: model.free !== false, capabilities: Array.isArray(model.capabilities) ? model.capabilities.map(String) : ['text'], available: model.available !== false })
      return items
    }, []) : []
    result.push({ id, label: String(row.label || id), kind: row.kind === 'browser' ? 'browser' : 'api', configured: row.configured !== false, status: String(row.status || ''), models })
    return result
  }, [])
}

export default function AutomationPage() {
  const { locale } = useLocale()
  const t = (vi: string, en: string) => localize(locale, vi, en)
  const [mode, setMode] = useState<InputMode>('topic')
  const [title, setTitle] = useState('')
  const [topic, setTopic] = useState('')
  const [settings, setSettings] = useState<AutomationSettings>(DEFAULT_SETTINGS)
  const [chatProviders, setChatProviders] = useState<ChatProviderOption[]>([])
  const [chatModelsLoading, setChatModelsLoading] = useState(true)
  const [flowAccounts, setFlowAccounts] = useState<FlowAccountOption[]>([])
  const [ttsVoices, setTtsVoices] = useState<TtsVoiceOption[]>([])
  const [voiceSearch, setVoiceSearch] = useState('')
  const [optionsLoading, setOptionsLoading] = useState(true)
  const [jobs, setJobs] = useState<AutomationJob[]>([])
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [editingJobId, setEditingJobId] = useState('')
  const [deleteTarget, setDeleteTarget] = useState<AutomationJob | null>(null)
  const [videoPreview, setVideoPreview] = useState<MediaPreviewItem | null>(null)
  const [textPreview, setTextPreview] = useState<string | null>(null)
  const [textPreviewSaving, setTextPreviewSaving] = useState(false)
  const [isDesktopApp, setIsDesktopApp] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(() => {
    try { return window.localStorage.getItem(AUTOMATION_SETTINGS_OPEN_KEY) !== '0' } catch { return true }
  })
  const [settingsTab, setSettingsTab] = useState<AutomationSettingsTab>(() => {
    try {
      const value = window.localStorage.getItem(AUTOMATION_SETTINGS_TAB_KEY)
      return value === 'tts' || value === 'flow' || value === 'compose' ? value : 'text'
    } catch { return 'text' }
  })
  const selectSettingsTab = (next: AutomationSettingsTab) => {
    setSettingsTab(next)
    try { window.localStorage.setItem(AUTOMATION_SETTINGS_TAB_KEY, next) } catch { /* storage unavailable */ }
  }
  const [builderWidth, setBuilderWidth] = useState(() => {
    try {
      const saved = Number(window.localStorage.getItem(AUTOMATION_PANEL_WIDTH_KEY))
      return Number.isFinite(saved) ? Math.max(320, Math.min(520, saved)) : 400
    } catch { return 400 }
  })
  const panelDrag = useRef<{ startX: number; startWidth: number } | null>(null)

  useEffect(() => {
    const onMove = (event: PointerEvent) => {
      const drag = panelDrag.current
      if (!drag) return
      setBuilderWidth(Math.max(320, Math.min(520, drag.startWidth + event.clientX - drag.startX)))
    }
    const onUp = () => {
      if (!panelDrag.current) return
      panelDrag.current = null
      document.body.classList.remove('automation-resizing')
      try { localStorage.setItem(AUTOMATION_PANEL_WIDTH_KEY, String(builderWidth)) } catch { /* storage unavailable */ }
    }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
    return () => { window.removeEventListener('pointermove', onMove); window.removeEventListener('pointerup', onUp) }
  }, [builderWidth])

  const [files, setFiles] = useState<Record<string, File | null>>({ script: null, audio: null, srt: null, prompts: null, watermark: null })
  const providerName = (id: string) => ({
    chatgpt_web: t('ChatGPT API', 'ChatGPT API'), openai: t('OpenAI API', 'OpenAI API'), gemini: 'Gemini',
    deepseek: 'DeepSeek', openrouter: 'OpenRouter', grok: 'Grok (xAI)', groq: 'Groq', nvidia: t('NVIDIA NIM', 'NVIDIA NIM'),
  } as Record<string, string>)[id] || id
  const refresh = useCallback(async () => {
    try {
      const response = await fetchWithTimeout(`${API}/jobs`)
      if (!response.ok) throw new Error(await response.text())
      const data = await response.json() as { jobs?: AutomationJob[] }
      setJobs(Array.isArray(data.jobs) ? data.jobs : [])
      setError('')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t('Không tải được danh sách job.', 'Could not load jobs.'))
    } finally { setLoading(false) }
  }, [locale])

  useEffect(() => {
    void Promise.all([
      fetchWithTimeout(`${API}/settings`).then(response => response.ok ? response.json() as Promise<Partial<AutomationSettings>> : null).then(value => { if (value) setSettings(mergeSettings(value)) }).catch(() => undefined),
      fetchWithTimeout('/api/config').then(async (r) => r.ok && setIsDesktopApp(Boolean((await r.json() as { desktop?: boolean }).desktop))).catch(() => undefined),
      refresh(),
    ])
  }, [refresh])

  useEffect(() => {
    let active = true
    setChatModelsLoading(true)
    void fetchWithTimeout('/api/chat/providers').then(response => response.ok ? response.json() as Promise<unknown> : null).then(raw => {
      if (!active) return
      const available = normalizeChatProviders(raw)
      setChatProviders(available)
      setSettings(current => {
        const currentProvider = available.find(item => item.id === current.textProvider && (item.status === 'ready' || (item.id === 'chatgpt_web' && item.configured)))
        const preferred = currentProvider || available.find(item => item.id === 'chatgpt_web' && item.configured) || available.find(item => item.status === 'ready')
        if (!preferred) return current
        const model = preferred.models.some(item => item.id === current.textModel) ? current.textModel : (preferred.models[0]?.id || current.textModel)
        return { ...current, textProvider: preferred.id, textModel: model, chatModel: preferred.id === 'chatgpt_web' ? model : current.chatModel }
      })
    }).catch(() => {
      if (active) setChatProviders([])
    }).finally(() => {
      if (active) setChatModelsLoading(false)
    })
    return () => { active = false }
  }, [locale])

  useEffect(() => {
    let active = true
    setOptionsLoading(true)
    void Promise.all([
      fetchWithTimeout('/api/flow/accounts').then(response => response.ok ? response.json() as Promise<unknown> : null),
      fetchWithTimeout('/api/voices?lang=all').then(response => response.ok ? response.json() as Promise<unknown> : null),
    ]).then(([accounts, voices]) => {
      if (!active) return
      setFlowAccounts(normalizeFlowAccounts(accounts))
      setTtsVoices(normalizeTtsVoices(voices))
    }).catch(() => {
      if (active) setError(t('Không tải được tài khoản Flow hoặc danh sách giọng TTS.', 'Could not load Flow accounts or TTS voices.'))
    }).finally(() => {
      if (active) setOptionsLoading(false)
    })
    return () => { active = false }
  }, [locale])

  useEffect(() => {
    const online = flowAccounts.filter(account => account.status === 'online')
    if (!online.length || online.some(account => account.id === settings.flow.accountId)) return
    const preferred = online.find(account => account.isDefault) || online[0]
    setSettings(current => ({ ...current, flow: { ...current.flow, accountId: preferred.id } }))
  }, [flowAccounts, settings.flow.accountId])

  useEffect(() => {
    if (!ttsVoices.length || ttsVoices.some(voice => voice.id === settings.tts.voice)) return
    setSettings(current => ({ ...current, tts: { ...current.tts, voice: ttsVoices[0].id } }))
  }, [settings.tts.voice, ttsVoices])

  useEffect(() => {
    const active = jobs.some(job => job.status === 'queued' || job.status === 'running' || job.status === 'awaiting_topic')
    if (!active) return undefined
    const timer = window.setInterval(() => void refresh(), 1000)
    return () => window.clearInterval(timer)
  }, [jobs, refresh])

  const previewArtifact = (key: string, href: string, label: string) => {
    if (key === 'images') {
      window.history.pushState({ appMode: 'flow' }, '', '/flow-veo?p=queue')
      window.dispatchEvent(new PopStateEvent('popstate'))
      return
    }
    if (key === 'audio' || key === 'audioMp3') {
      setTextPreview(null)
      setVideoPreview({ title: label, src: href, type: 'audio' })
      return
    }
    if (key === 'srt') {
      void fetch(href).then(r => r.ok ? r.text() : Promise.reject(new Error('preview failed'))).then(text => {
        setTextPreview(text)
        setVideoPreview({ title: label, src: href, type: 'srt' })
      }).catch(() => setError(t('Không đọc được nội dung file.', 'Could not read the file content.')))
      return
    }
    setTextPreview(null)
    setVideoPreview({ title: label, src: href, type: 'video' })
  }



  const saveSettings = async (next: AutomationSettings) => {
    setSettings(next)
    try {
      const response = await fetch(`${API}/settings`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(next) })
      if (!response.ok) throw new Error(await response.text())
      if (editingJobId) {
        const jobResponse = await fetch(`${API}/jobs/${encodeURIComponent(editingJobId)}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ settings: next }) })
        if (!jobResponse.ok) throw new Error(t('Không lưu được cài đặt job.', 'Could not save job settings.'))
      }
    } catch (cause) { setError(cause instanceof Error ? cause.message : t('Không lưu được cài đặt.', 'Could not save settings.')) }
  }

  const saveTextPreview = async () => {
    if (!videoPreview || textPreview === null) return
    const match = videoPreview.src.match(/\/api\/automation\/jobs\/([^/]+)\/artifacts\/([^/?]+)/)
    if (!match) return
    setTextPreviewSaving(true)
    try {
      const response = await fetch(`${API}/jobs/${encodeURIComponent(match[1])}/artifacts/${encodeURIComponent(match[2])}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: textPreview }),
      })
      if (!response.ok) throw new Error(t('Không lưu được file.', 'Could not save the file.'))
      setNotice(t('Đã lưu file.', 'File saved.'))
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t('Không lưu được file.', 'Could not save the file.'))
    } finally {
      setTextPreviewSaving(false)
    }
  }

  const submit = async () => {
    setSubmitting(true); setError(''); setEditingJobId('')
    const body = new FormData()
    body.set('inputMode', mode); body.set('title', title.trim() || topic.trim().slice(0, 80) || t('Job tự động hoá', 'Automation job')); body.set('topic', topic.trim()); body.set('settings', JSON.stringify(settings)); body.set('startNow', 'true')
    for (const [key, file] of Object.entries(files)) if (file) body.append(key, file)
    try {
      const response = await fetch(`${API}/jobs`, { method: 'POST', body })
      const data = await response.json().catch(() => ({})) as { status?: JobStatus; detail?: { message?: string } }
      if (!response.ok) throw new Error(data.detail?.message || t('Không tạo được job.', 'Could not create job.'))
      setTitle(''); setTopic(''); setFiles({ script: null, audio: null, srt: null, prompts: null, watermark: null }); await refresh()
      setNotice(mode === 'ai_topic' || data.status === 'awaiting_topic'
        ? t('Đã tạo job. AI sẽ đề xuất đúng 5 chủ đề; chọn một chủ đề để chạy tiếp.', 'Job created. AI will suggest exactly 5 topics; choose one to continue.')
        : t('Đã thêm job vào hàng đợi.', 'Job added to the queue.'))
      window.setTimeout(() => setNotice(''), 5000)
    } catch (cause) { setError(cause instanceof Error ? cause.message : t('Không tạo được job.', 'Could not create job.')) }
    finally { setSubmitting(false) }
  }

  const mutate = async (id: string, action: 'pause' | 'resume' | 'retry' | 'cancel') => {
    setError('')
    try {
      const response = await fetch(`${API}/jobs/${encodeURIComponent(id)}/${action}`, { method: 'POST' })
      if (!response.ok) throw new Error((await response.json().catch(() => ({})) as { detail?: { message?: string } }).detail?.message || t('Không cập nhật được job.', 'Could not update job.'))
      await refresh()
    } catch (cause) { setError(cause instanceof Error ? cause.message : t('Không cập nhật được job.', 'Could not update job.')) }
  }

  const removeJob = (job: AutomationJob) => setDeleteTarget(job)

  const confirmRemoveJob = async () => {
    const job = deleteTarget
    setDeleteTarget(null)
    if (!job) return
    setError('')
    try {
      const response = await fetch(`${API}/jobs/${encodeURIComponent(job.id)}`, { method: 'DELETE' })
      if (!response.ok) throw new Error((await response.json().catch(() => ({})) as { detail?: { message?: string } }).detail?.message || t('Không xoá được job.', 'Could not delete the job.'))
      await refresh()
      setNotice(t('Đã xoá job.', 'Job deleted.'))
      window.setTimeout(() => setNotice(''), 3000)
    } catch (cause) { setError(cause instanceof Error ? cause.message : t('Không xoá được job.', 'Could not delete the job.')) }
  }

  const chooseTopic = async (job: AutomationJob, value: string) => {
    try {
      const response = await fetch(`${API}/jobs/${encodeURIComponent(job.id)}/select-topic`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ topic: value }) })
      if (!response.ok) throw new Error(t('Không chọn được chủ đề.', 'Could not select the topic.'))
      await refresh()
    } catch (cause) { setError(cause instanceof Error ? cause.message : t('Không chọn được chủ đề.', 'Could not select the topic.')) }
  }

  const openFolder = async (job: AutomationJob) => {
    try {
      const response = await fetch(`${API}/jobs/${encodeURIComponent(job.id)}/open-folder`, { method: 'POST' })
      if (!response.ok) throw new Error(t('Không mở được thư mục đầu ra.', 'Could not open the output folder.'))
    } catch (cause) { setError(cause instanceof Error ? cause.message : t('Không mở được thư mục đầu ra.', 'Could not open the output folder.')) }
  }

  const editJob = async (job: AutomationJob) => {
    setMode(job.input_mode); setTitle(job.title); setTopic(job.input?.topic || job.input?.selectedTopic || ''); setEditingJobId(job.id)
    const nextSettings = mergeSettings(job.settings || {})
    setSettings(nextSettings)
    if (job.input) setNotice(t('Đã nạp thông tin job vào form; chọn file mới nếu cần rồi lưu cài đặt trước khi chạy lại.', 'Job details loaded into the form; choose replacement files if needed, then save settings before retrying.'))
    if (job.error) setError(t('Bạn có thể chỉnh cài đặt ở form bên trái rồi bấm Chạy lại chặng lỗi.', 'Edit the settings in the form on the left, then retry the failed stage.'))
    try {
      const response = await fetch(`${API}/jobs/${encodeURIComponent(job.id)}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title: job.title, settings: nextSettings }) })
      if (!response.ok) throw new Error(t('Không lưu được cài đặt job.', 'Could not save job settings.'))
      await refresh()
    } catch (cause) { setError(cause instanceof Error ? cause.message : t('Không lưu được cài đặt job.', 'Could not save job settings.')) }
  }

  const update = <K extends keyof AutomationSettings>(key: K, value: AutomationSettings[K]) => void saveSettings({ ...settings, [key]: value })
  const updateNested = <K extends 'tts' | 'flow' | 'compose'>(group: K, key: keyof AutomationSettings[K], value: string | number | boolean) => {
    const next = { ...settings[group], [key]: value } as AutomationSettings[K]
    void saveSettings({ ...settings, [group]: next })
  }
  const selectedTextProvider = chatProviders.find(item => item.id === settings.textProvider)
  const voiceDisplay = (voice: TtsVoiceOption) => [voice.name || voice.label || voice.id, voice.engine, voice.language].filter(Boolean).join(' · ')
  const selectedVoice = ttsVoices.find(voice => voice.id === settings.tts.voice)

  return <main className="automation-page" style={{ ['--automation-builder-width' as string]: `${builderWidth}px` }}>
      <section className="automation-builder" aria-labelledby="automation-title">
      <div className="automation-heading"><div><h1 id="automation-title">{t('Tự động hoá video', 'Video automation')}</h1><p>{t('Chạy nhiều job từ ý tưởng đến MP4, mỗi job có checkpoint và log riêng.', 'Run multiple jobs from idea to MP4, each with its own checkpoint and logs.')}</p></div><button type="button" className="automation-refresh" onClick={() => void refresh()} aria-label={t('Làm mới job', 'Refresh jobs')}>↻</button></div>
      <div className="automation-mode-grid" role="radiogroup" aria-label={t('Loại đầu vào', 'Input type')}>
        {(['topic', 'ai_topic'] as InputMode[]).map(item => <button key={item} type="button" role="radio" aria-checked={mode === item} className={mode === item ? 'selected' : ''} onClick={() => setMode(item)}><strong>{modeLabel(item, t)}</strong><small>{item === 'topic' ? t('Nhập một chủ đề hoặc URL', 'Enter a topic or URL') : t('AI đưa 5 lựa chọn rồi chờ bạn chọn', 'AI suggests 5 choices, then waits')}</small></button>)}
      </div>
      {(mode === 'topic' || mode === 'ai_topic') && <label className="automation-field"><span>{t('Chủ đề (không bắt buộc)', 'Topic (optional)')}</span><textarea value={topic} onChange={event => setTopic(event.target.value)} placeholder={t('Để trống để AI tự đề xuất chủ đề…', 'Leave empty for AI-generated topic ideas…')} rows={3} /></label>}
      <label className="automation-field"><span>{t('Tên job (tuỳ chọn)', 'Job name (optional)')}</span><input value={title} onChange={event => setTitle(event.target.value)} placeholder={t('Tự đặt theo chủ đề nếu bỏ trống', 'Generated from the topic if empty')} /></label>
      <details className="automation-settings" open={settingsOpen} onToggle={(event) => {
        const next = event.currentTarget.open
        setSettingsOpen(next)
        try { window.localStorage.setItem(AUTOMATION_SETTINGS_OPEN_KEY, next ? '1' : '0') } catch { /* storage unavailable */ }
      }}><summary>{t('Cài đặt các chặng', 'Stage settings')}</summary>
      <div className="automation-settings-layout">
      <div className="automation-settings-tabs" role="tablist" aria-orientation="horizontal" aria-label={t('Cài đặt các chặng', 'Stage settings')}>
        {([
          ['text', t('AI text', 'AI text')],
          ['tts', t('Giọng TTS', 'TTS voice')],
          ['flow', t('Flow', 'Flow')],
          ['compose', t('Ghép video', 'Compose video')],
        ] as [AutomationSettingsTab, string][]).map(([id, label]) => <button key={id} type="button" role="tab" aria-selected={settingsTab === id} aria-controls={`automation-settings-${id}`} className={settingsTab === id ? 'active' : ''} onClick={() => selectSettingsTab(id)}>{label}</button>)}
      </div>
      <div className="automation-settings-panel">
      {settingsTab === 'text' ? <div id="automation-settings-text" className="automation-setting-grid" role="tabpanel">
        <label><span>{t('Ngôn ngữ đầu ra', 'Output language')}</span><select value={settings.language} onChange={event => update('language', event.target.value as AutomationSettings['language'])}><option value="vi">{t('Tiếng Việt', 'Vietnamese')}</option><option value="en">{t('Tiếng Anh', 'English')}</option></select></label>
        <label><span>{t('Provider AI text', 'Text AI provider')}</span><select value={settings.textProvider} onChange={event => { const next = chatProviders.find(item => item.id === event.target.value); const nextModel = next?.models[0]?.id || ''; void saveSettings({ ...settings, textProvider: event.target.value, textModel: nextModel, chatModel: event.target.value === 'chatgpt_web' ? nextModel : settings.chatModel }) }} disabled={chatModelsLoading && !chatProviders.length} aria-busy={chatModelsLoading}>{!chatProviders.length ? <option value="">{chatModelsLoading ? t('Đang tải provider…', 'Loading providers…') : t('Chưa có provider khả dụng', 'No available provider')}</option> : null}{chatProviders.map(item => <option key={item.id} value={item.id} disabled={item.status !== 'ready' && !(item.id === 'chatgpt_web' && item.configured)}>{providerName(item.id)}{item.status === 'free_unavailable' ? ` · ${t('không có model khả dụng', 'no available model')}` : ''}</option>)}</select></label>
        <label><span>{t('Model AI text', 'Text AI model')}</span><select value={settings.textModel} onChange={event => update('textModel', event.target.value)} disabled={chatModelsLoading || !chatProviders.length} aria-busy={chatModelsLoading}>{!selectedTextProvider?.models.length ? <option value="">{chatModelsLoading ? t('Đang tải model…', 'Loading models…') : t('Chưa có model khả dụng', 'No available model')}</option> : null}{(selectedTextProvider?.models || []).map(item => <option key={item.id} value={item.id}>{item.label || item.id}</option>)}</select></label>
        <label className="automation-field-full"><span>{t('System prompt (tuỳ chỉnh)', 'System prompt (optional)')}</span><textarea rows={3} value={settings.systemPrompt || ''} onChange={event => update('systemPrompt', event.target.value)} placeholder={t('Bỏ trống để dùng mặc định của Audio-First 2D engine.', 'Leave empty to use the default Audio-First 2D engine prompt.')} /></label>
      </div> : settingsTab === 'tts' ? <div id="automation-settings-tts" className="automation-setting-grid" role="tabpanel">
        <label className="automation-field-full"><span>{t('Giọng TTS', 'TTS voice')}</span><input type="search" list="automation-tts-voices" value={voiceSearch} disabled={optionsLoading && !ttsVoices.length} placeholder={selectedVoice ? voiceDisplay(selectedVoice) : (optionsLoading ? t('Đang tải giọng…', 'Loading voices…') : t('Gõ tên, engine hoặc ngôn ngữ để tìm giọng…', 'Type a name, engine, or language to find a voice…'))} onChange={event => { const query = event.target.value; setVoiceSearch(query); const match = ttsVoices.find(voice => voice.id === query || voiceDisplay(voice) === query); if (match) void updateNested('tts', 'voice', match.id) }} /><datalist id="automation-tts-voices">{ttsVoices.filter(voice => !voiceSearch.trim() || voiceDisplay(voice).toLowerCase().includes(voiceSearch.trim().toLowerCase())).map(voice => <option key={voice.id} value={voiceDisplay(voice)} />)}</datalist><small className="automation-setting-hint">{selectedVoice ? `${t('Đang chọn', 'Selected')}: ${voiceDisplay(selectedVoice)}` : t('Chọn một gợi ý để dùng cho job.', 'Choose a suggestion to use for the job.')}</small></label>
        <label><span>{t('Tốc độ (%)', 'Speed (%)')}</span><input id="auto-tts-speed" type="range" min="50" max="200" step="5" value={Math.round((settings.tts.speed || 1) * 100)} onChange={event => updateNested('tts', 'speed', Number(event.target.value) / 100)} /><output htmlFor="auto-tts-speed">{Math.round((settings.tts.speed || 1) * 100)}%</output></label>
      </div> : settingsTab === 'flow' ? <div id="automation-settings-flow" className="automation-setting-grid" role="tabpanel">
        <label><span>{t('Model Flow ảnh', 'Flow image model')}</span><select value={settings.flow.model} onChange={event => updateNested('flow', 'model', event.target.value)}>{FLOW_IMAGE_MODELS.map(model => <option key={model} value={model}>{model}</option>)}</select></label>
        <label><span>{t('Bộ prompt Audio-First 2D', 'Audio-First 2D prompt engine')}</span><select value={settings.flow.promptEngine} onChange={event => updateNested('flow', 'promptEngine', event.target.value as 'vi' | 'en')}><option value="vi">ZMTOOL Audio-First 2D Engine V1.0 (Tiếng Việt)</option><option value="en">ZMTOOL Audio-First 2D Engine V1.0 (Bản Tiếng Anh)</option></select></label>
        <label><span>{t('Tài khoản Flow', 'Flow account')}</span><select value={settings.flow.accountId} onChange={event => updateNested('flow', 'accountId', event.target.value)} disabled={optionsLoading && !flowAccounts.length}><option value="">{optionsLoading ? t('Đang tải tài khoản…', 'Loading accounts…') : t('Chọn tài khoản Flow', 'Select a Flow account')}</option>{flowAccounts.filter(account => account.status === 'online').map(account => <option key={account.id} value={account.id}>{account.label}{account.plan ? ` · ${account.plan}` : ''}</option>)}</select></label>
        <label><span>{t('Tỷ lệ khung hình', 'Aspect ratio')}</span><select value={settings.flow.ratio} onChange={event => updateNested('flow', 'ratio', event.target.value)}><option>16:9</option><option>9:16</option><option>1:1</option></select></label>
        <label><span>{t('Số ảnh mỗi prompt', 'Images per prompt')}</span><select value={settings.flow.count ?? '1'} onChange={event => updateNested('flow', 'count', event.target.value)}><option value="1">1</option><option value="2">2</option><option value="4">4</option></select></label>
        <label><span>{t('Số luồng Flow', 'Flow concurrency')}</span><input type="number" min="1" max="8" value={settings.flow.concurrency} onChange={event => updateNested('flow', 'concurrency', event.target.value)} /></label>
      </div> : settingsTab === 'compose' ? <div id="automation-settings-compose" className="automation-setting-grid" role="tabpanel">
        <label><span>{t('Chất lượng xuất', 'Output quality')}</span><select value={settings.compose.resolution} onChange={event => updateNested('compose', 'resolution', event.target.value)}><option value="auto">{t('Auto theo media · 1080p', 'Auto from media · 1080p')}</option><option value="1920x1080">{t('1080p ngang', '1080p landscape')}</option><option value="1080x1920">{t('1080p dọc', '1080p portrait')}</option><option value="1080x1080">{t('1080p vuông', '1080p square')}</option><option value="1280x720">{t('720p ngang', '720p landscape')}</option></select></label>
        <label><span>{t('FPS xuất video', 'Output FPS')}</span><input type="number" min="1" max="120" value={settings.compose.fps} onChange={event => updateNested('compose', 'fps', Number(event.target.value) || 30)} /></label>
        <label><span>{t('Chất lượng nén (CRF)', 'Compression quality (CRF)')}</span><select value={settings.compose.crf} onChange={event => updateNested('compose', 'crf', Number(event.target.value) || 20)}><option value="18">{t('Cao · file lớn', 'High · larger file')}</option><option value="20">{t('Cân bằng', 'Balanced')}</option><option value="23">{t('Nhanh · file nhỏ', 'Fast · smaller file')}</option></select></label>
        <label><span>{t('Bộ mã hóa', 'Encoder')}</span><select value={settings.compose.encoder} onChange={event => updateNested('compose', 'encoder', event.target.value as AutomationSettings['compose']['encoder'])}><option value="auto">{t('Tự động', 'Automatic')}</option><option value="gpu">GPU</option><option value="cpu">CPU</option></select></label>
        <label><span>{t('Tốc độ (%)', 'Speed (%)')}</span><input type="number" min="25" max="400" value={settings.compose.speed} onChange={event => updateNested('compose', 'speed', Number(event.target.value) || 100)} /></label>
        <label><span>{t('Âm lượng (%)', 'Volume (%)')}</span><input type="number" min="0" max="300" value={settings.compose.volume} onChange={event => updateNested('compose', 'volume', Number(event.target.value) || 100)} /></label>
        <label><span>{t('Preview (giây)', 'Preview (seconds)')}</span><input type="number" min="0" max="120" value={settings.compose.previewSeconds} onChange={event => updateNested('compose', 'previewSeconds', Number(event.target.value) || 0)} /></label>
        <label className="automation-check"><input type="checkbox" checked={settings.compose.subtitleEnabled} onChange={event => updateNested('compose', 'subtitleEnabled', event.target.checked)} /><span>{t('Chèn phụ đề SRT', 'Burn SRT subtitles')}</span></label>
        <label className="automation-check"><input type="checkbox" checked={settings.compose.allowMissingMedia} onChange={event => updateNested('compose', 'allowMissingMedia', event.target.checked)} /><span>{t('Cho phép ghép khi thiếu media', 'Allow composition with missing media')}</span></label>
        <label className="automation-check"><input type="checkbox" checked={settings.compose.removeMetadata} onChange={event => updateNested('compose', 'removeMetadata', event.target.checked)} /><span>{t('Xóa metadata file xuất', 'Remove output metadata')}</span></label>
        <details className="automation-compose-group automation-field-full" open><summary>{t('Chuyển cảnh & chuyển động', 'Transitions & motion')}</summary><div className="automation-setting-grid">
          <label><span>{t('Nền tảng khung hình', 'Frame platform')}</span><select value={settings.compose.targetPlatform} onChange={event => updateNested('compose', 'targetPlatform', event.target.value)}><option value="auto">{t('Tự động', 'Automatic')}</option><option value="youtube">YouTube</option><option value="shorts">Shorts / Reels</option><option value="tiktok">TikTok</option></select></label>
          <label><span>{t('Hiệu ứng chuyển cảnh', 'Transition effect')}</span><select value={settings.compose.effect} onChange={event => updateNested('compose', 'effect', event.target.value)}><option value="none">{t('Tắt', 'Off')}</option><option value="random">{t('Ngẫu nhiên', 'Random')}</option><option value="fade">Fade</option><option value="dissolve">Dissolve</option></select></label>
          <label><span>{t('Thời lượng chuyển cảnh (giây)', 'Transition duration (seconds)')}</span><input type="number" min="0" max="5" step=".05" value={settings.compose.transitionDuration} onChange={event => updateNested('compose', 'transitionDuration', Number(event.target.value) || 0)} /></label>
          <label><span>Zoom</span><select value={settings.compose.zoom} onChange={event => updateNested('compose', 'zoom', event.target.value)}><option value="off">{t('Tắt', 'Off')}</option><option value="random">{t('Ngẫu nhiên', 'Random')}</option><option value="zoomIn">Zoom in</option><option value="zoomOut">Zoom out</option><option value="left">{t('Trái → phải', 'Left → right')}</option><option value="right">{t('Phải → trái', 'Right → left')}</option><option value="up">{t('Dưới → trên', 'Bottom → top')}</option><option value="down">{t('Trên → dưới', 'Top → bottom')}</option></select></label>
        </div></details>
        <details className="automation-compose-group automation-field-full" open><summary>{t('Phụ đề SRT', 'SRT subtitles')}</summary><div className="automation-setting-grid">
          <label><span>{t('Phông chữ', 'Font')}</span><select value={settings.compose.subtitleFontFamily} onChange={event => updateNested('compose', 'subtitleFontFamily', event.target.value)}><option value="system">{t('Hệ thống', 'System')}</option><option value="Arial">Arial</option><option value="Roboto">Roboto</option><option value="Montserrat">Montserrat</option></select></label>
          <label><span>{t('Cỡ chữ', 'Font size')}</span><input type="number" min="6" max="120" value={settings.compose.subtitleSize} onChange={event => updateNested('compose', 'subtitleSize', Number(event.target.value) || 8)} /></label>
          <label><span>{t('Lệch thời gian (giây)', 'Time offset (seconds)')}</span><input type="number" min="-3600" max="3600" step=".1" value={settings.compose.subtitleOffset} onChange={event => updateNested('compose', 'subtitleOffset', Number(event.target.value) || 0)} /></label>
          <label><span>{t('Lề dưới', 'Bottom margin')}</span><input type="number" min="0" max="1000" value={settings.compose.subtitleMargin} onChange={event => updateNested('compose', 'subtitleMargin', Number(event.target.value) || 0)} /></label>
          <label><span>{t('Nền chữ', 'Caption background')}</span><select value={settings.compose.subtitleBackground} onChange={event => updateNested('compose', 'subtitleBackground', event.target.value)}><option value="none">{t('Không nền', 'None')}</option><option value="solid">{t('Đặc', 'Solid')}</option><option value="box">{t('Hộp', 'Box')}</option></select></label>
          <label><span>{t('Độ mờ nền (%)', 'Background opacity (%)')}</span><input type="number" min="0" max="100" value={settings.compose.subtitleOpacity} onChange={event => updateNested('compose', 'subtitleOpacity', Number(event.target.value) || 0)} /></label>
          <label><span>{t('Màu chữ', 'Text color')}</span><input type="color" value={settings.compose.subtitleColor} onChange={event => updateNested('compose', 'subtitleColor', event.target.value)} /></label>
          <label><span>{t('Màu nền', 'Background color')}</span><input type="color" value={settings.compose.subtitleBgColor} onChange={event => updateNested('compose', 'subtitleBgColor', event.target.value)} /></label>
        </div></details>
        <details className="automation-compose-group automation-field-full"><summary>{t('Vẽ ảnh & xoá logo gốc', 'Drawing & remove original logo')}</summary><div className="automation-setting-grid">
          <label className="automation-check automation-field-full"><input type="checkbox" checked={settings.compose.drawingEnabled} onChange={event => updateNested('compose', 'drawingEnabled', event.target.checked)} /><span>{t('Vẽ ảnh tĩnh thành video', 'Turn still images into drawing videos')}</span></label>
          {settings.compose.drawingEnabled && <><label><span>{t('Kiểu vẽ', 'Drawing style')}</span><select value={settings.compose.drawingMode} onChange={event => updateNested('compose', 'drawingMode', event.target.value)}><option value="hand">{t('Tay + bút', 'Hand + pen')}</option><option value="drawing">{t('Vẽ nét', 'Strokes')}</option></select></label><label><span>{t('Dụng cụ', 'Tool')}</span><select value={settings.compose.drawingTool} onChange={event => updateNested('compose', 'drawingTool', event.target.value)}><option value="pencil">{t('Chì', 'Pencil')}</option><option value="pen">{t('Bút', 'Pen')}</option><option value="marker">Marker</option><option value="brush">{t('Cọ', 'Brush')}</option></select></label><label><span>{t('Độ chi tiết (%)', 'Detail (%)')}</span><input type="number" min="10" max="100" value={settings.compose.drawingDetail} onChange={event => updateNested('compose', 'drawingDetail', Number(event.target.value) || 72)} /></label><label><span>{t('Độ dày nét', 'Stroke thickness')}</span><input type="number" min="1" max="8" value={settings.compose.drawingThickness} onChange={event => updateNested('compose', 'drawingThickness', Number(event.target.value) || 2)} /></label><label className="automation-field-full"><span>{t('Đường đi nét', 'Stroke route')}</span><select value={settings.compose.drawingStrokeOrder} onChange={event => updateNested('compose', 'drawingStrokeOrder', event.target.value)}><option value="natural">{t('Tự nhiên theo đối tượng', 'Natural by object')}</option><option value="outline">{t('Theo viền thật', 'True outlines')}</option><option value="region">{t('Từng vùng hoàn chỉnh', 'Complete one region')}</option><option value="reading">{t('Theo chữ · trái sang phải', 'Text · left to right')}</option><option value="center">{t('Từ tâm lan ra', 'Centre outward')}</option></select></label></>}
          <label className="automation-check"><input type="checkbox" checked={settings.compose.delogoEnabled} onChange={event => updateNested('compose', 'delogoEnabled', event.target.checked)} /><span>{t('Xóa logo gốc', 'Remove original logo')}</span></label>
          {settings.compose.delogoEnabled && <><label className="automation-check"><input type="checkbox" checked={settings.compose.delogoAuto} onChange={event => updateNested('compose', 'delogoAuto', event.target.checked)} /><span>{t('Tự định vị logo', 'Auto position logo')}</span></label>{!settings.compose.delogoAuto && <><label><span>X (%)</span><input type="number" min="0" max="100" value={settings.compose.delogoX} onChange={event => updateNested('compose', 'delogoX', Number(event.target.value) || 0)} /></label><label><span>Y (%)</span><input type="number" min="0" max="100" value={settings.compose.delogoY} onChange={event => updateNested('compose', 'delogoY', Number(event.target.value) || 0)} /></label><label><span>{t('Rộng (%)', 'Width (%)')}</span><input type="number" min="1" max="100" value={settings.compose.delogoW} onChange={event => updateNested('compose', 'delogoW', Number(event.target.value) || 1)} /></label><label><span>{t('Cao (%)', 'Height (%)')}</span><input type="number" min="1" max="100" value={settings.compose.delogoH} onChange={event => updateNested('compose', 'delogoH', Number(event.target.value) || 1)} /></label></>}</>}
        </div></details>
        <details className="automation-compose-group automation-field-full"><summary>{t('Logo / watermark', 'Logo / watermark')}</summary><div className="automation-setting-grid">
          <label className="automation-check automation-field-full"><input type="checkbox" checked={settings.compose.logoEnabled} onChange={event => updateNested('compose', 'logoEnabled', event.target.checked)} /><span>{t('Chèn logo vào video', 'Add logo to video')}</span></label>
          {settings.compose.logoEnabled && <><label><span>{t('Nguồn logo', 'Logo source')}</span><select value={settings.compose.logoSource} onChange={event => updateNested('compose', 'logoSource', event.target.value as 'text' | 'image' | 'icon')}><option value="text">{t('Chữ', 'Text')}</option><option value="image">{t('Ảnh', 'Image')}</option><option value="icon">Icon</option></select></label>{settings.compose.logoSource === 'text' ? <label><span>{t('Nội dung', 'Content')}</span><input value={settings.compose.logoText} onChange={event => updateNested('compose', 'logoText', event.target.value)} /></label> : settings.compose.logoSource === 'image' ? <label><span>{t('Ảnh logo', 'Logo image')}</span><input type="file" accept="image/png,image/jpeg,image/webp,image/bmp" onChange={event => setFiles(current => ({ ...current, watermark: event.target.files?.[0] || null }))} /><small className="automation-setting-hint">{files.watermark?.name || t('Chọn ảnh khi tạo job mới.', 'Choose an image when creating a new job.')}</small></label> : <label><span>Icon</span><select value={settings.compose.logoIcon} onChange={event => updateNested('compose', 'logoIcon', event.target.value)}><option>★</option><option>▶</option><option>●</option><option>◆</option></select></label>}<label><span>{t('Độ mờ (%)', 'Opacity (%)')}</span><input type="number" min="5" max="100" value={settings.compose.logoOpacity} onChange={event => updateNested('compose', 'logoOpacity', Number(event.target.value) || 5)} /></label><label><span>X (%)</span><input type="number" min="0" max="100" value={settings.compose.logoX} onChange={event => updateNested('compose', 'logoX', Number(event.target.value) || 0)} /></label><label><span>Y (%)</span><input type="number" min="0" max="100" value={settings.compose.logoY} onChange={event => updateNested('compose', 'logoY', Number(event.target.value) || 0)} /></label><label><span>{t('Chuyển động', 'Motion')}</span><select value={settings.compose.logoMotion} onChange={event => updateNested('compose', 'logoMotion', event.target.value)}><option value="fixed">{t('Cố định', 'Static')}</option><option value="random">{t('Ngẫu nhiên', 'Random')}</option></select></label><label><span>{t('Phạm vi', 'Scope')}</span><select value={settings.compose.logoScope} onChange={event => updateNested('compose', 'logoScope', event.target.value)}><option value="full">{t('Toàn video', 'Entire video')}</option><option value="range">{t('Theo đoạn', 'Selected range')}</option></select></label>{settings.compose.logoSource === 'text' ? <><label><span>{t('Cỡ chữ', 'Font size')}</span><input type="number" min="6" max="160" value={settings.compose.logoFontSize} onChange={event => updateNested('compose', 'logoFontSize', Number(event.target.value) || 32)} /></label><label><span>{t('Màu chữ', 'Text color')}</span><input type="color" value={settings.compose.logoColor} onChange={event => updateNested('compose', 'logoColor', event.target.value)} /></label></> : <label><span>{t('Kích thước (%)', 'Size (%)')}</span><input type="number" min="2" max="30" value={settings.compose.logoSize} onChange={event => updateNested('compose', 'logoSize', Number(event.target.value) || 8)} /></label>}{settings.compose.logoMotion === 'random' && <><label><span>{t('Hiện (giây)', 'Visible (seconds)')}</span><input type="number" min=".5" step=".1" value={settings.compose.logoVisibleSec} onChange={event => updateNested('compose', 'logoVisibleSec', Number(event.target.value) || .5)} /></label><label><span>{t('Ẩn (giây)', 'Hidden (seconds)')}</span><input type="number" min="0" step=".1" value={settings.compose.logoHiddenSec} onChange={event => updateNested('compose', 'logoHiddenSec', Number(event.target.value) || 0)} /></label><label><span>Fade (s)</span><input type="number" min="0" step=".1" value={settings.compose.logoFadeSec} onChange={event => updateNested('compose', 'logoFadeSec', Number(event.target.value) || 0)} /></label><label><span>{t('Lề an toàn (%)', 'Safe margin (%)')}</span><input type="number" min="0" max="20" value={settings.compose.logoSafeMargin} onChange={event => updateNested('compose', 'logoSafeMargin', Number(event.target.value) || 0)} /></label></>}{settings.compose.logoScope === 'range' && <><label><span>{t('Hiện từ (giây)', 'Show from (seconds)')}</span><input type="number" min="0" value={settings.compose.logoStart} onChange={event => updateNested('compose', 'logoStart', Number(event.target.value) || 0)} /></label><label><span>{t('Đến (giây)', 'Until (seconds)')}</span><input type="number" min="0" value={settings.compose.logoEnd} onChange={event => updateNested('compose', 'logoEnd', Number(event.target.value) || 0)} /></label></>}</>}
        </div></details>
        <div className="automation-field-full">
          <OutputFolderField
            isDesktopApp={isDesktopApp}
            value={settings.outputDir}
            onChange={(value) => update('outputDir', value)}
            onChoose={isDesktopApp ? async () => {
              const res = await fetch('/api/system/pick-folder', { method: 'POST' })
              if (!res.ok) throw new Error(await res.text())
              const picked = await res.json() as { path?: string }
              return picked.path || undefined
            } : undefined}
            defaultPath={t('Ví dụ: du-an-01', 'Example: project-01')}
            appFolder="automation"
            label={t('Thư mục xuất MP4', 'MP4 output folder')}
          />
        </div>
      </div> : null}</div></div></details>
      {notice && <p className="automation-notice" role="status">{notice}</p>}{error && <p className="automation-error" role="alert">{error}</p>}
      <button type="button" className="automation-submit" onClick={() => void submit()} disabled={submitting}>{submitting ? t('Đang thêm job…', 'Adding job…') : mode === 'ai_topic' ? t('✦ Tạo 5 chủ đề', '✦ Generate 5 topics') : t('▶ Chạy job', '▶ Run job')}</button>
    </section>
      <div className="automation-resizer" role="separator" aria-orientation="vertical" aria-label={t('Kéo để đổi độ rộng panel', 'Drag to resize panel')} onPointerDown={(event) => { event.preventDefault(); panelDrag.current = { startX: event.clientX, startWidth: builderWidth }; document.body.classList.add('automation-resizing') }} />
      <section className="automation-queue" aria-labelledby="automation-queue-title"><div className="automation-queue-heading"><div><p className="automation-eyebrow">QUEUE</p><h2 id="automation-queue-title">{t('Các job đang chạy', 'Job queue')}</h2></div><span>{jobs.length} {t('job', 'jobs')}</span></div>{loading ? <p className="automation-empty">{t('Đang tải…', 'Loading…')}</p> : !jobs.length ? <p className="automation-empty">{t('Chưa có job. Tạo job đầu tiên ở bên trái.', 'No jobs yet. Create the first job on the left.')}</p> : <div className="automation-job-list">{jobs.map(job => { const jobProvider = String(job.settings?.textProvider || ''); const jobModel = String(job.settings?.textModel || job.settings?.chatModel || ''); return <article className={`automation-job automation-job--${job.status}`} key={job.id}><div className="automation-job-head"><div><h3>{job.title}</h3><p>{modeLabel(job.input_mode, t)} · {stageLabel(job.stage, t)}{jobProvider ? ` · ${providerName(jobProvider)}` : ''}{jobModel ? ` · ${jobModel}` : ''}</p></div><span className="automation-status">{statusLabel(job.status, t)}</span></div><div className="automation-progress-row"><div className="automation-progress"><i style={{ width: `${Math.max(0, Math.min(100, job.progress || 0))}%` }} /></div><strong>{Math.round(job.progress || 0)}%</strong></div>{job.error ? <p className="automation-job-error"><strong>{job.error.code || t('Lỗi', 'Error')}</strong> {job.error.message}</p> : null}{job.status === 'awaiting_topic' && <div className="automation-topic-choices">{(job.input?.topicCandidates || []).map(candidate => <button type="button" key={candidate} onClick={() => void chooseTopic(job, candidate)}>{candidate}</button>)}</div>}<div className="automation-job-actions">{job.status === 'running' || job.status === 'queued' ? <button type="button" onClick={() => void mutate(job.id, 'pause')}>{t('Tạm dừng', 'Pause')}</button> : null}{job.status === 'paused' || job.status === 'interrupted' ? <><button type="button" onClick={() => void editJob(job)}>{t('Sửa cài đặt', 'Edit settings')}</button><button type="button" onClick={() => void mutate(job.id, 'resume')}>{t('Tiếp tục', 'Continue')}</button><button type="button" onClick={() => void mutate(job.id, 'retry')}>{t('Chạy lại chặng lỗi', 'Retry failed stage')}</button></> : null}{job.status === 'cancelled' ? <><button type="button" onClick={() => void mutate(job.id, 'resume')}>{t('Tiếp tục', 'Continue')}</button></> : null}{job.status === 'failed' || job.status === 'completed' ? <><button type="button" onClick={() => void editJob(job)}>{t('Sửa cài đặt', 'Edit settings')}</button><button type="button" onClick={() => void mutate(job.id, 'retry')}>{t('Ghép lại', 'Recompose')}</button></> : null}{!['completed', 'cancelled', 'failed'].includes(job.status) ? <button type="button" className="danger" onClick={() => void mutate(job.id, 'cancel')}>{t('Hủy', 'Cancel')}</button> : null}<button type="button" className="danger" onClick={() => removeJob(job)}>{t('Xoá job', 'Delete job')}</button>{(job.status === 'completed' || Object.keys(job.artifacts || {}).length > 0) ? <button type="button" onClick={() => void openFolder(job)}>{t('Mở thư mục', 'Open folder')}</button> : null}{job.artifacts && Object.entries(job.artifacts).map(([key, artifact]) => {
                        if (!artifact?.available) return null
                        const href = `${API}/jobs/${encodeURIComponent(job.id)}/artifacts/${encodeURIComponent(key)}`
                        const label = artifact.filename || key
                        if (key === 'video') return (
                          <Fragment key={key}>
                            <button type="button" onClick={() => previewArtifact(key, href, job.title)}>{t('Xem', 'View')}</button>
                            <a href={href} download={artifact.filename || 'output.mp4'}>{t('Tải xuống', 'Download')}</a>
                          </Fragment>
                        )
                        if (key === 'images') return <button key={key} type="button" onClick={() => previewArtifact(key, href, label)}>{t('Hàng đợi Flow', 'Flow queue')}</button>
                        return <a key={key} href={href} onClick={event => { event.preventDefault(); previewArtifact(key, href, label) }}>{label}</a>
                      })}</div>{job.logs?.length ? <details className="automation-logs"><summary>{t('Xem log', 'View logs')} ({job.logs.length})</summary><div>{job.logs.slice(-12).map((log, index) => <p key={`${log.id || index}-${log.message}`}><time>{log.stage}</time> {log.message}</p>)}</div></details> : null}</article> })}</div>}</section>
      <MediaPreviewModal
        open={Boolean(videoPreview)}
        item={videoPreview}
        onClose={() => { setVideoPreview(null); setTextPreview(null) }}
        downloadLabel={t('Tải file', 'Download file')}
        onDownload={() => { if (videoPreview) { const link = document.createElement('a'); link.href = videoPreview.src; link.download = videoPreview.downloadFilename || 'automation-output'; link.click() } }}
        actions={videoPreview?.type === 'srt' && textPreview !== null ? [{ label: textPreviewSaving ? t('Đang lưu…', 'Saving…') : t('Lưu', 'Save'), onClick: saveTextPreview, disabled: textPreviewSaving, primary: true } satisfies MediaPreviewAction] : []}
      >
        {videoPreview?.type === 'srt' && textPreview !== null ? <textarea value={textPreview} onChange={event => setTextPreview(event.target.value)} spellCheck={false} style={{ width: '100%', minHeight: '60vh', resize: 'vertical', margin: 0, padding: 20, whiteSpace: 'pre-wrap', textAlign: 'left', color: 'white', background: 'rgba(0,0,0,.25)', border: 0, outline: 'none', font: 'inherit' }} /> : undefined}
      </MediaPreviewModal>
      <ConfirmDialog open={Boolean(deleteTarget)} title={t('Xác nhận xoá job', 'Confirm job deletion')} message={deleteTarget ? t(`Xoá job “${deleteTarget.title}”, log, file đầu vào, MP4 đã xuất và ảnh Flow liên quan?`, `Delete job “${deleteTarget.title}”, its logs, input files, exported MP4, and related Flow images?`) : ''} cancelLabel={t('Quay lại', 'Go back')} confirmLabel={t('Xoá toàn bộ', 'Delete everything')} onCancel={() => setDeleteTarget(null)} onConfirm={() => void confirmRemoveJob()} danger />
  </main>
}
