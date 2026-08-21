import React, { useState, useCallback, useEffect } from 'react';

interface DebounceContainerProps {
  /** The async action to perform (e.g., your fetch/POST request) */
  action: () => Promise<void> | void;
  /** Delay in milliseconds to wait before execution */
  delay?: number;
  /** A render prop that passes down the states to the UI child elements */
  children: (renderProps: {
    handleAction: () => void;
    isLoading: boolean;
  }) => React.ReactNode;
}

export function DebounceContainer({ 
  action, 
  delay = 500, 
  children 
}: DebounceContainerProps) {
  const [isLoading, setIsLoading] = useState(false);
  const [timeoutId, setTimeoutId] = useState<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => {
    if (timeoutId) clearTimeout(timeoutId);
  }, [timeoutId]);

  const debouncedHandler = useCallback(() => {
    if (timeoutId) clearTimeout(timeoutId);

    const nextTimeoutId = setTimeout(() => {
      if (isLoading) return;

      setIsLoading(true);
      Promise.resolve(action())
        .catch((error: unknown) => {
          console.error("Action execution failed:", error);
        })
        .finally(() => {
          setIsLoading(false);
          setTimeoutId(null);
        });
    }, delay);

    setTimeoutId(nextTimeoutId);
  }, [action, delay, isLoading, timeoutId]);

  return <>{children({ handleAction: debouncedHandler, isLoading })}</>;
}
