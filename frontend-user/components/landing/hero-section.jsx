import { useCallback, useEffect, useRef, useState } from "react"
import { Volume2, VolumeX } from "lucide-react"

const METRO_AUDIO_SRC = "/audio/metro-train-ambience.mp3"
const METRO_VOLUME = 0.42

// Two cuts of the hero film: a wide one for desktop and a tall one for
// phones. `movile_video` is spelled that way on disk — matching the real
// filename rather than fixing it here, because the deploy host is
// case- and spelling-sensitive and a "corrected" path would 404 there.
const HERO_VIDEO_DESKTOP = "/images/desktop_video.mp4"
const HERO_VIDEO_MOBILE = "/images/movile_video.mp4"

// Matches Tailwind's `md` breakpoint, which is where the rest of the site
// switches between its mobile and desktop layouts.
const MOBILE_QUERY = "(max-width: 767px)"

export function HeroSection() {
  const videoRef = useRef(null)
  const audioRef = useRef(null)
  const [soundOn, setSoundOn] = useState(false)
  const [needsTap, setNeedsTap] = useState(true)

  const startMetroSound = useCallback(async () => {
    const audio = audioRef.current
    const video = videoRef.current
    if (!audio) return false

    audio.volume = METRO_VOLUME
    audio.loop = true

    try {
      if (video && !video.paused) {
        audio.currentTime = video.currentTime % (audio.duration || 1) || 0
      }
      await audio.play()
      setSoundOn(true)
      setNeedsTap(false)
      return true
    } catch {
      setNeedsTap(true)
      return false
    }
  }, [])

  const stopMetroSound = useCallback(() => {
    const audio = audioRef.current
    if (audio) {
      audio.pause()
      audio.currentTime = 0
    }
    setSoundOn(false)
  }, [])

  const toggleSound = useCallback(async () => {
    if (soundOn) {
      stopMetroSound()
      return
    }
    await startMetroSound()
  }, [soundOn, startMetroSound, stopMetroSound])

  // ── Pick the hero cut for this viewport ────────────────────────────
  // Assigned here rather than in JSX for two reasons:
  //
  //   1. Hydration. Choosing the source during render would need `window`,
  //      which the server doesn't have — the markup would differ between
  //      server and client and React would throw a mismatch.
  //   2. Bandwidth. The obvious alternatives both cost a wasted download:
  //      two <video> elements toggled with `hidden`/`md:` classes fetch
  //      BOTH files, and `<source media="...">` inside <video> is not
  //      honoured by Chrome (it only works inside <picture>). These clips
  //      are 12.7 MB and 18.5 MB, so pulling the wrong one is expensive —
  //      especially on the phone, where the larger file lives.
  //
  // The listener also handles rotating a phone or resizing a window, and
  // only swaps when the answer actually changes, so playback isn't
  // restarted on every incidental resize.
  useEffect(() => {
    const video = videoRef.current
    if (!video || typeof window === "undefined") return

    const mql = window.matchMedia(MOBILE_QUERY)

    const apply = (isMobile) => {
      const next = isMobile ? HERO_VIDEO_MOBILE : HERO_VIDEO_DESKTOP
      // `video.src` reads back as an absolute URL, so compare on the path.
      const current = video.currentSrc || video.src
      if (current && new URL(current, window.location.href).pathname === next) return
      video.src = next
      video.load()
      video.play().catch(() => {
        /* Autoplay can still be refused; the poster frame stays up. */
      })
    }

    apply(mql.matches)
    const onChange = (e) => apply(e.matches)

    // Safari < 14 only has the deprecated addListener signature.
    if (mql.addEventListener) mql.addEventListener("change", onChange)
    else mql.addListener(onChange)
    return () => {
      if (mql.removeEventListener) mql.removeEventListener("change", onChange)
      else mql.removeListener(onChange)
    }
  }, [])

  useEffect(() => {
    const video = videoRef.current
    if (!video) return

    const onVideoPlay = () => {
      if (soundOn && audioRef.current?.paused) {
        audioRef.current.play().catch(() => setNeedsTap(true))
      }
    }

    video.addEventListener("play", onVideoPlay)
    return () => video.removeEventListener("play", onVideoPlay)
  }, [soundOn])

  useEffect(() => {
    return () => {
      audioRef.current?.pause()
    }
  }, [])

  const onHeroInteract = useCallback(() => {
    if (!soundOn && needsTap) void startMetroSound()
  }, [soundOn, needsTap, startMetroSound])

  return (
    <section
      className="relative min-h-screen flex items-center justify-center overflow-hidden cursor-default"
      onClick={onHeroInteract}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") onHeroInteract()
      }}
      role="presentation"
    >
      {/* One <video>, source assigned at runtime — see the effect above.
          Deliberately NO <source> child and no `src` attribute here: the
          element must render identically on server and client, and only
          ONE of the two files may ever be fetched. */}
      <div className="absolute inset-0 z-0">
        <video
          ref={videoRef}
          autoPlay
          loop
          muted
          playsInline
          preload="none"
          className="w-full h-full object-cover"
        />
      </div>

      {/* Metro / train ambience (video stays muted for autoplay policy) */}
      <audio ref={audioRef} src={METRO_AUDIO_SRC} preload="auto" loop />

      <div className="absolute bottom-6 right-6 z-20 flex flex-col items-end gap-2">
        {needsTap && !soundOn && (
          <span className="text-xs text-white/80 bg-black/50 backdrop-blur-sm px-3 py-1 rounded-full">
            Tap for metro train sound
          </span>
        )}
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation()
            void toggleSound()
          }}
          aria-label={soundOn ? "Mute metro train sound" : "Play metro train sound"}
          aria-pressed={soundOn}
          className="flex items-center justify-center w-11 h-11 rounded-full bg-black/55 backdrop-blur-md border border-white/20 text-white hover:bg-black/70 transition-colors shadow-lg"
        >
          {soundOn ? <Volume2 className="w-5 h-5" /> : <VolumeX className="w-5 h-5" />}
        </button>
      </div>
    </section>
  )
}
