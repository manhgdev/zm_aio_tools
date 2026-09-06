/**
 * Hình học khung che / caption (box math thuần) — tách từ coverLayout.ts.
 * Không chứa logic quyết định layout; chỉ pad, clamp, expand, seed box.
 */
import type { ProjectSettings, Segment } from '@/features/project/project.types'
import type { PixelBox, CropRect } from './previewStyles'
import { CAP_PAD_X, isCjkHardsubSource, measureSourceInkWidth } from './captionMeasure'

export const AUTO_SUBTITLE_FONT = 48
/** Khớp burn._cover_max_h — đủ 1–3 dòng theo font */
export const COVER_MAX_H_FRAME_RATIO = 0.065

export const COVER_SHADOW_BOT = 4

export function coverPad(fontSizePx = AUTO_SUBTITLE_FONT, frameW = 1080) {
  return {
    x: Math.max(3, Math.round(frameW * 0.003)),
    // Chỉ chừa đủ viền/stroke; tránh chữ lọt thỏm giữa bbox.
    top: Math.max(2, Math.round(fontSizePx * 0.04)),
    // Match export: leave enough room for CJK descenders, outline, and shadow.
    bottom: Math.max(18, Math.round(fontSizePx * 0.55)),
  }
}

/** Căn giữa khối chữ trong cover (đúng giữa khung tím). */
export function captionCenterInCover(coverY: number, coverH: number, textBlockH: number) {
  return Math.round(coverY + Math.max(0, (coverH - textBlockH) / 2))
}

/** Cover cuối phải ôm trọn mọi dòng caption, mở đều quanh tâm OCR. */
export function expandCoverForCaptionLines(
  cover: PixelBox,
  lineCount: number,
  fontPx: number,
  frameW: number,
  frameH: number,
): PixelBox {
  const lines = Math.max(1, Math.round(lineCount))
  const fs = Math.max(1, fontPx)
  const padY = Math.max(4, Math.round(fs * 0.16))
  const neededH = Math.ceil(lines * fs * 1.1 + padY * 2)
  if (neededH <= cover.h) return clampCoverBox(cover, frameW, frameH)
  const cy = cover.y + cover.h / 2
  const h = Math.min(frameH, neededH)
  return clampCoverBox(
    { ...cover, y: Math.round(cy - h / 2), h },
    frameW,
    frameH,
  )
}

/** Nới cover theo bề ngang cần, giữ tâm — không lệch 1 phía khi chạm mép frame. */
export function expandCoverCentered(
  box: PixelBox,
  needW: number,
  frameW: number,
  frameH: number,
): PixelBox {
  const cx = box.x + box.w / 2
  const w = Math.min(frameW, Math.max(box.w, Math.ceil(needW)))
  const x = Math.round(Math.max(0, Math.min(frameW - w, cx - w / 2)))
  return clampCoverBox({ ...box, x, w }, frameW, frameH)
}

export function coverInnerWidth(coverW: number, fontSizePx: number, frameW: number) {
  const pad = coverPad(fontSizePx, frameW)
  return Math.max(4, coverW - pad.x * 2 - CAP_PAD_X * 2)
}

export function frameMaxInnerWidth(fontSizePx: number, frameW: number) {
  // Full ngang video (trừ pad mép) — bbox được full width
  const maxCoverW = Math.max(12, frameW - 4)
  return coverInnerWidth(maxCoverW, fontSizePx, frameW)
}

export function coverBleedX(contentW: number, frameW = 1080) {
  // Bleed vừa đủ stroke CJK — không nới xa
  return Math.max(4, Math.round(contentW * 0.012), Math.round(frameW * 0.003))
}

export function coverContentWidth(origW: number, transW: number) {
  return Math.max(origW, transW)
}

export function coverBoxWidth(contentW: number, frameW: number) {
  const bleed = coverBleedX(contentW, frameW)
  return Math.min(frameW, Math.ceil(contentW + bleed * 2))
}

/**
 * Cover ngang (chuẩn):
 * 1) Che FULL chữ cũ (OCR seed + đo source + bleed)
 * 2) Fit chữ dịch nếu dài hơn
 * Caption frame nằm trong cover — không co cover theo VI.
 */
