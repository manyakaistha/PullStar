import React from 'react';
import { LED } from './LED';

export interface ToggleProps {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  ledColor?: 'cyan' | 'amber' | 'emerald';
  disabled?: boolean;
  description?: string;
  id?: string;
}

export const Toggle: React.FC<ToggleProps> = ({
  label,
  checked,
  onChange,
  ledColor,
  disabled = false,
  description,
  id,
}) => {
  const switchId = id || `switch-${label.toLowerCase().replace(/[^a-z0-9]/g, '-')}`;

  return (
    <div
      className={`flex items-center justify-between gap-3 min-h-[44px] select-none ${
        disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'
      }`}
      onClick={(event) => {
        if (!disabled && !event.currentTarget.closest("fieldset:disabled")) onChange(!checked);
      }}
    >
      <div className="flex flex-col gap-0.5 min-w-0 pr-2">
        <label
          htmlFor={switchId}
          onClick={(event) => event.stopPropagation()}
          className="flex items-center gap-2 text-[13px] text-slate-200 font-medium cursor-pointer"
        >
          {ledColor && <LED color={checked ? ledColor : 'off'} />}
          <span>{label}</span>
        </label>
        {description && (
          <span className="text-[11px] text-slate-400 font-normal leading-tight">
            {description}
          </span>
        )}
      </div>

      <button
        id={switchId}
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        disabled={disabled}
        className="physical-switch flex-shrink-0"
        onClick={(e) => {
          e.stopPropagation();
          if (!disabled) onChange(!checked);
        }}
      >
        <span className="switch-track" aria-hidden="true">
          <span className="switch-cap" />
        </span>
      </button>
    </div>
  );
};
