import React from 'react';

export const Panel: React.FC<React.HTMLAttributes<HTMLDivElement>> = ({ children, className = '', ...props }) => (
  <div className={`bay-surface p-4 ${className}`} {...props}>
    {children}
  </div>
);

export const Well: React.FC<React.HTMLAttributes<HTMLDivElement>> = ({ children, className = '', ...props }) => (
  <div className={`field-well p-3 ${className}`} {...props}>
    {children}
  </div>
);
