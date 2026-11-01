import React from 'react';

export type LEDColor = 'cyan' | 'amber' | 'emerald' | 'off';

export interface LEDProps {
  color?: LEDColor;
  className?: string;
  label?: string;
}

export const LED: React.FC<LEDProps> = ({ color = 'off', className = '', label }) => {
  return (
    <span className="inline-flex items-center gap-1.5 align-middle">
      <span className={`led ${color} ${className}`} aria-hidden="true" />
      {label && <span className="text-xs text-slate-300 font-medium">{label}</span>}
    </span>
  );
};
