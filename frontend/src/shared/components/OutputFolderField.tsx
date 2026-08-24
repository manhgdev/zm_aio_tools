import { useEffect, useMemo, useState } from 'react'
import { localize, useLocale } from '@/app/i18n'
import './OutputFolderField.css'

let desktopOutputRootRequest: Promise<string> | undefined

function loadDesktopOutputRoot() {
  if (!desktopOutputRootRequest) {
    desktopOutputRootRequest = fetch('/api/config')
      .then(async (response) => response.ok ? response.json() as Promise<{ desktopOutputRoot?: string }> : null)
      .then((config) => String(config?.desktopOutputRoot || ''))
      .catch(() => '')
  }
  return desktopOutputRootRequest
}

type Props = {
  isDesktopApp: boolean
  value: string
  onChange: (value: string) => void
  onChoose?: () => void | Promise<void>
  onSave?: () => void | Promise<void>
  defaultPath: string
  appFolder: string
  label?: string
  disabled?: boolean
  selectedRootName?: string
  webFolderOnly?: boolean
}

export function OutputFolderField({
  isDesktopApp,
  value,
  onChange,
  onChoose,
  onSave,
  defaultPath,
  appFolder,
  label,
  disabled = false,
  selectedRootName = '',
  webFolderOnly = false,
}: Props) {
  const { locale } = useLocale()
  const t = (vi: string, en: string) => localize(locale, vi, en)
  const [message, setMessage] = useState('')
  const [desktopOutputRoot, setDesktopOutputRoot] = useState('')
  useEffect(() => setMessage(''), [value])
  useEffect(() => {
    if (!isDesktopApp) return
    let active = true
    void loadDesktopOutputRoot()
      .then((outputRoot) => {
        if (active && outputRoot) setDesktopOutputRoot(outputRoot)
      })
      .catch(() => undefined)
    return () => { active = false }
  }, [isDesktopApp])

  const appPath = useMemo(() => {
    const fallbackRoot = `Downloads/ZM_AIO_TOOL/${appFolder}`
    const defaultRoot = `${desktopOutputRoot || fallbackRoot}`.replace(/[\\/]+$/, '')
    const entered = value.trim()
    if (!entered || !/^(?:[A-Za-z]:[\\/]|[\\/])/.test(entered)) {
      return { prefix: `${defaultRoot}/`, suffix: value }
    }
    const normalized = entered.replace(/[\\/]+$/, '')
    const separatorIndex = Math.max(normalized.lastIndexOf('/'), normalized.lastIndexOf('\\'))
    if (separatorIndex < 0) return { prefix: `${defaultRoot}/`, suffix: value }
    return { prefix: `${normalized.slice(0, separatorIndex + 1)}`, suffix: normalized.slice(separatorIndex + 1) }
  }, [appFolder, desktopOutputRoot, value])

  function changeAppSuffix(nextSuffix: string) {
    const suffix = nextSuffix.trimStart()
    onChange(suffix ? `${appPath.prefix}${suffix}` : '')
  }

  async function save() {
    await onSave?.()
    setMessage(isDesktopApp
      ? t('Đã lưu thư mục.', 'Folder saved.')
      : webFolderOnly
        ? t('Đã lưu tên thư mục con.', 'Subfolder name saved.')
        : t('Đã lưu tên thư mục con / tên đầu ra.', 'Subfolder / output name saved.'))
  }

  return (
    <label className="output-folder-field">
      <span className="output-folder-label">
        {label || t('Thư mục lưu', 'Save folder')}
        <small>{isDesktopApp ? 'APP' : 'WEB'}</small>
      </span>
      <div className={`output-folder-row ${isDesktopApp ? 'is-app' : 'is-web-editable'} ${onChoose ? 'has-choose' : ''}`}>
        {isDesktopApp ? (
          <div className="output-folder-app-path">
            <input
              aria-label={t('Đường dẫn thư mục cố định', 'Fixed output folder path')}
              className="output-folder-prefix"
              type="text"
              value={appPath.prefix}
              title={appPath.prefix}
              disabled
              readOnly
              spellCheck={false}
            />
            <span className="output-folder-separator" aria-hidden="true">—</span>
            <input
              aria-label={t('Tên thư mục hoặc tệp đầu ra', 'Output subfolder or file name')}
              className="output-folder-suffix"
              type="text"
              value={appPath.suffix}
              onChange={(event) => changeAppSuffix(event.target.value)}
              placeholder={defaultPath}
              title={t('Nhập tên thư mục con hoặc tên file; phần đường dẫn đầu là cố định.', 'Enter a subfolder or file name; the base path is fixed.')}
              disabled={disabled}
              spellCheck={false}
            />
          </div>
        ) : (
          <input
            type="text"
            value={value}
            onChange={(event) => onChange(event.target.value)}
            placeholder={webFolderOnly
              ? t('Ví dụ: du-an-01', 'Example: project-01')
              : t('Ví dụ: du-an-01 hoặc video-01.mp4', 'Example: project-01 or video-01.mp4')}
            title={webFolderOnly
              ? t('Tên thư mục con chứa kết quả', 'Result subfolder name')
              : t('Tên thư mục con hoặc tên file đầu ra', 'Output subfolder or file name')}
            disabled={disabled}
            spellCheck={false}
          />
        )}
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
          <>
            {onChoose && (
              <button type="button" disabled={disabled} onClick={() => void onChoose()} title={t('Chọn thư mục tải xuống', 'Choose download folder')}>
                <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 6a2 2 0 0 1 2-2h5l2 3h7a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z" /></svg>
                {t('Chọn', 'Choose')}
              </button>
            )}
            <button type="button" disabled={disabled || !value.trim()} onClick={() => void save()} title={t('Lưu tên đầu ra', 'Save output name')}>
              {t('Lưu', 'Save')}
            </button>
          </>
        )}
      </div>
      <span className="output-folder-hint">
        {message || (!isDesktopApp && selectedRootName
          ? t(`Sẽ lưu vào ${selectedRootName}/${value || 'flow'}.`, `Will save to ${selectedRootName}/${value || 'flow'}.`)
          : isDesktopApp
            ? t('Phần đầu là thư mục mặc định của APP; chỉ sửa tên thư mục hoặc tệp phía sau.', 'The APP base folder is fixed; edit only the subfolder or file name after it.')
          : t(
              webFolderOnly
                ? 'Nhập tên thư mục con; ảnh và video sẽ được lưu bên trong.'
                : 'Nhập thư mục con hoặc tên file đầu ra do bạn muốn.',
              webFolderOnly
                ? 'Enter a subfolder name; images and videos will be saved inside.'
                : 'Enter your preferred output subfolder or file name.',
            ))}
      </span>
    </label>
  )
}
