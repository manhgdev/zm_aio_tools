import { useEffect, useRef, useState } from 'react'
import './ConfirmDialog.css'

type PromptDialogProps = {
  open: boolean
  title: string
  message?: string
  initialValue?: string
  placeholder?: string
  confirmLabel: string
  cancelLabel: string
  onConfirm: (value: string) => void
  onCancel: () => void
}

/** In-app text prompt; avoids browser-native prompt dialogs. */
export function PromptDialog({
  open,
  title,
  message,
  initialValue = '',
  placeholder,
  confirmLabel,
  cancelLabel,
  onConfirm,
  onCancel,
}: PromptDialogProps) {
  const [value, setValue] = useState(initialValue)
  const valueRef = useRef(initialValue)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!open) return undefined
    valueRef.current = initialValue
    setValue(initialValue)
    inputRef.current?.focus()
    inputRef.current?.select()
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onCancel()
      if (event.key === 'Enter' && document.activeElement === inputRef.current) onConfirm(valueRef.current.trim())
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [initialValue, onCancel, onConfirm, open])

  if (!open) return null
  return (
    <div
      className="app-confirm-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onCancel()
      }}
    >
      <section className="app-confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="app-prompt-title">
        <header>
          <strong id="app-prompt-title">{title}</strong>
          <button type="button" onClick={onCancel} aria-label={cancelLabel}>×</button>
        </header>
        {message ? <p>{message}</p> : null}
        <div className="app-prompt-field"><label htmlFor="app-prompt-input">{title}</label><input ref={inputRef} id="app-prompt-input" value={value} onChange={(event) => { valueRef.current = event.target.value; setValue(event.target.value) }} placeholder={placeholder} /></div>
        <footer>
          <button type="button" onClick={onCancel}>{cancelLabel}</button>
          <button type="button" className="is-primary" onClick={() => onConfirm(value.trim())}>{confirmLabel}</button>
        </footer>
      </section>
    </div>
  )
}
