'use client'
import { useEffect, useRef } from 'react'

interface MagnetLinesProps {
  rows?: number
  cols?: number
  color?: string
}

export default function MagnetLines({ rows = 12, cols = 20, color = '#F5A623' }: MagnetLinesProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const mouseRef = useRef({ x: -1000, y: -1000 })
  const animRef = useRef<number>(0)
  const needsDrawRef = useRef(true)
  const visibleRef = useRef(true)

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
      needsDrawRef.current = true
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
      needsDrawRef.current = true
    }
    const handleLeave = () => {
      mouseRef.current = { x: -1000, y: -1000 }
      needsDrawRef.current = true
    }
    canvas.addEventListener('mousemove', handleMouse, { passive: true })
    canvas.addEventListener('mouseleave', handleLeave)

    const draw = () => {
      animRef.current = requestAnimationFrame(draw)
      
      if (!visibleRef.current || !needsDrawRef.current) return
      needsDrawRef.current = false

      const w = canvas.offsetWidth
      const h = canvas.offsetHeight
      if (w <= 0 || h <= 0) return
      
      ctx.clearRect(0, 0, w, h)
      
      const cellW = w / cols
      const cellH = h / rows
      const mx = mouseRef.current.x
      const my = mouseRef.current.y
      const radius = 150
      const radiusSq = radius * radius

      ctx.strokeStyle = color
      ctx.lineWidth = 1.5
      ctx.lineCap = 'round'

      for (let r = 0; r < rows; r++) {
        for (let c = 0; c < cols; c++) {
          const cx = cellW * (c + 0.5)
          const cy = cellH * (r + 0.5)
          const dx = mx - cx
          const dy = my - cy
          const distSq = dx * dx + dy * dy
          
          const angle = distSq < radiusSq 
            ? Math.atan2(dy, dx)
            : Math.PI / 2
          
          const len = cellH * 0.35
          const influence = distSq < radiusSq ? Math.max(0, 1 - Math.sqrt(distSq) / radius) : 0
          const opacity = 0.15 + influence * 0.7
          
          ctx.save()
          ctx.translate(cx, cy)
          ctx.rotate(angle)
          ctx.globalAlpha = opacity
          ctx.beginPath()
          ctx.moveTo(-len / 2, 0)
          ctx.lineTo(len / 2, 0)
          ctx.stroke()
          ctx.restore()
        }
      }
    }
    animRef.current = requestAnimationFrame(draw)

    return () => {
      cancelAnimationFrame(animRef.current)
      observer.disconnect()
      window.removeEventListener('resize', resize)
    }
  }, [rows, cols, color])

  return <canvas ref={canvasRef} className="absolute inset-0 w-full h-full" style={{ opacity: 0.4 }} />
}
