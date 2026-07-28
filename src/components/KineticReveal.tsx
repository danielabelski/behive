'use client'
import { motion, useInView } from 'motion/react'
import { useRef } from 'react'

interface KineticRevealProps {
  text: string
  className?: string
  delay?: number
  stagger?: number
}

export default function KineticReveal({ text, className = '', delay = 0, stagger = 0.04 }: KineticRevealProps) {
  const ref = useRef<HTMLDivElement>(null)
  const isInView = useInView(ref, { once: true, margin: '-50px' })
  
  const words = text.split(' ')

  return (
    <div ref={ref} className={`flex flex-wrap gap-x-[0.3em] ${className}`}>
      {words.map((word, wi) => (
        <span key={wi} className="inline-flex overflow-hidden">
          {word.split('').map((char, ci) => {
            const i = words.slice(0, wi).join(' ').length + ci + wi
            return (
              <motion.span
                key={`${wi}-${ci}`}
                initial={{ y: '100%', opacity: 0, filter: 'blur(8px)' }}
                animate={isInView ? { y: '0%', opacity: 1, filter: 'blur(0px)' } : {}}
                transition={{
                  duration: 0.5,
                  delay: delay + i * stagger,
                  ease: [0.25, 0.4, 0, 1]
                }}
                className="inline-block"
              >
                {char}
              </motion.span>
            )
          })}
        </span>
      ))}
    </div>
  )
}
