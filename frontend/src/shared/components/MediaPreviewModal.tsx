import { useEffect, type ReactNode } from 'react'
import { IconArrowRight, IconDownload } from '@/shared/components/Icons'
import { localize, useLocale } from '@/app/i18n'
import './MediaPreviewModal.css'

export type MediaPreviewKind = 'video' | 'image' | 'audio' | 'srt' | 'iframe' | 'other'

export type MediaPreviewItem = {
  id?: string
  title: string
  subtitle?: string
  src: string
  downloadUrl?: string
  downloadFilename?: string
  type?: MediaPreviewKind | string
  canEdit?: boolean
  extra?: Record<string, any>
}

export type MediaPreviewAction = {
  label: string
  onClick: () => void | Promise<void>
  danger?: boolean
  primary?: boolean
  disabled?: boolean
  icon?: ReactNode
}

export type MediaPreviewModalProps = {
  open: boolean
  onClose: () => void
  item: MediaPreviewItem | null
  // Navigation across multiple items
  totalCount?: number
  currentIndex?: number
  onPrevious?: () => void
  onNext?: () => void
  // Standard Action Buttons
  onReveal?: () => void | Promise<void>
  revealLabel?: string
  onDownload?: () => void
  downloadLabel?: string
  onEdit?: () => void | Promise<void>
  editLabel?: string
  onDelete?: () => void | Promise<void>
  deleteLabel?: string
  // Custom Action Buttons
  actions?: MediaPreviewAction[]
  // Custom Media Body Render if needed
  children?: ReactNode
}

export function detectMediaKind(src: string, explicitType?: string): MediaPreviewKind {
  if (explicitType) {
    const t = explicitType.toLowerCase()
    if (t.includes('video') || t === 'mp4' || t === 'mov' || t === 'webm' || t === 'mkv') return 'video'
    if (t.includes('image') || t === 'png' || t === 'jpg' || t === 'jpeg' || t === 'webp') return 'image'
    if (t.includes('audio') || t === 'mp3' || t === 'wav' || t === 'ogg' || t === 'm4a' || t === 'aac') return 'audio'
    if (t.includes('srt') || t === 'vtt' || t === 'ass' || t === 'sub') return 'srt'
    if (t.includes('iframe') || t.includes('html')) return 'iframe'
  }
  const clean = src.split('?')[0].toLowerCase()
  if (clean.endsWith('.mp4') || clean.endsWith('.mov') || clean.endsWith('.webm') || clean.endsWith('.mkv')) return 'video'
  if (clean.endsWith('.png') || clean.endsWith('.jpg') || clean.endsWith('.jpeg') || clean.endsWith('.webp') || clean.endsWith('.gif')) return 'image'
  if (clean.endsWith('.mp3') || clean.endsWith('.wav') || clean.endsWith('.m4a') || clean.endsWith('.aac') || clean.endsWith('.ogg')) return 'audio'
  if (clean.endsWith('.srt') || clean.endsWith('.vtt') || clean.endsWith('.txt')) return 'srt'
  return 'video'
}

