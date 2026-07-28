'use client'
import { motion, useScroll, useTransform } from 'motion/react'
import { useRef } from 'react'

interface VelocityScrollProps {
  texts: string[]
  baseSpeed?: number
  className?: string
}

export default function VelocityScroll({ texts, baseSpeed = 50, className = '' }: VelocityScrollProps) {
  const ref = useRef<HTMLDivElement>(null)
  const { scrollYProgress } = useScroll({ target: ref, offset: ['start end', 'end start'] })
  const x1 = useTransform(scrollYProgress, [0, 1], [0, -baseSpeed * texts.length])
  const x2 = useTransform(scrollYProgress, [0, 1], [-baseSpeed * texts.length, 0])

  return (
    <div ref={ref} className={`overflow-hidden py-4 ${className}`}>
      <motion.div className="flex whitespace-nowrap gap-8" style={{ x: x1 }}>
        {[...texts, ...texts, ...texts].map((t, i) => (
          <span key={i} className="text-lg font-mono text-gold-muted/40 uppercase tracking-widest flex items-center gap-4">
            <span className="text-gold/60">⬡</span> {t}
          </span>
        ))}
      </motion.div>
      <motion.div className="flex whitespace-nowrap gap-8 mt-3" style={{ x: x2 }}>
        {[...texts, ...texts, ...texts].map((t, i) => (
          <span key={i} className="text-lg font-mono text-gold-muted/30 uppercase tracking-widest flex items-center gap-4">
            <span className="text-amber/40">⬢</span> {t}
          </span>
        ))}
      </motion.div>
    </div>
  )
}
