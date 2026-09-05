import { useCallback, useEffect, useRef, useState } from 'react'
import { localize, useLocale } from '@/app/i18n'
import { FLOW_IMAGE_MODELS } from '@/features/flow/flow.helpers'
import { ConfirmDialog } from '@/shared/components/ConfirmDialog'
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
  flow: { accountId: string; model: string; ratio: string; resolution: string; concurrency: string; promptEngine: 'vi' | 'en' }
  compose: { resolution: string; fps: number; crf: number; encoder: 'auto' | 'gpu' | 'cpu'; speed: number; volume: number; previewSeconds: number; allowMissingMedia: boolean; subtitleEnabled: boolean; removeMetadata: boolean }
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
const AUTOMATION_SETTINGS_OPEN_KEY = 'videoclone.automation-settings-open.v1'
const AUTOMATION_PANEL_WIDTH_KEY = 'videoclone.automation-panel-width.v1'
const AUTOMATION_SETTINGS_TAB_KEY = 'videoclone.automation-settings-tab.v1'
const DEFAULT_SETTINGS: AutomationSettings = {
  language: 'vi', textProvider: 'openrouter', textModel: 'openrouter/free', chatModel: 'GPT-5.6 Sol',
  tts: { voice: 'system', speed: 1, volume: 1, pitch: 0, style: 'tu_nhien' },
  flow: { accountId: '', model: 'Nano Banana 2', ratio: '16:9', resolution: '1K', concurrency: '3', promptEngine: 'vi' },
  compose: { resolution: 'auto', fps: 30, crf: 20, encoder: 'auto', speed: 100, volume: 100, previewSeconds: 0, allowMissingMedia: false, subtitleEnabled: true, removeMetadata: false }, outputDir: '',
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
  const [optionsLoading, setOptionsLoading] = useState(true)
  const [jobs, setJobs] = useState<AutomationJob[]>([])
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [editingJobId, setEditingJobId] = useState('')
  const [deleteTarget, setDeleteTarget] = useState<AutomationJob | null>(null)
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

  const [files, setFiles] = useState<Record<string, File | null>>({ script: null, audio: null, srt: null, prompts: null })
  const providerName = (id: string) => ({
    chatgpt_web: t('ChatGPT Web', 'ChatGPT Web'), openai: t('OpenAI API', 'OpenAI API'), gemini: 'Gemini',
    deepseek: 'DeepSeek', openrouter: 'OpenRouter', grok: 'Grok (xAI)', groq: 'Groq', nvidia: t('NVIDIA NIM', 'NVIDIA NIM'),
  } as Record<string, string>)[id] || id
  const refresh = useCallback(async () => {
    try {
      const response = await fetch(`${API}/jobs`)
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
      fetch(`${API}/settings`).then(response => response.ok ? response.json() as Promise<Partial<AutomationSettings>> : null).then(value => { if (value) setSettings(mergeSettings(value)) }).catch(() => undefined),
      refresh(),
    ])
  }, [refresh])

  useEffect(() => {
    let active = true
    setChatModelsLoading(true)
    void fetch('/api/chat/providers').then(response => response.ok ? response.json() as Promise<unknown> : null).then(raw => {
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
      fetch('/api/flow/accounts').then(response => response.ok ? response.json() as Promise<unknown> : null),
      fetch('/api/voices?lang=all').then(response => response.ok ? response.json() as Promise<unknown> : null),
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

  const submit = async () => {
    setSubmitting(true); setError(''); setEditingJobId('')
    const body = new FormData()
    body.set('inputMode', mode); body.set('title', title.trim() || topic.trim().slice(0, 80) || t('Job tự động hoá', 'Automation job')); body.set('topic', topic.trim()); body.set('settings', JSON.stringify(settings)); body.set('startNow', 'true')
    for (const [key, file] of Object.entries(files)) if (file) body.append(key, file)
    try {
      const response = await fetch(`${API}/jobs`, { method: 'POST', body })
      const data = await response.json().catch(() => ({})) as { status?: JobStatus; detail?: { message?: string } }
      if (!response.ok) throw new Error(data.detail?.message || t('Không tạo được job.', 'Could not create job.'))
      setTitle(''); setTopic(''); setFiles({ script: null, audio: null, srt: null, prompts: null }); await refresh()
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
        <label><span>{t('Ngôn ngữ đầu ra', 'Output language')}</span><select value={settings.language} onChange={event => update('language', event.target.value as AutomationSettings['language'])}><option value="vi">{t('Tiếng Việt', 'Vietnamese')}</option><option value="en">{t('Tiếng Anh', 'English')}</option></select><small className="automation-setting-hint">{t('Áp dụng cho script, TTS, SRT và prompt ảnh.', 'Applies to script, TTS, SRT and image prompts.')}</small></label>
        <label><span>{t('Provider AI text', 'Text AI provider')}</span><select value={settings.textProvider} onChange={event => { const next = chatProviders.find(item => item.id === event.target.value); const nextModel = next?.models[0]?.id || ''; void saveSettings({ ...settings, textProvider: event.target.value, textModel: nextModel, chatModel: event.target.value === 'chatgpt_web' ? nextModel : settings.chatModel }) }} disabled={chatModelsLoading && !chatProviders.length} aria-busy={chatModelsLoading}>{!chatProviders.length ? <option value="">{chatModelsLoading ? t('Đang tải provider…', 'Loading providers…') : t('Chưa có provider khả dụng', 'No available provider')}</option> : null}{chatProviders.map(item => <option key={item.id} value={item.id} disabled={item.status !== 'ready' && !(item.id === 'chatgpt_web' && item.configured)}>{providerName(item.id)}{item.status === 'free_unavailable' ? ` · ${t('không có model khả dụng', 'no available model')}` : ''}</option>)}</select><small className="automation-setting-hint">{t('Chọn một provider cho topic, script và prompt ảnh; chỉ model khả dụng.', 'One provider for topic, script and image prompts; available models only.')}</small></label>
        <label><span>{t('Model AI text', 'Text AI model')}</span><select value={settings.textModel} onChange={event => update('textModel', event.target.value)} disabled={chatModelsLoading || !chatProviders.length} aria-busy={chatModelsLoading}>{!selectedTextProvider?.models.length ? <option value="">{chatModelsLoading ? t('Đang tải model…', 'Loading models…') : t('Chưa có model khả dụng', 'No available model')}</option> : null}{(selectedTextProvider?.models || []).map(item => <option key={item.id} value={item.id}>{item.label || item.id}</option>)}</select><small className="automation-setting-hint">{t('Provider lỗi/quota sẽ dừng job để bạn chọn lại.', 'Provider errors/quota pause the job so you can choose again.')}</small></label>
      </div> : settingsTab === 'tts' ? <div id="automation-settings-tts" className="automation-setting-grid" role="tabpanel">
        <label><span>{t('Giọng TTS', 'TTS voice')}</span><select value={settings.tts.voice} onChange={event => updateNested('tts', 'voice', event.target.value)} disabled={optionsLoading && !ttsVoices.length}><option value="">{optionsLoading ? t('Đang tải giọng…', 'Loading voices…') : t('Chưa có giọng', 'No voices available')}</option>{ttsVoices.map(voice => <option key={voice.id} value={voice.id}>{voice.name || voice.label || voice.id}</option>)}</select><small className="automation-setting-hint">{ttsVoices.length ? t(`${ttsVoices.length} giọng từ tab TTS`, `${ttsVoices.length} voices from TTS`) : t('Danh sách sẽ lấy từ tab TTS.', 'The list is loaded from the TTS tab.')}</small></label>
      </div> : settingsTab === 'flow' ? <div id="automation-settings-flow" className="automation-setting-grid" role="tabpanel">
        <label><span>{t('Model Flow ảnh', 'Flow image model')}</span><select value={settings.flow.model} onChange={event => updateNested('flow', 'model', event.target.value)}>{FLOW_IMAGE_MODELS.map(model => <option key={model} value={model}>{model}</option>)}</select><small className="automation-setting-hint">{t('Các model ảnh hiện có trong tab Flow.', 'Current image models from the Flow tab.')}</small></label>
        <label><span>{t('Bộ prompt Audio-First 2D', 'Audio-First 2D prompt engine')}</span><select value={settings.flow.promptEngine} onChange={event => updateNested('flow', 'promptEngine', event.target.value as 'vi' | 'en')}><option value="vi">ZMTOOL Audio-First 2D Engine V1.0 (Tiếng Việt)</option><option value="en">ZMTOOL Audio-First 2D Engine V1.0 (Bản Tiếng Anh)</option></select><small className="automation-setting-hint">{t('Dùng cùng chuẩn tạo ảnh và video cho toàn bộ job hàng loạt.', 'Keeps image and video prompts consistent across the batch.')}</small></label>
        <label><span>{t('Tài khoản Flow', 'Flow account')}</span><select value={settings.flow.accountId} onChange={event => updateNested('flow', 'accountId', event.target.value)} disabled={optionsLoading && !flowAccounts.length}><option value="">{optionsLoading ? t('Đang tải tài khoản…', 'Loading accounts…') : t('Chọn tài khoản Flow', 'Select a Flow account')}</option>{flowAccounts.filter(account => account.status === 'online').map(account => <option key={account.id} value={account.id}>{account.label}{account.plan ? ` · ${account.plan}` : ''}</option>)}</select><small className="automation-setting-hint">{flowAccounts.filter(account => account.status === 'online').length ? t('Chỉ hiển thị tài khoản đang online trong tab Flow.', 'Only online accounts from the Flow tab are shown.') : t('Hãy đăng nhập một tài khoản trong tab Flow trước.', 'Sign in to an account in the Flow tab first.')}</small></label>
        <label><span>{t('Tỷ lệ khung hình', 'Aspect ratio')}</span><select value={settings.flow.ratio} onChange={event => updateNested('flow', 'ratio', event.target.value)}><option>16:9</option><option>9:16</option><option>1:1</option></select></label>
        <label><span>{t('Số luồng Flow', 'Flow concurrency')}</span><input type="number" min="1" max="8" value={settings.flow.concurrency} onChange={event => updateNested('flow', 'concurrency', event.target.value)} /></label>
      </div> : settingsTab === 'compose' ? <div id="automation-settings-compose" className="automation-setting-grid" role="tabpanel">
        <h3 className="automation-settings-panel-title">{t('Cài đặt ghép video', 'Video composition settings')}</h3>
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
        <label><span>{t('Thư mục xuất MP4 (tuỳ chọn)', 'MP4 output folder (optional)')}</span><input value={settings.outputDir} onChange={event => update('outputDir', event.target.value)} placeholder={t('Mặc định: Downloads/ZM_AIO_TOOL/automation', 'Default: Downloads/ZM_AIO_TOOL/automation')} /></label>
      </div> : null}</div></div></details>
      {notice && <p className="automation-notice" role="status">{notice}</p>}{error && <p className="automation-error" role="alert">{error}</p>}
      <button type="button" className="automation-submit" onClick={() => void submit()} disabled={submitting}>{submitting ? t('Đang thêm job…', 'Adding job…') : mode === 'ai_topic' ? t('✦ Tạo 5 chủ đề', '✦ Generate 5 topics') : t('▶ Chạy job', '▶ Run job')}</button>
    </section>
      <div className="automation-resizer" role="separator" aria-orientation="vertical" aria-label={t('Kéo để đổi độ rộng panel', 'Drag to resize panel')} onPointerDown={(event) => { event.preventDefault(); panelDrag.current = { startX: event.clientX, startWidth: builderWidth }; document.body.classList.add('automation-resizing') }} />
      <section className="automation-queue" aria-labelledby="automation-queue-title"><div className="automation-queue-heading"><div><p className="automation-eyebrow">QUEUE</p><h2 id="automation-queue-title">{t('Các job đang chạy', 'Job queue')}</h2></div><span>{jobs.length} {t('job', 'jobs')}</span></div>{loading ? <p className="automation-empty">{t('Đang tải…', 'Loading…')}</p> : !jobs.length ? <p className="automation-empty">{t('Chưa có job. Tạo job đầu tiên ở bên trái.', 'No jobs yet. Create the first job on the left.')}</p> : <div className="automation-job-list">{jobs.map(job => { const jobProvider = String(job.settings?.textProvider || ''); const jobModel = String(job.settings?.textModel || job.settings?.chatModel || ''); return <article className={`automation-job automation-job--${job.status}`} key={job.id}><div className="automation-job-head"><div><h3>{job.title}</h3><p>{modeLabel(job.input_mode, t)} · {stageLabel(job.stage, t)}{jobProvider ? ` · ${providerName(jobProvider)}` : ''}{jobModel ? ` · ${jobModel}` : ''}</p></div><span className="automation-status">{statusLabel(job.status, t)}</span></div><div className="automation-progress-row"><div className="automation-progress"><i style={{ width: `${Math.max(0, Math.min(100, job.progress || 0))}%` }} /></div><strong>{Math.round(job.progress || 0)}%</strong></div>{job.error ? <p className="automation-job-error"><strong>{job.error.code || t('Lỗi', 'Error')}</strong> {job.error.message}</p> : null}{job.status === 'awaiting_topic' && <div className="automation-topic-choices">{(job.input?.topicCandidates || []).map(candidate => <button type="button" key={candidate} onClick={() => void chooseTopic(job, candidate)}>{candidate}</button>)}</div>}<div className="automation-job-actions">{job.status === 'running' || job.status === 'queued' ? <button type="button" onClick={() => void mutate(job.id, 'pause')}>{t('Tạm dừng', 'Pause')}</button> : null}{job.status === 'paused' || job.status === 'interrupted' ? <><button type="button" onClick={() => void editJob(job)}>{t('Sửa cài đặt', 'Edit settings')}</button><button type="button" onClick={() => void mutate(job.id, 'resume')}>{t('Tiếp tục', 'Continue')}</button><button type="button" onClick={() => void mutate(job.id, 'retry')}>{t('Chạy lại chặng lỗi', 'Retry failed stage')}</button></> : null}{!['completed', 'cancelled'].includes(job.status) ? <button type="button" className="danger" onClick={() => void mutate(job.id, 'cancel')}>{t('Hủy', 'Cancel')}</button> : null}<button type="button" className="danger" onClick={() => removeJob(job)}>{t('Xoá job', 'Delete job')}</button>{(job.status === 'completed' || Object.keys(job.artifacts || {}).length > 0) ? <button type="button" onClick={() => void openFolder(job)}>{t('Mở thư mục', 'Open folder')}</button> : null}{job.artifacts && Object.entries(job.artifacts).map(([key, artifact]) => artifact?.available ? <a key={key} href={`${API}/jobs/${encodeURIComponent(job.id)}/artifacts/${encodeURIComponent(key)}`} download={artifact.filename}>{key === 'video' ? t('Tải MP4', 'Download MP4') : artifact.filename || key}</a> : null)}</div>{job.logs?.length ? <details className="automation-logs"><summary>{t('Xem log', 'View logs')} ({job.logs.length})</summary><div>{job.logs.slice(-12).map((log, index) => <p key={`${log.id || index}-${log.message}`}><time>{log.stage}</time> {log.message}</p>)}</div></details> : null}</article> })}</div>}</section>
      <ConfirmDialog open={Boolean(deleteTarget)} title={t('Xác nhận xoá job', 'Confirm job deletion')} message={deleteTarget ? t(`Xoá job “${deleteTarget.title}” và dữ liệu tạm của job?`, `Delete job “${deleteTarget.title}” and its temporary data?`) : ''} cancelLabel={t('Quay lại', 'Go back')} confirmLabel={t('Xoá job', 'Delete job')} onCancel={() => setDeleteTarget(null)} onConfirm={() => void confirmRemoveJob()} danger />
  </main>
}
