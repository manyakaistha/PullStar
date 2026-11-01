import React from 'react';

export type ButtonVariant = 'primary' | 'secondary' | 'pill' | 'quiet';

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  active?: boolean;
  icon?: React.ReactNode;
}

export const Button: React.FC<ButtonProps> = ({
  children,
  variant = 'secondary',
  active = false,
  icon,
  className = '',
  ...props
}) => {
  let baseClass = '';

  switch (variant) {
    case 'primary':
      baseClass = 'tactile-button';
      break;
    case 'pill':
      baseClass = 'glass-pill';
      break;
    case 'quiet':
      baseClass = 'inline-flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-slate-400 hover:text-slate-100 hover:bg-white/5 transition-colors focus-visible:outline-2 focus-visible:outline-[var(--accent)] focus-visible:outline-offset-2';
      break;
    case 'secondary':
    default:
      baseClass = 'tactile-button-secondary';
      break;
  }

  return (
    <button
      className={`${baseClass} ${active ? 'active' : ''} ${className}`}
      aria-pressed={active ? 'true' : undefined}
      {...props}
    >
      {icon && <span className="tactile-icon" aria-hidden="true">{icon}</span>}
      {children}
    </button>
  );
};
