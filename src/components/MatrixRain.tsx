'use client'
import { useEffect, useRef } from 'react'

interface MatrixRainProps {
  color?: string
  charSet?: string
  speed?: number
}

export default function MatrixRain({ 
  color = '#F5A623', 
  charSet = '01ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩαβγδεζηθ⬡⬢⎔◇◈⏣',
  speed = 1.2
}: MatrixRainProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const visibleRef = useRef(false)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d', { alpha: true })
    if (!ctx) return

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio, 2)
      canvas.width = canvas.offsetWidth * dpr
      canvas.height = canvas.offsetHeight * dpr
    }
    resize()
    window.addEventListener('resize', resize)

    // Only run when visible
    const observer = new IntersectionObserver(
      ([entry]) => { visibleRef.current = entry.isIntersecting },
      { threshold: 0.1 }
    )
    observer.observe(canvas)

    const fontSize = 14
    const columns = Math.floor(canvas.width / fontSize)
    const drops: number[] = Array(columns).fill(0).map(() => Math.random() * -100)

    let intervalId: ReturnType<typeof setInterval> | null = null

    const draw = () => {
      if (!visibleRef.current) return

      ctx.fillStyle = 'rgba(12, 12, 12, 0.05)'
      ctx.fillRect(0, 0, canvas.width, canvas.height)
      
      ctx.font = `${fontSize}px JetBrains Mono, monospace`
      
      for (let i = 0; i < drops.length; i++) {
        const char = charSet[Math.floor(Math.random() * charSet.length)]
        const y = drops[i] * fontSize
        
        // Bright head
        ctx.fillStyle = '#FFD700'
        ctx.globalAlpha = 0.9
        ctx.fillText(char, i * fontSize, y)
        
        // Trail
        ctx.fillStyle = color
        ctx.globalAlpha = 0.4
        if (drops[i] > 1) {
          const trailChar = charSet[Math.floor(Math.random() * charSet.length)]
          ctx.fillText(trailChar, i * fontSize, y - fontSize)
        }
        ctx.globalAlpha = 0.15
        if (drops[i] > 2) {
          const trailChar2 = charSet[Math.floor(Math.random() * charSet.length)]
          ctx.fillText(trailChar2, i * fontSize, y - fontSize * 2)
        }
        
        ctx.globalAlpha = 1
        
        if (y > canvas.height && Math.random() > 0.975) {
          drops[i] = 0
        }
        drops[i] += speed
      }
    }

    // 60ms interval (~16fps) instead of 45ms — matrix rain doesn't need 22fps
    intervalId = setInterval(draw, 60)
    
    return () => {
      if (intervalId) clearInterval(intervalId)
      observer.disconnect()
      window.removeEventListener('resize', resize)
    }
  }, [color, charSet, speed])

  return <canvas ref={canvasRef} className="absolute inset-0 w-full h-full" style={{ opacity: 0.6 }} />
}
