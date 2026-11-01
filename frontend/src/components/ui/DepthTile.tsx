import { useEffect, useRef, type ReactNode } from 'react';

export interface DepthTileProps {
  children: ReactNode;
  className?: string;
  emblem?: ReactNode;
}

export function DepthTile({ children, className = '', emblem }: DepthTileProps) {
  const host = useRef<HTMLDivElement>(null);
  const frame = useRef<number | null>(null);
  const enabled = useRef(false);
  const sample = useRef({ x: 0.5, y: 0.5 });

  useEffect(() => {
    const query = matchMedia(
      '(hover: hover) and (pointer: fine) and (prefers-reduced-motion: no-preference)'
    );
    const sync = () => {
      enabled.current = query.matches;
      if (!query.matches) reset();
    };
    sync();
    query.addEventListener('change', sync);
    return () => {
      query.removeEventListener('change', sync);
      if (frame.current !== null) cancelAnimationFrame(frame.current);
    };
  }, []);

  function paint() {
    frame.current = null;
    const node = host.current;
    if (!node) return;
    const { x, y } = sample.current;
    node.style.setProperty('--rx', `${(0.5 - y) * 6}deg`);
    node.style.setProperty('--ry', `${(x - 0.5) * 6}deg`);
    node.style.setProperty('--light-x', `${x * 100}%`);
    node.style.setProperty('--light-y', `${y * 100}%`);
  }

  function reset() {
    if (frame.current !== null) cancelAnimationFrame(frame.current);
    frame.current = null;
    sample.current = { x: 0.5, y: 0.5 };
    if (host.current) host.current.dataset.tracking = 'false';
    paint();
  }

  return (
    <div
      ref={host}
      className={`depth-hitbox ${className}`}
      onPointerMove={(event) => {
        if (!enabled.current || event.pointerType !== 'mouse') return;
        const box = event.currentTarget.getBoundingClientRect();
        const clamp = (v: number) => Math.min(1, Math.max(0, v));
        sample.current = {
          x: clamp((event.clientX - box.left) / Math.max(1, box.width)),
          y: clamp((event.clientY - box.top) / Math.max(1, box.height)),
        };
        event.currentTarget.dataset.tracking = 'true';
        if (frame.current === null) frame.current = requestAnimationFrame(paint);
      }}
      onPointerLeave={reset}
      onPointerCancel={reset}
    >
      <div className="depth-plane">
        <div className="glass-surface depth-skin">
          {children}
        </div>
        {emblem && (
          <span className="depth-emblem" aria-hidden="true">
            {emblem}
          </span>
        )}
      </div>
    </div>
  );
}
