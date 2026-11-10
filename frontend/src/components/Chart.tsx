import { useEffect, useRef } from 'react';
import {
  CandlestickSeries, HistogramSeries, createChart,
  type IChartApi, type ISeriesApi, type UTCTimestamp,
} from 'lightweight-charts';
import type { Candle } from '../api';

// lightweight-charts affiche en UTC : on décale pour l'heure locale.
const local = (ms: number) => ((ms - new Date(ms).getTimezoneOffset() * 60_000) / 1000) as UTCTimestamp;

export function Chart({ data }: { data: Candle[] }) {
  const el = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi>();
  const candles = useRef<ISeriesApi<'Candlestick'>>();
  const volume = useRef<ISeriesApi<'Histogram'>>();

  useEffect(() => {
    const c = createChart(el.current!, {
      autoSize: true,
      layout: { background: { color: 'transparent' }, textColor: '#8b949e', fontFamily: 'JetBrains Mono, Menlo, monospace', fontSize: 11 },
      grid: { vertLines: { color: '#1b2129' }, horzLines: { color: '#1b2129' } },
      timeScale: { timeVisible: true, borderColor: '#2a313c' },
      rightPriceScale: { borderColor: '#2a313c' },
      crosshair: { mode: 0 },
    });
    candles.current = c.addSeries(CandlestickSeries, {
      upColor: '#26a69a', downColor: '#ef5350', borderVisible: false,
      wickUpColor: '#26a69a', wickDownColor: '#ef5350',
    });
    volume.current = c.addSeries(HistogramSeries, { priceScaleId: 'vol', priceFormat: { type: 'volume' }, color: '#3b4452' });
    c.priceScale('vol').applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    chart.current = c;
    return () => c.remove();
  }, []);

  useEffect(() => {
    candles.current?.setData(data.map((d) => ({ time: local(d.t), open: d.o, high: d.h, low: d.l, close: d.c })));
    volume.current?.setData(data.map((d) => ({ time: local(d.t), value: d.v, color: d.c >= d.o ? '#1f4d48' : '#5a2a2a' })));
  }, [data]);

  return <div ref={el} className="chart" />;
}
