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

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const resize = () => {
      canvas.width = canvas.offsetWidth * 2
      canvas.height = canvas.offsetHeight * 2
    }
    resize()
    window.addEventListener('resize', resize)

    const fontSize = 14
    const columns = Math.floor(canvas.width / fontSize)
    const drops: number[] = Array(columns).fill(0).map(() => Math.random() * -100)

    const draw = () => {
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

    const interval = setInterval(draw, 45)
    return () => {
      clearInterval(interval)
      window.removeEventListener('resize', resize)
    }
  }, [color, charSet, speed])

  return <canvas ref={canvasRef} className="absolute inset-0 w-full h-full" style={{ opacity: 0.6 }} />
}
