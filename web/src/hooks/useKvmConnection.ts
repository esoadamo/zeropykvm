import { useCallback, useRef, useState } from 'react';

export interface ConnectionStats {
  frameCount: number;
  totalBytes: number;
  startTime: number;
  rtt: number | null;
}

function getWebSocketUrl(): string {
  // Use the same host (including port) as the current page so that reverse
  // proxies forwarding on a non-default port are handled correctly.
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const host = window.location.host || '127.0.0.1';
  return `${protocol}//${host}`;
}

function formatBytes(bytes: number): string {
  const mb = bytes / (1024 * 1024);
  return mb.toFixed(1) + 'M';
}

function formatTime(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000);
  const h = Math.floor(totalSeconds / 3600).toString().padStart(2, '0');
  const m = Math.floor((totalSeconds % 3600) / 60).toString().padStart(2, '0');
  const s = (totalSeconds % 60).toString().padStart(2, '0');
  return `${h}:${m}:${s}`;
}

interface UseKvmConnectionOptions {
  log: (msg: string, type?: 'info' | 'error' | 'success') => void;
  onConnect?: () => void;
  onDisconnect?: () => void;
  onData?: (data: Uint8Array) => void;
}

export function useKvmConnection({
  log,
  onConnect,
  onDisconnect,
  onData,
}: UseKvmConnectionOptions) {
  const [isConnected, setIsConnected] = useState(false);
  const [stats, setStats] = useState<ConnectionStats>({
    frameCount: 0,
    totalBytes: 0,
    startTime: 0,
    rtt: null,
  });

  const wsRef = useRef<WebSocket | null>(null);
  const statsIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pingIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const connect = useCallback(async () => {
    if (wsRef.current) {
      // Already connected, disconnect first
      return;
    }

    setStats({ frameCount: 0, totalBytes: 0, startTime: Date.now(), rtt: null });

    const url = getWebSocketUrl();
    log(`Dialing ${url}...`);

    try {
      const ws = new WebSocket(url);
      ws.binaryType = 'arraybuffer';
      wsRef.current = ws;

      ws.onopen = () => {
        log('Connection Established.', 'success');
        setIsConnected(true);
        setStats((prev) => ({ ...prev, startTime: Date.now() }));
        onConnect?.();

        // Start time update interval
        statsIntervalRef.current = setInterval(() => {
          setStats((prev) => ({ ...prev })); // Trigger re-render for time display
        }, 1000);

        // Start periodic RTT ping
        pingIntervalRef.current = setInterval(() => {
          if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
            wsRef.current.send(JSON.stringify({ type: 'ping', ts: performance.now() }));
          }
        }, 2000);
      };

      // Stats tracking
      let lastPacketTime = 0;
      let stallCount = 0;
      const STALL_THRESHOLD_MS = 50; // Warn if packet gap > 50ms

      ws.onmessage = (event) => {
        // Handle text messages (pong replies)
        if (typeof event.data === 'string') {
          try {
            const msg = JSON.parse(event.data);
            if (msg.type === 'pong' && typeof msg.ts === 'number') {
              const rtt = Math.round(performance.now() - msg.ts);
              setStats((prev) => ({ ...prev, rtt }));
            }
          } catch {
            // ignore malformed text frames
          }
          return;
        }

        const now = performance.now();
        const packet = new Uint8Array(event.data);

        // Warn on stalls
        if (lastPacketTime > 0) {
          const intervalMs = now - lastPacketTime;
          if (intervalMs > STALL_THRESHOLD_MS) {
            stallCount++;
            console.warn(
              `[WS STALL #${stallCount}] Packet gap: ${intervalMs.toFixed(1)}ms`
            );
          }
        }
        lastPacketTime = now;

        // Feed data to decoder
        onData?.(packet);

        // Update stats
        setStats((prev) => ({
          ...prev,
          frameCount: prev.frameCount + 1,
          totalBytes: prev.totalBytes + packet.byteLength,
        }));
      };

      ws.onclose = () => {
        log('Carrier Lost (Connection Closed).', 'error');
        wsRef.current = null;
        setIsConnected(false);
        if (statsIntervalRef.current) {
          clearInterval(statsIntervalRef.current);
          statsIntervalRef.current = null;
        }
        if (pingIntervalRef.current) {
          clearInterval(pingIntervalRef.current);
          pingIntervalRef.current = null;
        }
        onDisconnect?.();
      };

      ws.onerror = (err) => {
        log('Communication Error.', 'error');
        console.error(err);
      };
    } catch (e) {
      log(`Connection Failed: ${(e as Error).message}`, 'error');
    }
  }, [log, onConnect, onDisconnect, onData]);

  const disconnect = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }

    if (statsIntervalRef.current) {
      clearInterval(statsIntervalRef.current);
      statsIntervalRef.current = null;
    }

    if (pingIntervalRef.current) {
      clearInterval(pingIntervalRef.current);
      pingIntervalRef.current = null;
    }

    setIsConnected(false);
    log('System Disconnected.');
    onDisconnect?.();
  }, [log, onDisconnect]);

  const send = useCallback((data: string | ArrayBufferLike | Blob | ArrayBufferView) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(data);
    }
  }, []);

  return {
    isConnected,
    stats,
    connect,
    disconnect,
    send,
    formatBytes,
    formatTime,
  };
}

