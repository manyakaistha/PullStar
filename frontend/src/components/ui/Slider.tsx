import React from 'react';

export interface SliderProps extends Omit<React.InputHTMLAttributes<HTMLInputElement>, 'onChange'> {
  label: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  unit?: string;
  onChangeVal: (val: number) => void;
  helperText?: string;
}

export const Slider: React.FC<SliderProps> = ({
  label,
  value,
  min,
  max,
  step = 1,
  unit = '',
  onChangeVal,
  helperText,
  id,
  className = '',
  ...props
}) => {
  const inputId = id || `slider-${label.toLowerCase().replace(/[^a-z0-9]/g, '-')}`;
  const range = max - min;
  const clampedPercent = range <= 0 ? 0 : Math.min(100, Math.max(0, ((value - min) / range) * 100));

  const displayValue = step < 1 ? Number(value.toFixed(3)).toString() : value.toString();

  return (
    <div className={`flex flex-col gap-1.5 w-full ${className}`}>
      <div className="flex justify-between items-center text-[13px]">
        <label htmlFor={inputId} className="text-slate-300 font-medium tracking-tight">
          {label}
        </label>
        <span
          className="field-well px-2 py-0.5 text-xs text-slate-100 font-mono tabular-nums"
          aria-live="polite"
        >
          {displayValue}{unit}
        </span>
      </div>

      <div className="relative flex items-center h-11">
        <input
          id={inputId}
          type="range"
          className="physical-range"
          min={min}
          max={max}
          step={step}
          value={value}
          style={{ '--fill': `${clampedPercent}%` } as React.CSSProperties}
          aria-valuetext={`${displayValue} ${unit}`.trim()}
          onChange={(e) => onChangeVal(parseFloat(e.target.value))}
          {...props}
        />
      </div>

      {helperText && (
        <span className="text-[11px] text-slate-400 font-normal -mt-1">
          {helperText}
        </span>
      )}
    </div>
  );
};