export function fitHardsubCover(
  seed: PixelBox,
  autoW: number,
  fontPx: number,
  frameW: number,
  frameH: number,
  sourceText: string,
): PixelBox {
  const pad = coverPad(fontPx, frameW)
  const srcInk = measureSourceInkWidth(sourceText, fontPx, Math.max(seed.h, fontPx))
  // (1) chữ cũ: seed OCR hoặc đo source — luôn tối thiểu đủ che full
  const oldW = Math.max(seed.w, srcInk > 0 ? coverBoxWidth(srcInk, frameW) : 0)
  // (2) chữ dịch chỉ nới thêm khi dài hơn chữ cũ
  const w = Math.min(frameW, Math.max(oldW, autoW))
  const cx = seed.x + seed.w / 2

  // OCR commonly returns the bright glyph body only.  Never trim its top:
  // that was cutting through white/black subtitle outlines in the preview.
  // When seed already spans two rows (h ≥ 1.5× one row), use minimal padding
  // only — extra bleed would push the cover up into the caption area above.
  const oneRowH = Math.max(fontPx * 0.9, 28)
  const isTwoRow = seed.h >= oneRowH * 1.5
  const topBleed = isTwoRow
    ? Math.max(pad.top, Math.round(seed.h * 0.04))
    : Math.max(pad.top, Math.round(seed.h * 0.18))
  const y = Math.max(0, seed.y - topBleed)
  const botExtra = isTwoRow
    ? Math.max(pad.bottom, Math.round(seed.h * 0.06))
    : Math.max(pad.bottom, Math.round(seed.h * 0.4), Math.round(fontPx * 0.7))
  const bottom = seed.y + seed.h + botExtra
  const h = Math.max(12, Math.min(frameH - y, bottom - y))

  return clampCoverBox(
    {
      x: Math.round(Math.max(0, Math.min(frameW - w, cx - w / 2))),
      y: Math.round(y),
      w: Math.round(w),
      h: Math.round(h),
    },
    frameW,
    frameH,
  )
}

/** Chiều ngang ink chữ cũ: max(OCR anchor, đo source, cover đã lưu). */
export function resolveInkWidth(
  anchor: PixelBox,
  coverBox: PixelBox | null,
  hasSource: boolean,
  sourceW: number,
  frameW = 1080,
): number {
  let w = hasSource ? Math.max(sourceW, anchor.w) : anchor.w
  if (coverBox) {
    w = Math.max(w, coverBox.w - coverBleedX(coverBox.w, frameW) * 2)
  }
  return w
}

/** Thu bbox cũ bị kế thừa quá rộng; giữ nguyên tâm/Y/H của vùng OCR. */
export function tightenStoredBbox(
  seg: Pick<Segment, 'source' | 'bboxInherited'>,
  box: PixelBox,
  frameW: number,
): PixelBox {
  // Only an explicit false means the user dragged this box. Legacy OCR
  // payloads omitted bboxInherited, so null still follows conservative
  // horizontal tightening; Y/H remain exactly as located by the backend.
  if (seg.bboxInherited === false) return box
  const cjk = [...(seg.source ?? '')].filter((c) => c >= '一' && c <= '鿿').length
  if (cjk < 1) return box
  const glyphW = Math.max(18, box.h * 0.68)
  const expectedW = Math.max(box.h * 1.15, cjk * glyphW + 12)
  if (expectedW >= box.w * 0.94) return box
  // Tighten conservatively: at most 10%, and never below the estimated old text.
  const w = Math.max(48, Math.min(box.w, Math.round(Math.max(expectedW, box.w * 0.9))))
  const cx = box.x + box.w / 2
  const x = Math.max(0, Math.min(frameW - w, Math.round(cx - w / 2)))
  return { ...box, x, w }
}

export function cropCoversFull(crop: CropRect, frameW: number, frameH: number): boolean {
  return crop.x <= 1 && crop.y <= 1 && crop.w >= frameW - 2 && crop.h >= frameH - 2
}

export function intersectBox(a: PixelBox, crop: CropRect): PixelBox | null {
  const x = Math.max(a.x, crop.x)
  const y = Math.max(a.y, crop.y)
  const x2 = Math.min(a.x + a.w, crop.x + crop.w)
  const y2 = Math.min(a.y + a.h, crop.y + crop.h)
  if (x2 - x < 4 || y2 - y < 4) return null
  return { x: Math.round(x), y: Math.round(y), w: Math.round(x2 - x), h: Math.round(y2 - y) }
}

export function unionBox(a: PixelBox, b: PixelBox): PixelBox {
  const x = Math.min(a.x, b.x)
  const y = Math.min(a.y, b.y)
  const x2 = Math.max(a.x + a.w, b.x + b.w)
  const y2 = Math.max(a.y + a.h, b.y + b.h)
  return { x: Math.round(x), y: Math.round(y), w: Math.round(x2 - x), h: Math.round(y2 - y) }
}

