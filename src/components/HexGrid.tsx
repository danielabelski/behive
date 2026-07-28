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
    window.addEventListener('mousemove', handleMouse)

    const drawHex = (cx: number, cy: number, r: number, opacity: number, filled: boolean) => {
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
      ctx.strokeStyle = glowColor
      ctx.globalAlpha = opacity
      ctx.lineWidth = 1
      ctx.stroke()
    }

    let animId: number
    const draw = () => {
      timeRef.current += 0.01
      const w = canvas.offsetWidth
      const h = canvas.offsetHeight
      ctx.clearRect(0, 0, w, h)
      
      const hexH = cellSize * Math.sqrt(3)
      const mx = mouseRef.current.x
      const my = mouseRef.current.y

      for (let row = -1; row < h / hexH + 1; row++) {
        for (let col = -1; col < w / (cellSize * 1.5) + 1; col++) {
          const cx = col * cellSize * 1.5
          const cy = row * hexH + (col % 2 === 0 ? 0 : hexH / 2)
          
          const dx = mx - cx
          const dy = my - cy
          const dist = Math.sqrt(dx * dx + dy * dy)
          
          const mouseInfluence = Math.max(0, 1 - dist / 200)
          const pulse = Math.sin(timeRef.current * 2 + col * 0.3 + row * 0.5) * 0.5 + 0.5
          const baseOpacity = 0.06
          const opacity = baseOpacity + mouseInfluence * 0.5 + pulse * 0.03
          const filled = mouseInfluence > 0.3 || (pulse > 0.9 && Math.random() > 0.99)
          
          drawHex(cx, cy, cellSize * 0.45, opacity, filled)
        }
      }
      
      ctx.globalAlpha = 1
      animId = requestAnimationFrame(draw)
    }
    draw()

    return () => {
      cancelAnimationFrame(animId)
      window.removeEventListener('resize', resize)
      window.removeEventListener('mousemove', handleMouse)
    }
  }, [cellSize, glowColor])

  return <canvas ref={canvasRef} className="absolute inset-0 w-full h-full pointer-events-none" />
}
