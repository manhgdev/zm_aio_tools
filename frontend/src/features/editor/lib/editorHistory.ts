import type { Segment, TextOverlay, ProjectSettings } from '@/features/project/project.types'
import type { MediaClip } from './mediaClips'

import type { TrackId } from './editorUiConsts'

export type EditorSnap = {
  segments: Segment[]
  overlays: TextOverlay[]
  settings: ProjectSettings
  bookmarks: number[]
  selectedId: string | null
  selectedOverlayId: string | null
  trackFocus: TrackId
  videoClips: MediaClip[]
  bgClips: MediaClip[]
  selectedMediaId: string | null
  /** Bake tốc độ lúc snapshot — undo/redo gọi rebake nếu khác */
  bakedSpeed: number
  workClipSec: number
  mediaDuration: number
}

export const HISTORY_MAX = 40

function deepClone<T>(val: T): T {
  if (typeof structuredClone === 'function') {
    try {
      return structuredClone(val)
    } catch {
      /* fallback below */
    }
  }
  return JSON.parse(JSON.stringify(val))
}

export function cloneSnap(s: EditorSnap): EditorSnap {
  return {
    segments: deepClone(s.segments),
    overlays: deepClone(s.overlays),
    settings: deepClone(s.settings),
    bookmarks: [...s.bookmarks],
    selectedId: s.selectedId,
    selectedOverlayId: s.selectedOverlayId,
    trackFocus: s.trackFocus,
    videoClips: deepClone(s.videoClips),
    bgClips: deepClone(s.bgClips),
    selectedMediaId: s.selectedMediaId,
    bakedSpeed: s.bakedSpeed,
    workClipSec: s.workClipSec,
    mediaDuration: s.mediaDuration,
  }
}
