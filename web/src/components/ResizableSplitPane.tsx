import { useState, useRef, useEffect } from 'react';
import type { MouseEvent } from 'react';

interface ResizableSplitPaneProps {
  children: React.ReactNode[]; // Expect exactly two children
  defaultSize: number; // in pixels for first pane
  minSize: number; // in pixels
  maxSize?: number; // in pixels
  orientation: 'horizontal' | 'vertical';
  className?: string;
  onResizeEnd?: (size: number) => void;
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
  if (children.length !== 2) {
    throw new Error('ResizableSplitPane expects exactly two children');
  }

  const [size, setSize] = useState(defaultSize);
  const [isDragging, setIsDragging] = useState(false);
  const dragStartRef = useRef({ x: 0, y: 0, size: 0 });

  const handleMouseDown = (e: MouseEvent) => {
    e.preventDefault();
    setIsDragging(true);

    if (orientation === 'vertical') {
      dragStartRef.current = { x: e.clientX, y: e.clientY, size };
    } else {
      dragStartRef.current = { x: e.clientX, y: e.clientY, size };
    }
  };

  const handleMouseMove = (e: globalThis.MouseEvent) => {
    if (!isDragging) return;

    const deltaX = e.clientX - dragStartRef.current.x;
    const deltaY = e.clientY - dragStartRef.current.y;

    let newSize = size;

    if (orientation === 'vertical') {
      newSize = dragStartRef.current.size + deltaX;
    } else {
      newSize = dragStartRef.current.size + deltaY;
    }

    // Apply constraints
    if (minSize !== undefined) {
      newSize = Math.max(newSize, minSize);
    }
    if (maxSize !== undefined) {
      newSize = Math.min(newSize, maxSize);
    }

    setSize(newSize);
  };

  const handleMouseUp = () => {
    if (isDragging) {
      setIsDragging(false);
      onResizeEnd?.(size);
    }
  };

  useEffect(() => {
    if (isDragging) {
      window.addEventListener('mousemove', handleMouseMove);
      window.addEventListener('mouseup', handleMouseUp);
      return () => {
        window.removeEventListener('mousemove', handleMouseMove);
        window.removeEventListener('mouseup', handleMouseUp);
      };
    }
  }, [isDragging]);

  const pane1Style: React.CSSProperties = {
    flex: '0 0 auto',
    [orientation === 'vertical' ? 'width' : 'height']: `${size}px`,
    overflow: 'hidden',
  };

  const pane2Style: React.CSSProperties = {
    flex: '1 1 auto',
    overflow: 'hidden',
  };

  const splitterStyle: React.CSSProperties = {
    [orientation === 'vertical' ? 'width' : 'height']: '4px',
    cursor: orientation === 'vertical' ? 'col-resize' : 'row-resize',
    userSelect: 'none',
    touchAction: 'none',
    background: 'rgba(128, 128, 128, 0.2)',
    zIndex: 10,
  };

  return (
    <div
      className={className}
      style={{ display: 'flex', flexDirection: orientation === 'vertical' ? 'row' : 'column' }}
    >
      <div style={pane1Style}>{children[0]}</div>
      <div style={splitterStyle} onMouseDown={handleMouseDown} />
      <div style={pane2Style}>{children[1]}</div>
    </div>
  );
}