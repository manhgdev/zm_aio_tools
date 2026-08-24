/** Copy text in browsers and native webviews, including denied Clipboard API contexts. */
export async function copyText(text: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text)
      return
    } catch {
      // Native webviews can expose the API but deny it; use the DOM fallback.
    }
  }

  const textarea = document.createElement('textarea')
  textarea.value = text
  textarea.readOnly = true
  textarea.style.position = 'fixed'
  textarea.style.inset = '0 auto auto -9999px'
  textarea.style.opacity = '0'
  document.body.appendChild(textarea)
  try {
    textarea.focus()
    textarea.select()
    textarea.setSelectionRange(0, textarea.value.length)
    if (!document.execCommand('copy')) throw new Error('COPY_FAILED')
  } finally {
    textarea.remove()
  }
}