/**
 * Hai cue OCR cùng hàng thường là hai mảnh của một phụ đề cứng hai dòng.
 * OCR cũ đôi khi chỉ trả dòng dưới; nới lên đúng một hàng để Live Preview
 * không lộ dòng trên, đồng thời giữ nguyên bề ngang hợp của các mảnh.
 */
export function expandOverlappingSubtitleBand(
  boxes: PixelBox[],
  frameW: number,
  frameH: number,
  fontPx = AUTO_SUBTITLE_FONT,
): PixelBox | null {
  if (!boxes.length) return null
  const band = boxes.reduce(unionBox)
  const rowH = Math.max(...boxes.map((box) => box.h), 1)
  // When the union already spans multiple rows (blur-band mode where all mid
  // segs are included), skip the aggressive topExtra — it was only needed to
  // expand a single-row sample upward to reach the hidden second line.
  if (band.h >= rowH * 1.6) {
    const smallMargin = Math.round(fontPx * 0.2)
    const y = Math.max(0, band.y - smallMargin)
    return clampCoverBox({ ...band, y, h: band.y + band.h - y + smallMargin }, frameW, frameH)
  }
  const topExtra = Math.max(Math.round(rowH * 0.85), Math.round(fontPx * 1.25))
  const y = Math.max(0, band.y - topExtra)
  return clampCoverBox({ ...band, y, h: band.y + band.h - y }, frameW, frameH)
}

export function coverMaxHeight(frameH: number, fontSizePx = AUTO_SUBTITLE_FONT) {
  const one = Math.round(fontSizePx * 1.45 + 10)
  const cap = Math.round(fontSizePx * 3.4 + 16)
  const byFrame = Math.round(frameH * COVER_MAX_H_FRAME_RATIO)
  return Math.max(one, Math.min(cap, byFrame))
}

/** Giữ chiều cao OCR; ngang được full frame (không cắt 85%). */
export function normalizeCoverBox(box: PixelBox, frameW: number, frameH: number, _fontSizePx = AUTO_SUBTITLE_FONT): PixelBox {
  let { x, y, w, h } = box
  const sanityMaxH = Math.round(frameH * 0.15)
  // Ngang: full video — chỉ kẹp frameW
  const sanityMaxW = frameW
  if (h > sanityMaxH) {
    const cy = y + h / 2
    h = sanityMaxH
    y = Math.round(Math.max(0, Math.min(frameH - h, cy - h / 2)))
  }
  if (w > sanityMaxW) {
    const cx = x + w / 2
    w = sanityMaxW
    x = Math.round(Math.max(0, Math.min(frameW - w, cx - w / 2)))
  }
  x = Math.max(0, Math.min(x, frameW - 12))
  y = Math.max(0, Math.min(y, frameH - 12))
  w = Math.max(12, Math.min(w, frameW - x))
  h = Math.max(12, Math.min(h, frameH - y))
  return { x: Math.round(x), y: Math.round(y), w: Math.round(w), h: Math.round(h) }
}

/** Kéo tay: chỉ kẹp trong khung video, không cắt theo % sanity. */
export function clampCoverBox(box: PixelBox, frameW: number, frameH: number, minSize = 12): PixelBox {
  let { x, y, w, h } = box
  x = Math.max(0, Math.min(x, frameW - minSize))
  y = Math.max(0, Math.min(y, frameH - minSize))
  w = Math.max(minSize, Math.min(w, frameW - x))
  h = Math.max(minSize, Math.min(h, frameH - y))
  return { x: Math.round(x), y: Math.round(y), w: Math.round(w), h: Math.round(h) }
}

/** Anchor OCR suy từ cover — chỉ để căn caption */
export function coverToAnchor(cover: PixelBox, fontSizePx: number, frameW = 1080): PixelBox {
  const pad = coverPad(fontSizePx, frameW)
  return {
    x: Math.round(cover.x + pad.x),
    y: Math.round(cover.y + pad.top),
    w: Math.max(12, Math.round(cover.w - pad.x * 2)),
    h: Math.max(12, Math.round(cover.h - pad.top - pad.bottom)),
  }
}

export type SnapGuides = { h: boolean; v: boolean }

