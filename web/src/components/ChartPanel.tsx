import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  createChart,
  ColorType,
  CandlestickSeries,
  LineSeries,
  HistogramSeries,
  type IChartApi,
  type ISeriesApi,
} from 'lightweight-charts'
import { clsx } from 'clsx'
import { Layers, Bell, Settings2, Grid3X3, Zap, Activity, HeartPulse, TrendingUp } from 'lucide-react'
import { api } from '../lib/api'
import type { Candle, Quote } from '../lib/types'
const TIMEFRAMES = ['M1', 'M5', 'M15', 'M30', 'H1', 'H4', 'D1', 'W1']
const INDICATORS = [
  { id: 'ema20', name: 'EMA 20', color: '#7a95ff' },
  { id: 'ema50', name: 'EMA 50', color: '#ff9f1c' },
  { id: 'bbands', name: 'Bollinger Bands', color: '#4cc9f0' },
  { id: 'vwap', name: 'VWAP', color: '#f72585' },
  { id: 'ichimoku', name: 'Ichimoku', color: '#8ac926' },
]

const PERIODS = [
  { id: '1D', label: '1D' },
  { id: '1W', label: '1W' },
  { id: '1M', label: '1M' },
  { id: '3M', label: '3M' },
  { id: 'YTD', label: 'YTD' },
  { id: '1Y', label: '1Y' },
  { id: 'ALL', label: 'ALL' },
]

interface ChartPanelProps {
  quote?: Quote
  activeSymbol?: string
  onSelectSymbol?: (symbol: string) => void
}

