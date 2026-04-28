import { useState, useEffect } from 'react';

const PREFIX = 'zeropykvm.';

export function useLocalStorage<T>(key: string, defaultValue: T): [T, (value: T) => void] {
  const [value, setValue] = useState<T>(() => {
    try {
      const item = localStorage.getItem(PREFIX + key);
      return item !== null ? (JSON.parse(item) as T) : defaultValue;
    } catch {
      return defaultValue;
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem(PREFIX + key, JSON.stringify(value));
    } catch {
      // Storage not available – silently ignore
    }
  }, [key, value]);

  return [value, setValue];
}