/** Snap tâm khung về giữa khung video — kiểu CapCut */
export function snapBoxToCenter(box: PixelBox, frameW: number, frameH: number): { box: PixelBox; guides: SnapGuides } {
  const thresholdX = Math.max(8, frameW * 0.012)
  const thresholdY = Math.max(8, frameH * 0.012)
  const cx = frameW / 2
  const cy = frameH / 2
  let { x, y, w, h } = box
  const guides: SnapGuides = { h: false, v: false }
  const boxCx = x + w / 2
  const boxCy = y + h / 2
  if (Math.abs(boxCx - cx) <= thresholdX) {
    x = cx - w / 2
    guides.v = true
  }
  if (Math.abs(boxCy - cy) <= thresholdY) {
    y = cy - h / 2
    guides.h = true
  }
  return {
    box: {
      x: Math.max(0, Math.min(frameW - w, x)),
      y: Math.max(0, Math.min(frameH - h, y)),
      w,
      h,
    },
    guides,
  }
}

/**
 * Font theo bbox che chữ (OCR) — chèn trên/dưới/cover đều bám cỡ dải này.
 * Không sàn 48: chữ to tràn đè hardsub.
 */
export function autoFontFromBbox(
  bbox: PixelBox,
  text: string,
  baseFontPx = 0,
): number {
  const compactLen = Math.max(1, text.replace(/\s+/g, '').length)
  const byH = Math.floor(bbox.h * (compactLen <= 12 ? 0.78 : 0.65))
  const byW = Math.floor(bbox.w / Math.max(2.5, compactLen * 0.55))
  const auto = Math.max(10, Math.min(byH, byW, Math.floor(bbox.h * 0.92), 56))
  if (baseFontPx > 0) {
    // preferred user: không lớn hơn bbox che
    return Math.max(10, Math.min(baseFontPx, Math.max(auto, Math.floor(bbox.h * 0.95))))
  }
  return auto
}

export function resolveCaptionFontSize(
  seg: Segment | undefined,
  settings: ProjectSettings,
  _width: number,
  _height: number,
) {
  const segFs = seg?.fontSize ?? 0
  if (segFs > 0) return segFs
  if (settings.subtitleFontSize > 0) return settings.subtitleFontSize
  return AUTO_SUBTITLE_FONT
}

/** Overlay mid/dọc/nhãn: 0 = auto fit khung; >0 = đúng cỡ user set (không lấy cỡ phụ đề đáy dự án). */
export function resolveOverlayFontPreferred(seg: Segment | undefined): number {
  const segFs = seg?.fontSize ?? 0
  return segFs > 0 ? segFs : 0
}

/** placement khi xuất: cover+ burn → over; không cover → below/above.
 * Mid/dọc/nhãn luôn 'over' (neo OCR) — không đẩy xuống đáy khi chọn “phía dưới”.
 */
export function captionPlacement(settings: ProjectSettings): 'over' | 'below' | 'above' {
  if (settings.coverHardsubs && settings.burnSubs) return 'over'
  return settings.captionPlacement === 'above' ? 'above' : 'below'
}

/** Overlay OCR vẫn neo theo bbox khi burn — coverHardsubs chỉ bật mask. */
export function overlayTextEnabled(settings: ProjectSettings): boolean {
  return Boolean(settings.burnSubs && settings.targetLang !== 'none')
}

/** Cover mặc định phụ đề đáy — chỉ khi không phải CJK chờ OCR. */
export function fallbackCoverBox(frameW: number, frameH: number, fontSizePx = AUTO_SUBTITLE_FONT): PixelBox {
  const h = coverMaxHeight(frameH, fontSizePx)
  const w = Math.round(frameW * 0.4)
  return {
    x: Math.round((frameW - w) / 2),
    y: Math.round(frameH - h - Math.round(frameH * 0.06)),
    w,
    h,
  }
}

/**
 * Seed cover: bbox OCR nếu có.
 * CJK chưa bbox → null (không đoán giữa/đáy — video khác nhau vị trí khác nhau).
 */
export function seedCoverBox(
  seg: Pick<Segment, 'source' | 'bbox' | 'layout'> | undefined,
  frameW: number,
  frameH: number,
  fontSizePx = AUTO_SUBTITLE_FONT,
): PixelBox | null {
  if (seg?.bbox) {
    return clampCoverBox(seg.bbox, frameW, frameH)
  }
  if (seg && isCjkHardsubSource(seg.source)) return null
  return fallbackCoverBox(frameW, frameH, fontSizePx)
}
