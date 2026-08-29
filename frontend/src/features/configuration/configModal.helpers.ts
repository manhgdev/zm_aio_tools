import type { CloudProviderId, SystemChecks } from '@/features/project/project.types'

export const PROVIDERS: CloudProviderId[] = ['openai', 'gemini', 'deepseek', 'openrouter', 'grok', 'nvidia']

export type InstallKind = 'ai_runtime' | 'ai_runtime_ocr' | 'ai_runtime_vieneu' | 'ocr_cuda' | 'demucs_cuda' | 'nvm'

export const INSTALL_LABELS: Record<InstallKind, string> = {
  ai_runtime: 'gói AI', ai_runtime_ocr: 'gói AI', ai_runtime_vieneu: 'gói AI',
  ocr_cuda: 'OCR CUDA', demucs_cuda: 'Demucs', nvm: 'NVM + Node.js LTS',
}

export const INSTALL_ORDER: InstallKind[] = ['ai_runtime', 'ai_runtime_ocr', 'ai_runtime_vieneu', 'ocr_cuda', 'demucs_cuda']

export function installLabel(kind: string): string {
  return INSTALL_LABELS[kind as InstallKind] || kind
}

export function nextAutoInstall(checks: SystemChecks): InstallKind | null {
  for (const id of INSTALL_ORDER) {
    const it = checks.items.find((i) => !i.ok && i.install === id)
    if (it?.required) return id
  }
  return null
}

export type Section = 'setup' | 'cloud' | 'tts' | 'license' | 'logs'
export type CloudTab = CloudProviderId
export type UpdateDialog = {
  kind: 'available' | 'info' | 'downloading' | 'ready' | 'error' | 'complete'
  title: string; detail: string; progress?: number
}

export type CloudDraft = Record<
  CloudProviderId,
  { apiKey: string; apiKeys?: string; keyCount?: number; baseUrl: string; model: string; reviewBaseUrl?: string; reviewModel?: string; apiKeySet: boolean; label: string }
>

export function emptyCloud(): CloudDraft {
  return {
    openai:     { apiKey: '', baseUrl: 'https://api.openai.com/v1', model: 'gpt-4o-mini', apiKeySet: false, label: 'OpenAI' },
    gemini:     { apiKey: '', baseUrl: 'https://generativelanguage.googleapis.com/v1beta', model: 'gemini-3.1-flash-lite', reviewModel: 'gemini-2.5-flash', apiKeySet: false, label: 'Gemini' },
    deepseek:   { apiKey: '', baseUrl: 'https://api.deepseek.com', model: 'deepseek-chat', apiKeySet: false, label: 'DeepSeek' },
    openrouter: { apiKey: '', baseUrl: 'https://openrouter.ai/api/v1', model: 'google/gemini-2.5-flash', apiKeySet: false, label: 'OpenRouter' },
    grok:       { apiKey: '', baseUrl: 'https://api.x.ai/v1', model: 'grok-3-mini', apiKeySet: false, label: 'Grok' },
    nvidia:     { apiKey: '', baseUrl: 'https://integrate.api.nvidia.com/v1', model: 'nvidia/riva-translate-4b-instruct-v2', apiKeySet: false, label: 'NVIDIA NIM' },
  }
}

export function savedKeyPlaceholder(config: CloudDraft[CloudProviderId], index: number): string {
  const masked = (config.apiKeys || '').split(',')[index]?.trim()
  return masked || (index < (config.keyCount || 0) ? '••••••••' : 'sk-…')
}
