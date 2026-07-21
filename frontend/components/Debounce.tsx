import React, { useState, useMemo, useEffect, useRef } from 'react';

export function debounce<T extends (...args: any[]) => void>(
    func: T, 
    delay: number
  ): (...args: Parameters<T>) => void {
    let timeoutId: ReturnType<typeof setTimeout>;
    
    return (...args: Parameters<T>) => {
      clearTimeout(timeoutId);
      timeoutId = setTimeout(() => {
        func(...args);
      }, delay);
    };
  }

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
  
  // Keep the latest action in a ref to prevent unnecessary debounce recreations
  const actionRef = useRef(action);
  useEffect(() => {
    actionRef.current = action;
  }, [action]);

  // Wrapper that handles the loading state during async execution
  const executeAction = async () => {
    if (isLoading) return;
    setIsLoading(true);
    try {
      await actionRef.current();
    } catch (error) {
      console.error("Action execution failed:", error);
    } finally {
      setIsLoading(false);
    }
  };

  // Memoize the debounced version so it persists between renders
  const debouncedHandler = useMemo(
    () => debounce(executeAction, delay),
    [delay, isLoading]
  );

  return <>{children({ handleAction: debouncedHandler, isLoading })}</>;
}