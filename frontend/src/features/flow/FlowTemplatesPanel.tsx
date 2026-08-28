import { useMemo, useState } from 'react'
import { toast } from 'sonner'
import { localize, useLocale } from '@/app/i18n'
import { IconBook, IconDownload } from '@/shared/components/Icons'
import { FLOW_PROMPT_TEMPLATES, type FlowPromptTemplate, type FlowTemplateCategory, type FlowTemplateLang } from './flowTemplates'
import './FlowTemplatesPanel.css'

type Props = {
  onClose?: () => void
  embedded?: boolean
}

function downloadText(filename: string, text: string) {
  const blob = new Blob([text], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

export function FlowTemplatesPanel({ onClose, embedded = false }: Props) {
  const { locale } = useLocale()
  const t = (vi: string, en: string) => localize(locale, vi, en)

  const [categoryFilter, setCategoryFilter] = useState<FlowTemplateCategory | 'all'>('all')
  const [langFilter, setLangFilter] = useState<FlowTemplateLang | 'all'>('all')
  const [searchQuery, setSearchQuery] = useState('')
  const [previewTemplate, setPreviewTemplate] = useState<FlowPromptTemplate | null>(null)

  const filteredTemplates = useMemo(() => {
    return FLOW_PROMPT_TEMPLATES.filter((tpl) => {
      if (categoryFilter !== 'all' && tpl.category !== categoryFilter) return false
      if (langFilter !== 'all' && tpl.lang !== langFilter) return false
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase()
        const matchTitle = tpl.title.vi.toLowerCase().includes(q) || tpl.title.en.toLowerCase().includes(q)
        const matchDesc = tpl.description.vi.toLowerCase().includes(q) || tpl.description.en.toLowerCase().includes(q)
        const matchTag = tpl.tags.some((tag) => tag.toLowerCase().includes(q))
        if (!matchTitle && !matchDesc && !matchTag) return false
      }
      return true
    })
  }, [categoryFilter, langFilter, searchQuery])

  const copyPrompt = (tpl: FlowPromptTemplate) => {
    void navigator.clipboard.writeText(tpl.content).then(() => {
      toast.success(
        t(
          `Đã sao chép ${tpl.title.vi}! Hãy dán vào ChatGPT / Claude kèm file SRT để tạo danh sách prompt ảnh.`,
          `Copied ${tpl.title.en}! Paste into ChatGPT / Claude with your SRT file to generate image prompts.`,
        ),
      )
    }).catch(() => {
      toast.error(t('Không thể sao chép văn bản', 'Failed to copy text'))
    })
  }

  const handleDownload = (tpl: FlowPromptTemplate) => {
    downloadText(tpl.filename, tpl.content)
    toast.success(t(`Đang tải file ${tpl.filename}`, `Downloading ${tpl.filename}`))
  }

  return (
    <div className={`flow-templates-panel${embedded ? ' is-embedded' : ''}`}>
      <header className="flow-templates-header">
        <div className="flow-templates-header-main">
          <div className="flow-templates-title-row">
            <IconBook size={24} className="flow-templates-icon" />
            <div>
              <h2>{t('Thư viện Prompt Hệ Thống & Hướng dẫn Flow', 'Flow System Prompt Guides & Engines')}</h2>
              <p>
                {t(
                  'Các mẫu chỉ dẫn AI (System Prompt) chuẩn để đưa vào ChatGPT / Claude / Gemini phân tích file SRT hoặc Kịch bản thành chuỗi Prompt tạo ảnh/video đồng bộ theo Audio.',
                  'Standard System Prompt Engines for ChatGPT / Claude / Gemini to analyze SRT or Scripts into audio-synced image/video prompt batches.',
                )}
              </p>
            </div>
          </div>
          {onClose && (
            <button type="button" className="flow-templates-close-btn" onClick={onClose} aria-label={t('Đóng', 'Close')}>
              ×
            </button>
          )}
        </div>

        {/* ── Workflow Guide Steps ── */}
        <div className="flow-workflow-steps">
          <div className="flow-workflow-step">
            <span className="flow-workflow-step-num">1</span>
            <div>
              <strong>{t('Copy hoặc Tải System Prompt', 'Copy or Download System Prompt')}</strong>
              <small>{t('Lấy file mẫu bên dưới phù hợp với nhu cầu (Ảnh 2D / Video / Series).', 'Pick the matching template engine below (2D Image / Video / Series).')}</small>
            </div>
          </div>
          <div className="flow-workflow-step-arrow">➔</div>
          <div className="flow-workflow-step">
            <span className="flow-workflow-step-num">2</span>
            <div>
              <strong>{t('Dán vào ChatGPT / Claude / Gemini', 'Paste into ChatGPT / Claude / Gemini')}</strong>
              <small>{t('Gửi kèm file SRT, Audio hoặc Kịch bản để AI chia cảnh và xuất file prompt TXT.', 'Send your SRT, Audio, or Script for AI to segment visual beats and output a TXT prompt file.')}</small>
            </div>
          </div>
          <div className="flow-workflow-step-arrow">➔</div>
          <div className="flow-workflow-step">
            <span className="flow-workflow-step-num">3</span>
            <div>
              <strong>{t('Nhập file TXT vào Flow để tạo', 'Import TXT into Flow to Generate')}</strong>
              <small>{t('Quay lại tab Tạo trong Flow, bấm [Nhập TXT] để render hàng loạt tự động.', 'Back in Flow Create tab, click [Import TXT] to batch generate automatically.')}</small>
            </div>
          </div>
        </div>

        <div className="flow-templates-toolbar">
          <div className="flow-templates-tabs" role="tablist" aria-label={t('Lọc danh mục', 'Category filter')}>
            <button
              type="button"
              className={categoryFilter === 'all' ? 'is-active' : ''}
              onClick={() => setCategoryFilter('all')}
            >
              {t('Tất cả', 'All')}
            </button>
            <button
              type="button"
              className={categoryFilter === 'image' ? 'is-active' : ''}
              onClick={() => setCategoryFilter('image')}
            >
              🎨 {t('Ảnh 2D', '2D Image')}
            </button>
            <button
              type="button"
              className={categoryFilter === 'video' ? 'is-active' : ''}
              onClick={() => setCategoryFilter('video')}
            >
              🎬 {t('Video Veo 3', 'Video Veo 3')}
            </button>
            <button
              type="button"
              className={categoryFilter === 'series' ? 'is-active' : ''}
              onClick={() => setCategoryFilter('series')}
            >
              📚 {t('Series', 'Series')}
            </button>
          </div>

          <div className="flow-templates-lang-filter">
            <button
              type="button"
              className={langFilter === 'all' ? 'is-active' : ''}
              onClick={() => setLangFilter('all')}
            >
              {t('Mọi ngôn ngữ', 'All languages')}
            </button>
            <button
              type="button"
              className={langFilter === 'vi' ? 'is-active' : ''}
              onClick={() => setLangFilter('vi')}
            >
              🇻🇳 {t('Tiếng Việt', 'Vietnamese')}
            </button>
            <button
              type="button"
              className={langFilter === 'en' ? 'is-active' : ''}
              onClick={() => setLangFilter('en')}
            >
              🌐 {t('Tiếng Anh', 'English')}
            </button>
          </div>

          <div className="flow-templates-search">
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder={t('Tìm kiếm prompt mẫu…', 'Search templates…')}
            />
          </div>
        </div>
      </header>

      <div className="flow-templates-content">
        <div className="flow-templates-grid">
          {filteredTemplates.map((tpl) => (
            <article key={tpl.id} className="flow-template-card">
              <header className="flow-template-card-header">
                <div className="flow-template-badges">
                  <span className="flow-template-badge flow-template-badge--system">
                    ⚙️ {t('Prompt Hệ Thống (AI Engine)', 'System Prompt Engine')}
                  </span>
                  <span className="flow-template-badge flow-template-badge--lang">
                    {tpl.lang === 'vi' ? '🇻🇳 Tiếng Việt' : '🌐 English'}
                  </span>
                  <span className="flow-template-badge flow-template-badge--cat">
                    {tpl.category === 'image' ? '🎨 2D Image' : tpl.category === 'video' ? '🎬 Video' : '📚 Series'}
                  </span>
                  <span className="flow-template-badge flow-template-badge--ver">{tpl.version}</span>
                </div>
                <h3 className="flow-template-card-title">{locale === 'en' ? tpl.title.en : tpl.title.vi}</h3>
                <p className="flow-template-card-desc">{locale === 'en' ? tpl.description.en : tpl.description.vi}</p>
                <div className="flow-template-tags">
                  {tpl.tags.map((tag) => (
                    <span key={tag} className="flow-template-tag">
                      #{tag}
                    </span>
                  ))}
                </div>
              </header>

              <footer className="flow-template-card-footer">
                <div className="flow-template-usage-hint">
                  <span>💡 {t('Dùng cho ChatGPT / Claude / Gemini để phân tích SRT / Audio.', 'For ChatGPT / Claude / Gemini to analyze SRT / Audio.')}</span>
                </div>
                <div className="flow-template-card-actions">
                  <button
                    type="button"
                    className="flow-template-btn flow-template-btn--preview"
                    onClick={() => setPreviewTemplate(tpl)}
                    title={t('Xem trước toàn văn nội dung', 'Preview full template')}
                  >
                    👁 {t('Xem trước', 'Preview')}
                  </button>
                  <button
                    type="button"
                    className="flow-template-btn flow-template-btn--copy"
                    onClick={() => copyPrompt(tpl)}
                    title={t('Sao chép Prompt Hệ Thống để dán vào ChatGPT / Claude', 'Copy System Prompt to paste into ChatGPT / Claude')}
                  >
                    📋 {t('Sao chép Prompt Hệ Thống', 'Copy System Prompt')}
                  </button>
                  <button
                    type="button"
                    className="flow-template-btn"
                    onClick={() => handleDownload(tpl)}
                    title={t(`Tải file ${tpl.filename}`, `Download ${tpl.filename}`)}
                  >
                    <IconDownload size={14} /> {t('Tải về (.txt)', 'Download (.txt)')}
                  </button>
                </div>
              </footer>
            </article>
          ))}

          {/* Placeholder cards for upcoming templates */}
          {(categoryFilter === 'all' || categoryFilter === 'video') && (langFilter === 'all' || langFilter === 'en') && (
            <article className="flow-template-card flow-template-card--placeholder">
              <div className="flow-template-badges">
                <span className="flow-template-badge">⚙️ System Prompt</span>
                <span className="flow-template-badge">🎬 Video Veo 3</span>
                <span className="flow-template-badge">Motion</span>
                <span className="flow-template-badge">v1.0</span>
              </div>
              <h3 className="flow-template-card-title">{t('Veo 3 Motion & Camera Direction Engine', 'Veo 3 Motion & Camera Direction Engine')}</h3>
              <p className="flow-template-card-desc">
                {t('Mẫu prompt hệ thống phân tích nhịp video, điều khiển chuyển động camera (dolly, pan, tilt, orbit) và âm thanh sống động cho Veo 3.', 'System prompt engine analyzing video pacing, camera directions (dolly, pan, tilt, orbit), and dynamic audio for Veo 3.')}
              </p>
              <div className="flow-template-placeholder-note">
                <span>⏳ {t('Sắp cập nhật bổ sung', 'Coming soon')}</span>
              </div>
            </article>
          )}

          <article className="flow-template-card flow-template-card--placeholder">
            <div className="flow-template-badges">
              <span className="flow-template-badge">⚙️ System Prompt</span>
              <span className="flow-template-badge">🎬 Video Veo 3</span>
              <span className="flow-template-badge">Motion</span>
              <span className="flow-template-badge">v1.0</span>
            </div>
            <h3 className="flow-template-card-title">{t('Veo 3 Motion & Camera Direction Engine', 'Veo 3 Motion & Camera Direction Engine')}</h3>
            <p className="flow-template-card-desc">
              {t('Mẫu prompt hệ thống phân tích nhịp video, điều khiển chuyển động camera (dolly, pan, tilt, orbit) và âm thanh sống động cho Veo 3.', 'System prompt engine analyzing video pacing, camera directions (dolly, pan, tilt, orbit), and dynamic audio for Veo 3.')}
            </p>
            <div className="flow-template-placeholder-note">
              <span>⏳ {t('Sắp cập nhật bổ sung', 'Coming soon')}</span>
            </div>
          </article>

          {(categoryFilter === 'all' || categoryFilter === 'series') && (
            <article className="flow-template-card flow-template-card--placeholder">
              <div className="flow-template-badges">
                <span className="flow-template-badge">⚙️ System Prompt</span>
                <span className="flow-template-badge">📚 Series</span>
                <span className="flow-template-badge">Continuity</span>
                <span className="flow-template-badge">v1.0</span>
              </div>
              <h3 className="flow-template-card-title">{t('Series Continuity & Character Anchor Engine', 'Series Continuity & Character Anchor Engine')}</h3>
              <p className="flow-template-card-desc">
                {t('Mẫu prompt hệ thống giữ nhất quán nhân vật (Character Bible), phong cách nghệ thuật và bối cảnh qua hàng chục tập phim.', 'System prompt engine maintaining character consistency (Character Bible), style anchoring, and episodic story continuity.')}
              </p>
              <div className="flow-template-placeholder-note">
                <span>⏳ {t('Sắp cập nhật bổ sung', 'Coming soon')}</span>
              </div>
            </article>
          )}
        </div>
      </div>

      {/* ── Preview Modal ── */}
      {previewTemplate && (
        <div className="flow-template-modal-backdrop" role="presentation" onMouseDown={() => setPreviewTemplate(null)}>
          <section
            className="flow-template-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="flow-template-modal-title"
            onMouseDown={(e) => e.stopPropagation()}
          >
            <header className="flow-template-modal-header">
              <div>
                <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
                  <small className="flow-template-modal-badge">{previewTemplate.filename}</small>
                  <span className="flow-template-badge flow-template-badge--system">⚙️ {t('Prompt Hệ Thống', 'System Prompt Engine')}</span>
                </div>
                <h2 id="flow-template-modal-title">{locale === 'en' ? previewTemplate.title.en : previewTemplate.title.vi}</h2>
              </div>
              <button
                type="button"
                className="flow-template-modal-close"
                onClick={() => setPreviewTemplate(null)}
                aria-label={t('Đóng', 'Close')}
              >
                ×
              </button>
            </header>

            <div className="flow-template-modal-notice">
              <span>💡</span>
              <p>
                {t(
                  'Hướng dẫn: Hãy sao chép hoặc tải file này, sau đó dán vào ChatGPT / Claude / Gemini kèm file SRT hoặc Kịch bản để AI chia cảnh và xuất danh sách prompt hình ảnh/video.',
                  'Guide: Copy or download this file, then paste it into ChatGPT / Claude / Gemini with your SRT or Script file for AI to segment scenes and output image/video prompts.',
                )}
              </p>
            </div>

            <div className="flow-template-modal-body">
              <pre className="flow-template-code">{previewTemplate.content}</pre>
            </div>

            <footer className="flow-template-modal-footer">
              <div className="flow-template-modal-info">
                <span>{previewTemplate.content.length.toLocaleString()} {t('ký tự', 'characters')}</span>
                <span>·</span>
                <span>{previewTemplate.content.split('\n').length} {t('dòng', 'lines')}</span>
              </div>
              <div className="flow-template-modal-actions">
                <button
                  type="button"
                  className="flow-template-btn flow-template-btn--copy"
                  onClick={() => copyPrompt(previewTemplate)}
                >
                  📋 {t('Sao chép Prompt Hệ Thống', 'Copy System Prompt')}
                </button>
                <button
                  type="button"
                  className="flow-template-btn"
                  onClick={() => handleDownload(previewTemplate)}
                >
                  <IconDownload size={14} /> {t('Tải về file (.txt)', 'Download (.txt)')}
                </button>
                <button
                  type="button"
                  className="flow-template-btn flow-template-btn--neutral"
                  onClick={() => setPreviewTemplate(null)}
                >
                  {t('Đóng', 'Close')}
                </button>
              </div>
            </footer>
          </section>
        </div>
      )}
    </div>
  )
}
