import TtsStudio from '@/features/tts/TtsStudio'

type Props = {
  voices: { id: string; name: string }[]
  onBack: () => void
  onRefreshVoices?: (lang?: string) => void
  isDesktopApp?: boolean
  sideOpen?: boolean
  onSideOpenChange?: (open: boolean) => void
}

export default function TtsPage({
  voices,
  onBack,
  onRefreshVoices,
  isDesktopApp,
  sideOpen,
  onSideOpenChange,
}: Props) {
  return (
    <TtsStudio
      voices={voices}
      onBack={onBack}
      onRefreshVoices={onRefreshVoices}
      isDesktopApp={isDesktopApp}
      sideOpen={sideOpen}
      onSideOpenChange={onSideOpenChange}
    />
  )
}
