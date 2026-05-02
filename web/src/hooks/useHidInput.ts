import { useCallback, useEffect, useRef, useState } from 'react';

const MOUSE_THROTTLE_MS = 16; // ~60 Hz

interface UseHidInputOptions {
  send: (data: string) => void;
  log: (msg: string, type?: 'info' | 'error' | 'success') => void;
  invertScroll?: boolean;
  cursorRef?: React.RefObject<HTMLDivElement | null>;
}

export function useHidInput({ send, log, invertScroll = false, cursorRef }: UseHidInputOptions) {
  const [isActive, setIsActive] = useState(false);
  const lastMouseMoveRef = useRef(0);
  const containerRef = useRef<HTMLElement | null>(null);

  const handleFocus = useCallback(() => {
    setIsActive(true);
    log('Input active', 'success');
  }, [log]);

  const handleBlur = useCallback(() => {
    setIsActive(false);
    log('Input inactive');
  }, [log]);

  const handleKeyDown = useCallback(
    (event: KeyboardEvent) => {
      event.preventDefault();

      const keyboardData = {
        type: 'keyboard',
        event: 'keydown',
        key: event.key,
        code: event.code,
        modifiers: {
          ctrl: event.ctrlKey,
          alt: event.altKey,
          shift: event.shiftKey,
          meta: event.metaKey,
        },
      };

      send(JSON.stringify(keyboardData));
    },
    [send]
  );

  const handleKeyUp = useCallback(
    (event: KeyboardEvent) => {
      event.preventDefault();

      const keyboardData = {
        type: 'keyboard',
        event: 'keyup',
        key: event.key,
        code: event.code,
        modifiers: {
          ctrl: event.ctrlKey,
          alt: event.altKey,
          shift: event.shiftKey,
          meta: event.metaKey,
        },
      };

      send(JSON.stringify(keyboardData));
    },
    [send]
  );

  const handleMouseMove = useCallback(
    (event: MouseEvent) => {
      if (!isActive) return;

      const now = Date.now();
      if (now - lastMouseMoveRef.current < MOUSE_THROTTLE_MS) return;
      lastMouseMoveRef.current = now;

      const target = event.currentTarget as HTMLElement;
      const rect = target.getBoundingClientRect();

      let videoW = 1920;
      let videoH = 1080;

      const canvas = target.querySelector<HTMLCanvasElement>('canvas.display-surface');
      if (canvas && canvas.width) {
        videoW = canvas.width;
        videoH = canvas.height;
      } else {
        const video = target.querySelector<HTMLVideoElement>('video.display-surface');
        if (video && video.videoWidth) {
          videoW = video.videoWidth;
          videoH = video.videoHeight;
        }
      }

      // Calculate object-fit: contain dimensions
      const scale = Math.min(rect.width / videoW, rect.height / videoH);
      const actualW = videoW * scale;
      const actualH = videoH * scale;

      const offsetX = (rect.width - actualW) / 2;
      const offsetY = (rect.height - actualH) / 2;

      let x = Math.floor(((event.clientX - rect.left - offsetX) / actualW) * 32767);
      let y = Math.floor(((event.clientY - rect.top - offsetY) / actualH) * 32767);

      // Clamp values to valid range
      const clampedX = Math.max(0, Math.min(32767, x));
      const clampedY = Math.max(0, Math.min(32767, y));

      if (cursorRef?.current) {
        const leftPercent = ((offsetX + (clampedX / 32767) * actualW) / rect.width) * 100;
        const topPercent = ((offsetY + (clampedY / 32767) * actualH) / rect.height) * 100;
        cursorRef.current.style.left = `${leftPercent}%`;
        cursorRef.current.style.top = `${topPercent}%`;
      }

      send(
        JSON.stringify({
          type: 'mouse',
          event: 'move',
          x: clampedX,
          y: clampedY,
        })
      );
    },
    [isActive, send, cursorRef]
  );

  const handleMouseDown = useCallback(
    (event: MouseEvent) => {
      // Focus first to enable input mode
      const target = event.currentTarget as HTMLElement;
      target.focus();
      event.preventDefault();

      send(
        JSON.stringify({
          type: 'mouse',
          event: 'down',
          button: event.button, // 0=left, 1=middle, 2=right
        })
      );
    },
    [send]
  );

  const handleMouseUp = useCallback(
    (event: MouseEvent) => {
      event.preventDefault();

      send(
        JSON.stringify({
          type: 'mouse',
          event: 'up',
          button: event.button,
        })
      );
    },
    [send]
  );

  const handleWheel = useCallback(
    (event: WheelEvent) => {
      event.preventDefault();
      if (!isActive) return;

      // Normalize wheel delta to a reasonable range (-127 to 127)
      let delta = Math.max(-127, Math.min(127, Math.round(event.deltaY / 10)));

      // Invert scroll direction if needed
      if (invertScroll) {
        delta = -delta;
      }

      send(
        JSON.stringify({
          type: 'mouse',
          event: 'wheel',
          delta,
        })
      );
    },
    [isActive, invertScroll, send]
  );

  const handleContextMenu = useCallback((event: MouseEvent) => {
    event.preventDefault();
  }, []);

  // Attach document-level keyboard capture when active so browser shortcuts
  // (Ctrl+W, Ctrl+T, F-keys, etc.) are intercepted before the browser acts on them.
  useEffect(() => {
    if (!isActive) return;
    document.addEventListener('keydown', handleKeyDown as EventListener, { capture: true });
    document.addEventListener('keyup', handleKeyUp as EventListener, { capture: true });
    return () => {
      document.removeEventListener('keydown', handleKeyDown as EventListener, { capture: true });
      document.removeEventListener('keyup', handleKeyUp as EventListener, { capture: true });
    };
  }, [isActive, handleKeyDown, handleKeyUp]);

  const bindToElement = useCallback(
    (element: HTMLElement | null) => {
      // Unbind from previous element
      if (containerRef.current) {
        const el = containerRef.current;
        el.removeEventListener('focus', handleFocus);
        el.removeEventListener('blur', handleBlur);
        el.removeEventListener('mousemove', handleMouseMove as EventListener);
        el.removeEventListener('mousedown', handleMouseDown as EventListener);
        el.removeEventListener('mouseup', handleMouseUp as EventListener);
        el.removeEventListener('wheel', handleWheel as EventListener);
        el.removeEventListener('contextmenu', handleContextMenu as EventListener);
      }

      containerRef.current = element;

      // Bind to new element
      if (element) {
        element.addEventListener('focus', handleFocus);
        element.addEventListener('blur', handleBlur);
        element.addEventListener('mousemove', handleMouseMove as EventListener);
        element.addEventListener('mousedown', handleMouseDown as EventListener);
        element.addEventListener('mouseup', handleMouseUp as EventListener);
        element.addEventListener('wheel', handleWheel as EventListener, { passive: false });
        element.addEventListener('contextmenu', handleContextMenu as EventListener);
      }
    },
    [
      handleFocus,
      handleBlur,
      handleMouseMove,
      handleMouseDown,
      handleMouseUp,
      handleWheel,
      handleContextMenu,
    ]
  );

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (containerRef.current) {
        bindToElement(null);
      }
    };
  }, [bindToElement]);

  return {
    isActive,
    bindToElement,
  };
}

