'use client'
import { useEffect, useRef } from 'react'

interface HexGridProps {
  cellSize?: number
  glowColor?: string
}

export default function HexGrid({ cellSize = 30, glowColor = '#F5A623' }: HexGridProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const mouseRef = useRef({ x: -1000, y: -1000 })
  const timeRef = useRef(0)
  const visibleRef = useRef(true)
  const lastFrameRef = useRef(0)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d', { alpha: true })
    if (!ctx) return

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio, 2)
      canvas.width = canvas.offsetWidth * dpr
      canvas.height = canvas.offsetHeight * dpr
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    }
    resize()
    window.addEventListener('resize', resize)

    // Pause when off-screen
    const observer = new IntersectionObserver(
      ([entry]) => { visibleRef.current = entry.isIntersecting },
      { threshold: 0 }
    )
    observer.observe(canvas)

    const handleMouse = (e: MouseEvent) => {
      const rect = canvas.getBoundingClientRect()
      mouseRef.current = { x: e.clientX - rect.left, y: e.clientY - rect.top }
    }
    window.addEventListener('mousemove', handleMouse, { passive: true })

    let animId: number
    const FPS_INTERVAL = 1000 / 24 // Cap at 24fps (plenty smooth for subtle bg)

    const draw = (timestamp: number) => {
      animId = requestAnimationFrame(draw)
      
      if (!visibleRef.current) return
      
      const elapsed = timestamp - lastFrameRef.current
      if (elapsed < FPS_INTERVAL) return
      lastFrameRef.current = timestamp - (elapsed % FPS_INTERVAL)

      timeRef.current += 0.02
      const w = canvas.offsetWidth
      const h = canvas.offsetHeight
      if (w <= 0 || h <= 0) return
      
      ctx.clearRect(0, 0, w, h)
      
      const hexH = cellSize * Math.sqrt(3)
      const mx = mouseRef.current.x
      const my = mouseRef.current.y

      // Batch similar strokes
      ctx.strokeStyle = glowColor
      ctx.lineWidth = 1

      for (let row = -1; row < h / hexH + 1; row++) {
        for (let col = -1; col < w / (cellSize * 1.5) + 1; col++) {
          const cx = col * cellSize * 1.5
          const cy = row * hexH + (col % 2 === 0 ? 0 : hexH / 2)
          
          const dx = mx - cx
          const dy = my - cy
          const dist = dx * dx + dy * dy // skip sqrt for comparison
          
          const mouseInfluence = dist < 40000 ? Math.max(0, 1 - Math.sqrt(dist) / 200) : 0
          const pulse = Math.sin(timeRef.current * 2 + col * 0.3 + row * 0.5) * 0.5 + 0.5
          const baseOpacity = 0.06
          const opacity = baseOpacity + mouseInfluence * 0.5 + pulse * 0.03
          
          // Skip nearly invisible hexes
          if (opacity < 0.04) continue
          
          const filled = mouseInfluence > 0.3
          const r = cellSize * 0.45

          ctx.beginPath()
          for (let i = 0; i < 6; i++) {
            const angle = (Math.PI / 3) * i - Math.PI / 6
            const x = cx + r * Math.cos(angle)
            const y = cy + r * Math.sin(angle)
            if (i === 0) ctx.moveTo(x, y)
            else ctx.lineTo(x, y)
          }
          ctx.closePath()
          
          if (filled) {
            ctx.fillStyle = glowColor
            ctx.globalAlpha = opacity * 0.3
            ctx.fill()
          }
          ctx.globalAlpha = opacity
          ctx.stroke()
        }
      }
      
      ctx.globalAlpha = 1
    }
    animId = requestAnimationFrame(draw)

    return () => {
      cancelAnimationFrame(animId)
      observer.disconnect()
      window.removeEventListener('resize', resize)
      window.removeEventListener('mousemove', handleMouse)
    }
  }, [cellSize, glowColor])

  return <canvas ref={canvasRef} className="absolute inset-0 w-full h-full pointer-events-none" />
}
