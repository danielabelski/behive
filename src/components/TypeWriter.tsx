'use client'
import { useState, useEffect, useRef } from 'react'
import { useInView } from 'motion/react'

interface TypeWriterProps {
  words: string[]
  className?: string
  typingSpeed?: number
  deletingSpeed?: number
  pauseTime?: number
}

export default function TypeWriter({ 
  words, 
  className = '', 
  typingSpeed = 80, 
  deletingSpeed = 50, 
  pauseTime = 2000 
}: TypeWriterProps) {
  const [text, setText] = useState('')
  const [wordIndex, setWordIndex] = useState(0)
  const [isDeleting, setIsDeleting] = useState(false)
  const ref = useRef<HTMLSpanElement>(null)
  const isInView = useInView(ref, { once: true })

  useEffect(() => {
    if (!isInView) return
    
    const current = words[wordIndex]
    
    const timeout = setTimeout(() => {
      if (!isDeleting) {
        setText(current.substring(0, text.length + 1))
        if (text === current) {
          setTimeout(() => setIsDeleting(true), pauseTime)
        }
      } else {
        setText(current.substring(0, text.length - 1))
        if (text === '') {
          setIsDeleting(false)
          setWordIndex((prev) => (prev + 1) % words.length)
        }
      }
    }, isDeleting ? deletingSpeed : typingSpeed)

    return () => clearTimeout(timeout)
  }, [text, isDeleting, wordIndex, words, isInView, typingSpeed, deletingSpeed, pauseTime])

  return (
    <span ref={ref} className={className}>
      {text}
      <span className="animate-pulse text-gold">▋</span>
    </span>
  )
}