export function ChartPanel({ quote: _quote, activeSymbol = 'XAUUSD', onSelectSymbol }: ChartPanelProps) {
  const [tf, setTf] = useState('M15')
  const [period, setPeriod] = useState('1M')
  const [indicators] = useState<string[]>(['ema20'])
  const [chartType, setChartType] = useState<'Candlestick' | 'Line' | 'Bar' | 'HeikinAshi'>('Candlestick')
  const [showDrawingTools, setShowDrawingTools] = useState(false)
  const [symbols, setSymbols] = useState<string[]>([activeSymbol])

  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const lineSeriesRef = useRef<ISeriesApi<'Line'> | null>(null)
  const histogramSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null)

  const indicatorSeriesRefs = useRef<Map<string, ISeriesApi<'Line'>>>(new Map())

  const { data, isLoading } = useQuery({
    queryKey: ['candles', tf, activeSymbol],
    queryFn: () => api.candles(tf, 300, activeSymbol),
    staleTime: 30_000,
  })

  const candles: Candle[] = data?.values ?? []

  useEffect(() => {
    if (!containerRef.current) return
    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: '#7f8797',
        fontSize: 10,
        fontFamily: "'JetBrains Mono', monospace",
      },
      grid: {
        vertLines: { color: 'rgba(26,32,60,0.45)' },
        horzLines: { color: 'rgba(26,32,60,0.45)' },
      },
      rightPriceScale: {
        borderColor: 'rgba(30,37,64,0.7)',
        scaleMargins: { top: 0.08, bottom: 0.1 },
      },
      timeScale: {
        borderColor: 'rgba(30,37,64,0.7)',
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 4,
      },
      crosshair: {
        vertLine: { color: 'rgba(138,147,168,0.35)', labelBackgroundColor: '#1e2540' },
        horzLine: { color: 'rgba(138,147,168,0.35)', labelBackgroundColor: '#1e2540' },
      },
      handleScroll: { mouseWheel: true, pressedMouseMove: true },
      handleScale: { axisPressedMouseMove: true, mouseWheel: true, pinch: true },
    })

    // Create main series based on chart type
    let mainSeries: ISeriesApi<'Candlestick'> | ISeriesApi<'Line'>

    switch (chartType) {
      case 'Line':
        mainSeries = chart.addSeries(LineSeries, {
          color: '#7a95ff',
          lineWidth: 2,
          priceLineVisible: false,
          lastValueVisible: false,
        })
        lineSeriesRef.current = mainSeries
        break
      default:
        mainSeries = chart.addSeries(CandlestickSeries, {
          upColor: '#16c784',
          downColor: '#ea3943',
          borderUpColor: '#16c784',
          borderDownColor: '#ea3943',
          wickUpColor: '#16c784',
          wickDownColor: '#ea3943',
        })
        candleSeriesRef.current = mainSeries as ISeriesApi<'Candlestick'>
        break
    }

    // Create volume histogram series
    const volumeSeries = chart.addSeries(HistogramSeries, {
      color: '#26a69a',
      priceFormat: {
        type: 'volume',
      },
      priceScaleId: '',
    })
    histogramSeriesRef.current = volumeSeries

    chartRef.current = chart

    const onResize = () => chart.applyOptions({ width: containerRef.current!.clientWidth })
    const ro = new ResizeObserver(onResize)
    ro.observe(containerRef.current)

    return () => {
      ro.disconnect()
      chart.remove()
      chartRef.current = null
    }
  }, [chartType])

  useEffect(() => {
    if (!candles.length || !chartRef.current) return

    // Update main series
    if (chartType === 'Line' && lineSeriesRef.current) {
      const seriesData = candles.map((c) => ({
        time: ((c.time ?? 0) / 1000) as unknown as string,
        value: c.close,
      }))
      lineSeriesRef.current.setData(seriesData)
    } else if (chartType !== 'Line' && candleSeriesRef.current) {
      const seriesData = candles.map((c) => ({
        time: ((c.time ?? 0) / 1000) as unknown as string,
        open: c.open,
        high: c.high,
        low: c.low,
        close: c.close,
      }))
      candleSeriesRef.current.setData(seriesData)
    }

    // Update volume series
    if (histogramSeriesRef.current) {
      const volumeData = candles.map((c) => ({
        time: ((c.time ?? 0) / 1000) as unknown as string,
        value: c.volume,
      }))
      histogramSeriesRef.current.setData(volumeData)
    }

    // Update indicator series
    updateIndicatorSeries(candles)

    chartRef.current?.timeScale().fitContent()
  }, [candles, chartType])

  const updateIndicatorSeries = (candles: Candle[]) => {
    if (!chartRef.current) return

    // Remove old series that are no longer active
    indicatorSeriesRefs.current.forEach((series, id) => {
      if (!indicators.includes(id)) {
        chartRef.current?.removeSeries(series)
        indicatorSeriesRefs.current.delete(id)
      }
    })

    // Add or update active indicators
    indicators.forEach(id => {
      const indicator = INDICATORS.find(i => i.id === id)
      if (!indicator) return

      let series = indicatorSeriesRefs.current.get(id)
      if (!series) {
        series = chartRef.current?.addSeries(LineSeries, {
          color: indicator.color,
          lineWidth: 1,
          priceLineVisible: false,
          lastValueVisible: false,
        })
        if (series) {
          indicatorSeriesRefs.current.set(id, series)
        }
      }

      if (series) {
        let data: { time: string; value: number }[] = []

        switch (id) {
          case 'ema20':
            data = calculateEMA(candles, 20)
            break
          case 'ema50':
            data = calculateEMA(candles, 50)
            break
          // Add more indicator calculations as needed
          default:
            // For now, just use close price as placeholder
            data = candles.map(c => ({
              time: ((c.time ?? 0) / 1000) as unknown as string,
              value: c.close,
            }))
        }

        series.setData(data)
      }
    })
  }

  const calculateEMA = (candles: Candle[], period: number): { time: string; value: number }[] => {
    if (candles.length === 0) return []

    const closes = candles.map(c => c.close)
    const k = 2 / (period + 1)
    let ema = closes[0]
    const emaValues: number[] = [ema]

    for (let i = 1; i < closes.length; i++) {
      ema = closes[i] * k + ema * (1 - k)
      emaValues.push(ema)
    }

    return candles.map((c, i) => ({
      time: ((c.time ?? 0) / 1000) as unknown as string,
      value: emaValues[i],
    })).filter(v => v.value !== null) as { time: string; value: number }[]
  }

  const last = candles[candles.length - 1]

  return (
    <div className="flex min-h-0 flex-col">
      {/* Chart Header with Controls */}
      <div className="flex h-12 shrink-0 items-center gap-2 border-b border-ink-700/70 bg-ink-900/60 px-3">
        <div className="flex items-center gap-2">
          <span className="text-[11px] font-bold text-fg-100">
            {activeSymbol} <span className="text-[9px] font-medium text-fg-500">· Demo</span>
          </span>
        </div>

        <div className="flex-1 flex items-center justify-center gap-3">
          {/* Timeframe Selector */}
          <div className="flex items-center gap-1">
            {TIMEFRAMES.map((t) => (
              <button
                key={t}
                onClick={() => setTf(t)}
                className={clsx(
                  'rounded px-2 py-1 text-[10px] font-semibold transition-colors',
                  tf === t
                    ? 'bg-gold-600/10 text-gold-300 ring-1 ring-gold-600/30'
                    : 'text-fg-500 hover:bg-ink-800 hover:text-fg-300',
                )}
              >
                {t}
              </button>
            ))}
          </div>

          {/* Period Selector */}
          <div className="flex items-center gap-1">
            <span className="text-[9px] font-medium text-fg-500">Period:</span>
            {PERIODS.map((p) => (
              <button
                key={p.id}
                onClick={() => setPeriod(p.id)}
                className={clsx(
                  'rounded px-2 py-1 text-[9px] font-semibold transition-colors',
                  period === p.id
                    ? 'bg-gold-600/10 text-gold-300 ring-1 ring-gold-600/30'
                    : 'text-fg-500 hover:bg-ink-800 hover:text-fg-300',
                )}
              >
                {p.label}
              </button>
            ))}
          </div>

          {/* Chart Type Selector */}
          <div className="flex items-center gap-1">
            <span className="text-[9px] font-medium text-fg-500">Type:</span>
            <button
              onClick={() => {
                const types = ['Candlestick', 'Line', 'Bar', 'HeikinAshi'] as const
                const currentIndex = types.indexOf(chartType)
                const nextIndex = (currentIndex + 1) % types.length
                setChartType(types[nextIndex])
              }}
              className={clsx(
                'rounded px-2 py-1 text-[9px] font-semibold transition-colors',
                'bg-gold-600/10 text-gold-300 ring-1 ring-gold-600/30'
              )}
            >
              {chartType === 'Candlestick' ? '🕯️' : chartType === 'Line' ? '📈' : chartType === 'Bar' ? '📊' : '🕒'}
            </button>
          </div>

          {/* Indicators Button */}
          <button
            onClick={() => setShowDrawingTools(!showDrawingTools)}
            className={clsx(
              'flex items-center gap-1 rounded px-2 py-1 text-[10px] font-medium text-fg-400 hover:bg-ink-800 hover:text-fg-200',
              showDrawingTools ? 'bg-gold-600/20' : ''
            )}
          >
            <Zap className="h-3.5 w-3.5" /> Studies
          </button>

          {/* Symbol Comparison */}
          <div className="relative">
            <button
              onClick={() => {
                // In a real implementation, this would open a symbol search dialog
                setSymbols(['XAUUSD', 'XAGUSD', 'USOIL']) // Demo
              }}
              className={clsx(
                'flex items-center gap-1 rounded px-2 py-1 text-[10px] font-medium text-fg-400 hover:bg-ink-800 hover:text-fg-200'
              )}
            >
              <Activity className="h-3.5 w-3.5" /> Compare
            </button>
            {symbols.length > 1 && (
              <div className="absolute left-0 top-full mt-1 w-48 bg-ink-800/90 border border-ink-700 rounded-md p-2 z-20">
                {symbols.map((symbol, index) => (
                  <div
                    key={index}
                    onClick={() => onSelectSymbol?.(symbol)}
                    className={clsx(
                      'flex items-center gap-1 p-1 rounded hover:bg-ink-700',
                      activeSymbol === symbol ? 'bg-gold-600/20' : ''
                    )}
                  >
                    <span className="text-[10px] font-medium text-fg-100">{symbol}</span>
                    {activeSymbol === symbol && (
                      <span className="ml-auto text-[9px] font-bold text-gold-400">●</span>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Drawing Tools Toggle */}
          <button
            onClick={() => setShowDrawingTools(!showDrawingTools)}
            className={clsx(
              'flex items-center gap-1 rounded px-2 py-1 text-[10px] font-medium text-fg-400 hover:bg-ink-800 hover:text-fg-200'
            )}
          >
            <HeartPulse className="h-3.5 w-3.5" /> Drawing
          </button>
        </div>

        <div className="flex items-center gap-2">
          <button className="flex items-center gap-1 rounded px-2 py-1 text-[10px] font-medium text-fg-400 hover:bg-ink-800 hover:text-fg-200">
            <Layers className="h-3.5 w-3.5" /> Candles
          </button>
          <button className="flex items-center gap-1 rounded px-2 py-1 text-[10px] font-medium text-fg-400 hover:bg-ink-800 hover:text-fg-200">
            <Bell className="h-3.5 w-3.5" /> Alerts
          </button>
          <div className="mx-1 h-4 w-px bg-ink-700" />
          <div className="ml-auto flex items-center gap-0.5">
            <button className="rounded px-2 py-1 text-[10px] font-medium text-fg-400 hover:bg-ink-800 hover:text-fg-200">
              <Grid3X3 className="h-3.5 w-3.5" />
            </button>
            <button className="flex items-center gap-1 rounded px-2 py-1 text-[10px] font-medium text-fg-400 hover:bg-ink-800 hover:text-fg-200">
              <Settings2 className="h-3.5 w-3.5" /> Scalp
            </button>
          </div>
        </div>
      </div>

      {/* Drawing Tools Panel (when active) */}
      {showDrawingTools && (
        <div className="flex h-10 items-center gap-2 border-b border-ink-700/70 bg-ink-900/60 px-3">
          <span className="text-[10px] font-bold text-fg-100">Drawing Tools:</span>
          <button className="flex h-8 w-8 items-center justify-center rounded-lg text-fg-400 hover:bg-ink-800 hover:text-fg-200">
            <TrendingUp className="h-4 w-4" /> Trendline
          </button>
          <button className="flex h-8 w-8 items-center justify-center rounded-lg text-fg-400 hover:bg-ink-800 hover:text-fg-200">
            <Activity className="h-4 w-4" /> Horizontal Line
          </button>
          <button className="flex h-8 w-8 items-center justify-center rounded-lg text-fg-400 hover:bg-ink-800 hover:text-fg-200">
            <Zap className="h-4 w-4" /> Vertical Line
          </button>
          <button className="flex h-8 w-8 items-center justify-center rounded-lg text-fg-400 hover:bg-ink-800 hover:text-fg-200">
            <Bell className="h-4 w-4" /> Fibonacci
          </button>
          <button className="flex h-8 w-8 items-center justify-center rounded-lg text-fg-400 hover:bg-ink-800 hover:text-fg-200">
            <Grid3X3 className="h-4 w-4" /> Text
          </button>
          <button
            onClick={() => setShowDrawingTools(false)}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-fg-400 hover:bg-ink-800 hover:text-fg-200"
          >
            <Bell className="h-4 w-4" /> Done
          </button>
        </div>
      )}

      {/* Chart Container - Split Vertically for Price and Volume */}
      <div className="relative min-h-0 flex-1">
        {isLoading && !candles.length ? (
          <div className="flex h-full items-center justify-center text-[11px] text-fg-500">
            Loading candles…
          </div>
        ) : null}

        {/* Main Chart Area (Price) */}
        <div ref={containerRef} className="absolute inset-0" />

        {/* Volume Pane (below price chart) */}
        <div className="absolute left-0 bottom-0 right-0 h-[80px] pointer-events-none">
          <div className="flex h-full items-center gap-2 px-2 pt-1">
            <span className="text-[9px] font-medium text-fg-500">Volume</span>
            <div className="flex-1 h-[6px] bg-ink-800/50 rounded overflow-hidden">
              <div className="h-full w-[60%] bg-26a69a" />
            </div>
            <span className="tnum text-[9px] text-fg-500">1.25M</span>
          </div>
        </div>

        {/* Price Data Display (Top Left) */}
        <div className="pointer-events-none absolute left-3 top-3 z-20 flex flex-col gap-1 bg-ink-900/70 px-2 py-1.5 rounded-md border border-ink-700/60 backdrop-blur">
          <div className="flex items-center gap-2">
            <span className="text-[9px] font-bold text-fg-100">O</span>
            <span className="tnum text-[10px] text-fg-300">{last ? last.open.toFixed(2) : '—'}</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-[9px] font-bold text-fg-100">H</span>
            <span className="tnum text-[10px] text-fg-300">{last ? last.high.toFixed(2) : '—'}</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-[9px] font-bold text-fg-100">L</span>
            <span className="tnum text-[10px] text-fg-300">{last ? last.low.toFixed(2) : '—'}</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-[9px] font-bold text-fg-100">C</span>
            <span className="tnum text-[10px] text-fg-300">{last ? last.close.toFixed(2) : '—'}</span>
          </div>
        </div>

        {/* Position/P&L Overlay (when holding position) */}
        <div className="pointer-events-none absolute bottom-4 left-3 z-20 flex items-center gap-2 rounded-md border border-bull-500/25 bg-bull-500/10 px-2 py-1 text-[10px] font-semibold text-bull-500 backdrop-blur">
          <span className="h-1.5 w-1.5 rounded-full bg-bull-500 shadow-[0_0_6px_rgba(22,199,132,0.8)]" />
          <span>LONG 0.25</span>
          <span className="tnum ml-1">+$425.50</span>
        </div>

        {/* Indicator Values Display (Top Right) */}
        <div className="pointer-events-none absolute top-3 right-3 z-20 flex flex-col gap-1 bg-ink-900/70 px-2 py-1.5 rounded-md border border-ink-700/60 backdrop-blur">
          {indicators.map((id) => {
            const indicator = INDICATORS.find(i => i.id === id)
            if (!indicator) return null

            // Get last value from series (simplified)
            const lastValue = '—' // In reality, we'd get this from the series data

            return (
              <div key={id} className="flex items-center gap-1">
                <span className="text-[9px] font-medium text-fg-500">{indicator.name}</span>
                <span className={clsx('tnum text-[10px] font-semibold', indicator.id === 'ema20' ? 'text-fg-200' : 'text-fg-300')}>
                  {lastValue}
                </span>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