export function MediaPreviewModal({
  open,
  onClose,
  item,
  totalCount = 0,
  currentIndex = -1,
  onPrevious,
  onNext,
  onReveal,
  revealLabel,
  onDownload,
  downloadLabel,
  onEdit,
  editLabel,
  onDelete,
  deleteLabel,
  actions = [],
  children,
}: MediaPreviewModalProps) {
  const { locale } = useLocale()
  const t = (vi: string, en: string) => localize(locale, vi, en)

  const hasNavigation = totalCount > 1 && currentIndex >= 0

  useEffect(() => {
    if (!open || !item) return
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
      if (hasNavigation) {
        if (event.key === 'ArrowLeft') onPrevious?.()
        if (event.key === 'ArrowRight') onNext?.()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [open, item, hasNavigation, onClose, onPrevious, onNext])

  if (!open || !item) return null

  const kind = detectMediaKind(item.src, item.type)

  return (
    <div
      className="flow-preview-backdrop media-preview-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <section
        className="flow-preview-dialog media-preview-dialog"
        role="dialog"
        aria-modal="true"
        aria-label={t('Xem trước kết quả', 'Output preview')}
      >
        <header>
          <div>
            <strong>
              {hasNavigation
                ? `[${currentIndex + 1}/${totalCount}] ${item.title}`
                : item.title}
            </strong>
            {item.subtitle ? <small>{item.subtitle}</small> : null}
          </div>
          <button
            type="button"
            className="flow-preview-close"
            onClick={onClose}
            aria-label={t('Đóng xem trước', 'Close preview')}
          >
            ×
          </button>
        </header>

        <div className="flow-preview-media media-preview-media">
          {children ? (
            children
          ) : kind === 'video' ? (
            <video key={item.src} src={item.src} controls autoPlay playsInline />
          ) : kind === 'image' ? (
            <img key={item.src} src={item.src} alt={item.title} />
          ) : kind === 'audio' ? (
            <div className="flow-preview-audio-stage">
              <div className="flow-preview-audio-icon">
                <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>
              </div>
              <strong>{item.title}</strong>
              <audio key={item.src} src={item.src} controls autoPlay />
            </div>
          ) : kind === 'srt' ? (
            <div className="flow-preview-srt-stage">
              <div className="flow-preview-srt-icon">
                <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
              </div>
              <strong>{item.title}</strong>
              {item.subtitle && <small style={{ color: 'rgba(255,255,255,0.7)' }}>{item.subtitle}</small>}
            </div>
          ) : (
            <iframe key={item.src} src={item.src} title={item.title} />
          )}

          {hasNavigation && (
            <>
              <button
                className="flow-preview-nav is-previous"
                type="button"
                onClick={onPrevious}
                aria-label={t('Kết quả trước', 'Previous output')}
                title={t('Kết quả trước (Phím ←)', 'Previous output (Left Arrow)')}
              >
                <IconArrowRight size={22} />
              </button>
              <button
                className="flow-preview-nav is-next"
                type="button"
                onClick={onNext}
                aria-label={t('Kết quả tiếp theo', 'Next output')}
                title={t('Kết quả tiếp theo (Phím →)', 'Next output (Right Arrow)')}
              >
                <IconArrowRight size={22} />
              </button>
              <span className="flow-preview-counter" aria-live="polite">
                {currentIndex + 1} / {totalCount}
              </span>
            </>
          )}
        </div>

        <footer>
          {onReveal && (
            <button type="button" onClick={() => void onReveal()}>
              {revealLabel || t('Mở thư mục', 'Open folder')}
            </button>
          )}
          {onDownload ? (
            <button type="button" onClick={onDownload}>
              <IconDownload size={15} /> {downloadLabel || t('Tải về', 'Download')}
            </button>
          ) : item.downloadUrl ? (
            <a href={item.downloadUrl} download={item.downloadFilename || item.title}>
              <IconDownload size={15} /> {downloadLabel || t('Tải về', 'Download')}
            </a>
          ) : null}
          {onEdit && (
            <button type="button" onClick={() => void onEdit()}>
              {editLabel || t('Sửa', 'Edit')}
            </button>
          )}
          {actions.map((act, i) => (
            <button
              key={i}
              type="button"
              className={act.danger ? 'flow-preview-delete media-preview-delete' : undefined}
              disabled={act.disabled}
              onClick={() => void act.onClick()}
            >
              {act.icon} {act.label}
            </button>
          ))}
          {onDelete && (
            <button
              type="button"
              className="flow-preview-delete media-preview-delete"
              onClick={() => void onDelete()}
            >
              {deleteLabel || t('Xóa', 'Delete')}
            </button>
          )}
          <button type="button" onClick={onClose}>
            {t('Đóng', 'Close')}
          </button>
        </footer>
      </section>
    </div>
  )
}
