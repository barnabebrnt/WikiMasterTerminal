import { useEffect, useRef, useState } from 'react';

export type LiveEvent = { type: string; data: any };

/** WebSocket /api/ws avec reconnexion automatique. */
export function useLive(onEvent: (e: LiveEvent) => void) {
  const [connected, setConnected] = useState(false);
  const cb = useRef(onEvent);
  cb.current = onEvent;

  useEffect(() => {
    let ws: WebSocket | null = null;
    let stop = false;
    let delay = 500;
    const connect = () => {
      const proto = location.protocol === 'https:' ? 'wss' : 'ws';
      ws = new WebSocket(`${proto}://${location.host}/api/ws`);
      ws.onopen = () => { setConnected(true); delay = 500; };
      ws.onmessage = (m) => cb.current(JSON.parse(m.data));
      ws.onclose = () => {
        setConnected(false);
        if (!stop) setTimeout(connect, (delay = Math.min(delay * 2, 10000)));
      };
    };
    connect();
    return () => { stop = true; ws?.close(); };
  }, []);

  return connected;
}
