import { useEffect, useState } from 'react'
import { localize, useLocale } from '@/app/i18n'
import './OutputFolderField.css'

type Props = {
  isDesktopApp: boolean
  value: string
  onChange: (value: string) => void
  onChoose?: () => void | Promise<void>
  onSave?: () => void | Promise<void>
  defaultPath: string
  label?: string
  disabled?: boolean
}

export function OutputFolderField({
  isDesktopApp,
  value,
  onChange,
  onChoose,
  onSave,
  defaultPath,
  label,
  disabled = false,
}: Props) {
  const { locale } = useLocale()
  const t = (vi: string, en: string) => localize(locale, vi, en)
  const [message, setMessage] = useState('')
  useEffect(() => setMessage(''), [value])

  async function save() {
    await onSave?.()
    setMessage(isDesktopApp
      ? t('Đã lưu thư mục.', 'Folder saved.')
      : t('Đã lưu tên thư mục con / tên đầu ra.', 'Subfolder / output name saved.'))
  }

  return (
    <label className="output-folder-field">
      <span className="output-folder-label">
        {label || t('Thư mục lưu', 'Save folder')}
        <small>{isDesktopApp ? 'APP' : 'WEB'}</small>
      </span>
      <div className={`output-folder-row ${isDesktopApp ? 'is-app' : 'is-web-editable'}`}>
        <input
          type="text"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          placeholder={isDesktopApp
            ? defaultPath
            : t('Ví dụ: du-an-01 hoặc video-01.mp4', 'Example: project-01 or video-01.mp4')}
          title={isDesktopApp
            ? t('Đường dẫn đầy đủ trên máy chạy APP', 'Full path on the computer running the app')
            : t('Tên thư mục con hoặc tên file đầu ra', 'Output subfolder or file name')}
          disabled={disabled}
          spellCheck={false}
        />
        {isDesktopApp ? (
          <>
            <button type="button" disabled={disabled || !onChoose} onClick={() => void onChoose?.()} title={t('Chọn thư mục', 'Choose folder')}>
              <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 6a2 2 0 0 1 2-2h5l2 3h7a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z" /></svg>
              {t('Chọn', 'Choose')}
            </button>
            <button type="button" disabled={disabled || !value.trim()} onClick={() => void save()} title={t('Lưu thư mục', 'Save folder')}>
              {t('Lưu', 'Save')}
            </button>
          </>
        ) : (
          <button type="button" disabled={disabled || !value.trim()} onClick={() => void save()} title={t('Lưu tên đầu ra', 'Save output name')}>
            {t('Lưu', 'Save')}
          </button>
        )}
      </div>
      <span className="output-folder-hint">
        {message || (isDesktopApp
          ? t('Video, ảnh và file đầu ra sẽ được lưu tại đường dẫn này.', 'Videos, images, and output files will be saved to this path.')
          : t(
              'Nhập thư mục con hoặc tên file đầu ra do bạn muốn.',
              'Enter your preferred output subfolder or file name.',
            ))}
      </span>
    </label>
  )
}
