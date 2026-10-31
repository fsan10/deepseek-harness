"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export function useToast() {
  const [toast, setToast] = useState("");
  const timer = useRef<number | null>(null);

  const notify = useCallback((message: string) => {
    setToast(message);
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setToast(""), 2600);
  }, []);

  useEffect(() => () => {
    if (timer.current) window.clearTimeout(timer.current);
  }, []);

  return { toast, notify };
}

export function Toast({ message }: { message: string }) {
  if (!message) return null;
  return (
    <div className="toast" role="status">
      {message}
    </div>
  );
}
