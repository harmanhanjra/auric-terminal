import { useEffect, useRef, useState } from 'react'
import { clsx } from 'clsx'

interface AnimatedValueProps {
  value: number
  format?: (value: number) => string
  className?: string
  flash?: boolean
}

export function AnimatedValue({
  value,
  format = (v) => String(v),
  className,
  flash = true,
}: AnimatedValueProps) {
  const previous = useRef(value)
  const [direction, setDirection] = useState<'up' | 'down' | null>(null)

  useEffect(() => {
    if (!flash || value === previous.current) return
    setDirection(value > previous.current ? 'up' : 'down')
    previous.current = value
    const timer = window.setTimeout(() => setDirection(null), 420)
    return () => window.clearTimeout(timer)
  }, [flash, value])

  return (
    <span
      className={clsx(
        'tnum transition-colors duration-300',
        direction === 'up' && 'text-bull-400',
        direction === 'down' && 'text-bear-400',
        className,
      )}
    >
      {format(value)}
    </span>
  )
}
