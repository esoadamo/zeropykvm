import { useCallback, useEffect, useRef, useState } from 'react';
import './index.css';
import { useLogger, useVideoDecoder, useKvmConnection, useHidInput } from './hooks';

function App() {
  const { logs, log } = useLogger();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);

  // Stable ref to connection.send; updated each render so the backlog callback
  // (which is created once) always picks up the live send function.
  const sendRef = useRef<((data: string) => void) | undefined>(undefined);

  // Stable callback: fires when the decoder backlog state changes and sends
  // a frameskip/resume message to the server over the WebSocket.
  const handleBacklogChange = useCallback((isBacklogged: boolean) => {
    sendRef.current?.(JSON.stringify({ type: 'frameskip', skip: isBacklogged }));
  }, []);

  const decoder = useVideoDecoder(log, canvasRef, videoRef, handleBacklogChange);

  const [isFullscreen, setIsFullscreen] = useState(false);
  const [localCursor, setLocalCursor] = useState(false);
  const [invertScroll, setInvertScroll] = useState(false);
  const [brightness, setBrightness] = useState(120);
  const [contrast, setContrast] = useState(120);
  const [saturate, setSaturate] = useState(100);
  const [crtOpacity, setCrtOpacity] = useState(60);
  const [sigLedOn, setSigLedOn] = useState(true);
  const [elapsedTime, setElapsedTime] = useState(0);

  const screenContainerRef = useRef<HTMLDivElement>(null);
  const crtScreenRef = useRef<HTMLDivElement>(null);
  const terminalRef = useRef<HTMLDivElement>(null);
  const cursorRef = useRef<HTMLDivElement>(null);

  const handleData = useCallback(
    (data: Uint8Array) => {
      decoder.feed(data);
    },
    [decoder]
  );

  const handleConnect = useCallback(() => {
    crtScreenRef.current?.classList.remove('power-off');
    crtScreenRef.current?.classList.add('power-on');
  }, []);

  const handleDisconnect = useCallback(() => {
    crtScreenRef.current?.classList.remove('power-on');
    crtScreenRef.current?.classList.add('power-off');
    decoder.destroy();
    // Exit fullscreen and blur input on disconnect
    if (document.fullscreenElement) {
      document.exitFullscreen().catch(() => {});
    }
    screenContainerRef.current?.blur();
  }, [decoder]);

  const connection = useKvmConnection({
    log,
    onConnect: handleConnect,
    onDisconnect: handleDisconnect,
    onData: handleData,
  });

  // Keep sendRef pointing at the live send function so the stable
  // handleBacklogChange callback can always reach it.
  sendRef.current = connection.send;

  const hidInput = useHidInput({
    send: connection.send,
    log,
    invertScroll,
    cursorRef,
  });

  // Bind HID input to screen container
  useEffect(() => {
    if (screenContainerRef.current) {
      hidInput.bindToElement(screenContainerRef.current);
    }
    return () => {
      hidInput.bindToElement(null);
    };
  }, [hidInput]);

  // Auto-scroll terminal
  useEffect(() => {
    if (terminalRef.current) {
      terminalRef.current.scrollTop = terminalRef.current.scrollHeight;
    }
  }, [logs]);

  // SIG LED blinking effect
  useEffect(() => {
    if (!connection.isConnected) return;
    const interval = setInterval(() => {
      setSigLedOn(Math.random() > 0.5);
    }, 100);
    return () => clearInterval(interval);
  }, [connection.isConnected]);

  // Elapsed time counter
  useEffect(() => {
    if (!connection.stats.startTime) return;
    const update = () => setElapsedTime(Date.now() - connection.stats.startTime!);
    update();
    const interval = setInterval(update, 1000);
    return () => clearInterval(interval);
  }, [connection.stats.startTime]);

  // Global fullscreenchange handler
  useEffect(() => {
    const handleFullscreenChange = () => {
      setIsFullscreen(!!document.fullscreenElement);
      if (!document.fullscreenElement) {
        log('Exited Fullscreen Mode.');
      }
    };

    document.addEventListener('fullscreenchange', handleFullscreenChange);
    return () => document.removeEventListener('fullscreenchange', handleFullscreenChange);
  }, [log]);

  const handlePowerClick = async () => {
    if (connection.isConnected) {
      connection.disconnect();
    } else {
      const initialized = await decoder.init();
      if (initialized) {
        connection.connect();
      }
    }
  };

  const handleFullscreenClick = () => {
    if (!document.fullscreenElement) {
      document.documentElement.requestFullscreen().catch((err) => {
        log(`Error attempting to enable fullscreen: ${err.message}`, 'error');
      });
      setIsFullscreen(true);
      screenContainerRef.current?.focus();
      log('Entered Fullscreen Mode. Press ESC to exit.', 'success');
    } else {
      document.exitFullscreen();
    }
  };

  const filterStyle = `brightness(${brightness}%) contrast(${contrast}%) saturate(${saturate}%)`;

  return (
    <div className="main-console">
      {/* Left: CRT Monitor */}
      <div className="monitor-unit">
        <div className="monitor-casing">
          <div className="monitor-bezel-inner">
            <div
              ref={screenContainerRef}
              className={`screen-container ${isFullscreen ? 'fake-fullscreen' : ''} ${localCursor ? 'local-cursor-active' : ''}`}
              tabIndex={0}
            >
              {/* CRT Effects */}
              <div className="scanlines" style={{ opacity: crtOpacity / 100 }} />
              <div className="screen-glare" style={{ opacity: crtOpacity / 100 }} />

              {/* Local cursor overlay */}
              <div ref={cursorRef} className="local-cursor" style={{ display: localCursor ? 'block' : 'none' }}>
                <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                  <path
                    d="M4 4L10.5 20L12.5 13.5L19 11.5L4 4Z"
                    fill="white"
                    stroke="black"
                    strokeWidth="1.5"
                    strokeLinejoin="round"
                  />
                </svg>
              </div>

              {/* CRT Content Wrapper */}
              <div ref={crtScreenRef} className="crt-content">
                <div className="no-signal" style={{ display: connection.isConnected ? 'none' : 'block' }} />
                {/* WebCodecs canvas (primary) */}
                <canvas
                  ref={canvasRef}
                  className="display-surface"
                  style={{ filter: filterStyle }}
                />
                {/* jMuxer video element (fallback) */}
                <video
                  ref={videoRef}
                  className="display-surface"
                  autoPlay
                  muted
                  playsInline
                  style={{ display: 'none', filter: filterStyle }}
                />
              </div>
            </div>
          </div>
          <div className="brand-badge">MYKVM 2000 Professional</div>
        </div>
        <div className="monitor-base" />
      </div>

      {/* Right: Control Tower */}
      <div className="control-tower">
        {/* Power & Status */}
        <div className="panel-group">
          <div className="power-section">
            <div style={{ display: 'flex', gap: '12px' }}>
              <div className="led-indicator">
                <div className={`led led-red ${connection.isConnected ? 'on' : ''}`} />
                <span>PWR</span>
              </div>
              <div className="led-indicator">
                <div
                  className={`led led-green ${connection.isConnected ? 'on' : ''}`}
                  style={{ opacity: connection.isConnected ? (sigLedOn ? 1 : 0.5) : 1 }}
                />
                <span>SIG</span>
              </div>
              <div className="led-indicator">
                <div className={`led led-blue ${hidInput.isActive ? 'on' : ''}`} />
                <span>HID</span>
              </div>
            </div>
            <button
              className={`retro-btn power-btn ${connection.isConnected ? 'active' : ''}`}
              aria-label="Power"
              onClick={handlePowerClick}
            />
          </div>
        </div>

        {/* Statistics */}
        <div className="panel-group">
          <div className="lcd-panel">
            <div className="lcd-row">
              <span>FRAMES:</span>
              <span className="lcd-value">
                {connection.stats.frameCount.toString().padStart(6, '0')}
              </span>
            </div>
            <div className="lcd-row">
              <span>DATA:</span>
              <span className="lcd-value">{connection.formatBytes(connection.stats.totalBytes)}</span>
            </div>
            <div className="lcd-row">
              <span>RTT:</span>
              <span className="lcd-value">
                {connection.stats.rtt !== null ? `${connection.stats.rtt}ms` : '--'}
              </span>
            </div>
            <div className="lcd-row">
              <span>TIME:</span>
              <span className="lcd-value">
                {connection.formatTime(elapsedTime)}
              </span>
            </div>
          </div>
        </div>

        {/* View Control */}
        <div className="panel-group">
          <button className="retro-btn fullscreen-btn" onClick={handleFullscreenClick}>
            FULLSCREEN
          </button>
          <label className="checkbox-row" style={{ marginTop: '10px' }}>
            <input
              type="checkbox"
              checked={localCursor}
              onChange={(e) => setLocalCursor(e.target.checked)}
            />
            <span>Local Cursor</span>
          </label>
          <label className="checkbox-row" style={{ marginTop: '6px' }}>
            <input
              type="checkbox"
              checked={invertScroll}
              onChange={(e) => setInvertScroll(e.target.checked)}
            />
            <span>Invert Scroll</span>
          </label>
        </div>

        {/* Image Adjustments */}
        <div className="panel-group">
          <div className="slider-group">
            <div className="slider-row">
              <span>BRT</span>
              <input
                type="range"
                min="50"
                max="150"
                value={brightness}
                onChange={(e) => setBrightness(Number(e.target.value))}
              />
            </div>
            <div className="slider-row">
              <span>CNT</span>
              <input
                type="range"
                min="50"
                max="150"
                value={contrast}
                onChange={(e) => setContrast(Number(e.target.value))}
              />
            </div>
            <div className="slider-row">
              <span>SAT</span>
              <input
                type="range"
                min="0"
                max="200"
                value={saturate}
                onChange={(e) => setSaturate(Number(e.target.value))}
              />
            </div>
            <div className="slider-row">
              <span>CRT</span>
              <input
                type="range"
                min="0"
                max="100"
                value={crtOpacity}
                onChange={(e) => setCrtOpacity(Number(e.target.value))}
              />
            </div>
          </div>
        </div>

        {/* Log Terminal */}
        <div className="panel-group" style={{ flexGrow: 1, display: 'flex', flexDirection: 'column' }}>
          <div ref={terminalRef} className="terminal-box">
            {logs.map((entry) => (
              <div key={entry.id} className={`log-entry ${entry.type}`}>
                {entry.message}
              </div>
            ))}
            <div>
              <span className="cursor" />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default App;
