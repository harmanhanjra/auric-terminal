import { useState } from 'react'
import type { CSSProperties, PointerEvent as ReactPointerEvent, ReactNode } from 'react'

interface ResizableSplitPaneProps {
  children: ReactNode[]
  defaultSize: number
  minSize: number
  maxSize?: number
  orientation: 'horizontal' | 'vertical'
  className?: string
  onResizeEnd?: (size: number) => void
}

export function ResizableSplitPane({
  children,
  defaultSize,
  minSize,
  maxSize,
  orientation,
  className = '',
  onResizeEnd,
}: ResizableSplitPaneProps) {
  const [size, setSize] = useState(defaultSize)

  if (children.length !== 2) {
    throw new Error('ResizableSplitPane expects exactly two children')
  }

  const beginResize = (event: ReactPointerEvent<HTMLDivElement>) => {
    event.preventDefault()
    const startX = event.clientX
    const startY = event.clientY
    const startSize = size

    const move = (moveEvent: PointerEvent) => {
      const delta = orientation === 'vertical'
        ? moveEvent.clientX - startX
        : moveEvent.clientY - startY
      const unclamped = startSize + delta
      const next = Math.min(maxSize ?? Number.POSITIVE_INFINITY, Math.max(minSize, unclamped))
      setSize(next)
    }

    const up = () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
      onResizeEnd?.(size)
    }

    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
  }

  const pane1Style: CSSProperties = {
    flex: '0 0 auto',
    [orientation === 'vertical' ? 'width' : 'height']: `${size}px`,
    overflow: 'hidden',
  }

  const pane2Style: CSSProperties = {
    flex: '1 1 auto',
    overflow: 'hidden',
  }

  const splitterStyle: CSSProperties = {
    [orientation === 'vertical' ? 'width' : 'height']: '4px',
    cursor: orientation === 'vertical' ? 'col-resize' : 'row-resize',
    userSelect: 'none',
    touchAction: 'none',
    zIndex: 10,
  }

  return (
    <div
      className={className}
      style={{ display: 'flex', flexDirection: orientation === 'vertical' ? 'row' : 'column' }}
    >
      <div style={pane1Style}>{children[0]}</div>
      <div
        className="auric-resize-handle"
        style={splitterStyle}
        onPointerDown={beginResize}
        role="separator"
        aria-orientation={orientation}
      />
      <div style={pane2Style}>{children[1]}</div>
    </div>
  )
}
