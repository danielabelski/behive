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

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const resize = () => {
      canvas.width = canvas.offsetWidth * 2
      canvas.height = canvas.offsetHeight * 2
      ctx.scale(2, 2)
    }
    resize()
    window.addEventListener('resize', resize)

    const handleMouse = (e: MouseEvent) => {
      const rect = canvas.getBoundingClientRect()
      mouseRef.current = { x: e.clientX - rect.left, y: e.clientY - rect.top }
    }
    canvas.addEventListener('mousemove', handleMouse)
    canvas.addEventListener('mouseleave', () => { mouseRef.current = { x: -1000, y: -1000 } })

    let animId: number
    const draw = () => {
      const w = canvas.offsetWidth
      const h = canvas.offsetHeight
      ctx.clearRect(0, 0, w, h)
      
      const cellW = w / cols
      const cellH = h / rows
      const mx = mouseRef.current.x
      const my = mouseRef.current.y
      const radius = 150

      for (let r = 0; r < rows; r++) {
        for (let c = 0; c < cols; c++) {
          const cx = cellW * (c + 0.5)
          const cy = cellH * (r + 0.5)
          const dx = mx - cx
          const dy = my - cy
          const dist = Math.sqrt(dx * dx + dy * dy)
          
          const angle = dist < radius 
            ? Math.atan2(dy, dx)
            : Math.PI / 2
          
          const len = cellH * 0.35
          const influence = Math.max(0, 1 - dist / radius)
          const opacity = 0.15 + influence * 0.7
          
          ctx.save()
          ctx.translate(cx, cy)
          ctx.rotate(angle)
          ctx.beginPath()
          ctx.moveTo(-len / 2, 0)
          ctx.lineTo(len / 2, 0)
          ctx.strokeStyle = color
          ctx.globalAlpha = opacity
          ctx.lineWidth = 1.5
          ctx.lineCap = 'round'
          ctx.stroke()
          ctx.restore()
        }
      }
      animId = requestAnimationFrame(draw)
    }
    draw()

    return () => {
      cancelAnimationFrame(animId)
      window.removeEventListener('resize', resize)
    }
  }, [rows, cols, color])

  return <canvas ref={canvasRef} className="absolute inset-0 w-full h-full" style={{ opacity: 0.4 }} />
}
