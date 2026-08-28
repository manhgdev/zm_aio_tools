import { useMemo, useState } from 'react'
import { toast } from 'sonner'
import { localize, useLocale } from '@/app/i18n'
import { IconBook, IconDownload } from '@/shared/components/Icons'
import { FLOW_PROMPT_TEMPLATES, type FlowPromptTemplate, type FlowTemplateCategory, type FlowTemplateLang } from './flowTemplates'
import './FlowTemplatesPanel.css'

type Props = {
  onApplyTemplate?: (content: string, template: FlowPromptTemplate) => void
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

export function FlowTemplatesPanel({ onApplyTemplate, onClose, embedded = false }: Props) {
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
      toast.success(t(`Đã sao chép: ${tpl.title.vi}`, `Copied: ${tpl.title.en}`))
    }).catch(() => {
      toast.error(t('Không thể sao chép văn bản', 'Failed to copy text'))
    })
  }

  const handleDownload = (tpl: FlowPromptTemplate) => {
    downloadText(tpl.filename, tpl.content)
    toast.success(t(`Đang tải file ${tpl.filename}`, `Downloading ${tpl.filename}`))
  }

  const handleApply = (tpl: FlowPromptTemplate) => {
    if (onApplyTemplate) {
      onApplyTemplate(tpl.content, tpl)
      toast.success(t(`Đã chèn mẫu ${tpl.title.vi} vào ô prompt.`, `Inserted ${tpl.title.en} into prompt.`))
      if (onClose) onClose()
    }
  }

  return (
    <div className={`flow-templates-panel${embedded ? ' is-embedded' : ''}`}>
      <header className="flow-templates-header">
        <div className="flow-templates-header-main">
          <div className="flow-templates-title-row">
            <IconBook size={24} className="flow-templates-icon" />
            <div>
              <h2>{t('Thư viện Prompt Mẫu & Hướng dẫn Flow', 'Flow Prompt Guides & Templates')}</h2>
              <p>
                {t(
                  'Các mẫu prompt hệ thống (System Prompt) và hướng dẫn chuẩn cho sản xuất ảnh 2D, video Veo 3 và Series theo audio.',
                  'Standard system prompts and production guides for 2D images, Veo 3 videos, and audio-synced series.',
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
                    className="flow-template-btn"
                    onClick={() => copyPrompt(tpl)}
                    title={t('Sao chép nội dung vào Clipboard', 'Copy content to clipboard')}
                  >
                    📋 {t('Copy', 'Copy')}
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
                {onApplyTemplate && (
                  <button
                    type="button"
                    className="flow-template-btn flow-template-btn--apply"
                    onClick={() => handleApply(tpl)}
                  >
                    🚀 {t('Dùng mẫu này', 'Use template')}
                  </button>
                )}
              </footer>
            </article>
          ))}

          {/* Placeholder cards for upcoming templates */}
          <article className="flow-template-card flow-template-card--placeholder">
            <div className="flow-template-badges">
              <span className="flow-template-badge">🌐 English</span>
              <span className="flow-template-badge">🎨 2D Image</span>
              <span className="flow-template-badge">v1.0</span>
            </div>
            <h3 className="flow-template-card-title">{t('ZMTOOL Audio-First 2D Engine (Bản Tiếng Anh)', 'ZMTOOL Audio-First 2D Engine (English Base)')}</h3>
            <p className="flow-template-card-desc">
              {t('Mẫu prompt tối ưu hóa cho thị trường quốc tế, xuất prompt tiếng Anh AI-optimized bám sát audio tiếng Anh.', 'Optimized prompt template for international markets, exporting audio-synced AI-optimized English prompts.')}
            </p>
            <div className="flow-template-placeholder-note">
              <span>⏳ {t('Sắp cập nhật bổ sung', 'Coming soon')}</span>
            </div>
          </article>

          <article className="flow-template-card flow-template-card--placeholder">
            <div className="flow-template-badges">
              <span className="flow-template-badge">🎬 Video Veo 3</span>
              <span className="flow-template-badge">Motion</span>
              <span className="flow-template-badge">v1.0</span>
            </div>
            <h3 className="flow-template-card-title">{t('Veo 3 Motion & Camera Direction Engine', 'Veo 3 Motion & Camera Direction Engine')}</h3>
            <p className="flow-template-card-desc">
              {t('Mẫu prompt chuyên sâu điều khiển góc máy, chuyển động camera (dolly, pan, tilt, orbit) và âm thanh sống động cho Veo 3.', 'Advanced prompt template controlling camera movements (dolly, pan, tilt, orbit) and cinematic audio for Veo 3.')}
            </p>
            <div className="flow-template-placeholder-note">
              <span>⏳ {t('Sắp cập nhật bổ sung', 'Coming soon')}</span>
            </div>
          </article>

          <article className="flow-template-card flow-template-card--placeholder">
            <div className="flow-template-badges">
              <span className="flow-template-badge">📚 Series</span>
              <span className="flow-template-badge">Continuity</span>
              <span className="flow-template-badge">v1.0</span>
            </div>
            <h3 className="flow-template-card-title">{t('Series Continuity & Character Anchor Engine', 'Series Continuity & Character Anchor Engine')}</h3>
            <p className="flow-template-card-desc">
              {t('Mẫu prompt giữ nhất quán nhân vật, phong cách nghệ thuật và bối cảnh qua hàng chục tập phim dài hạn.', 'Prompt template for character consistency, style anchoring, and long-form episodic series storytelling.')}
            </p>
            <div className="flow-template-placeholder-note">
              <span>⏳ {t('Sắp cập nhật bổ sung', 'Coming soon')}</span>
            </div>
          </article>
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
                <small className="flow-template-modal-badge">{previewTemplate.filename}</small>
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
                  className="flow-template-btn"
                  onClick={() => copyPrompt(previewTemplate)}
                >
                  📋 {t('Sao chép nội dung', 'Copy content')}
                </button>
                <button
                  type="button"
                  className="flow-template-btn"
                  onClick={() => handleDownload(previewTemplate)}
                >
                  <IconDownload size={14} /> {t('Tải về file (.txt)', 'Download (.txt)')}
                </button>
                {onApplyTemplate && (
                  <button
                    type="button"
                    className="flow-template-btn flow-template-btn--apply"
                    onClick={() => {
                      handleApply(previewTemplate)
                      setPreviewTemplate(null)
                    }}
                  >
                    🚀 {t('Dùng mẫu này trong Flow', 'Use in Flow')}
                  </button>
                )}
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
