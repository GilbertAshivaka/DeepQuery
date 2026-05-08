import * as React from 'react';
import { Slot } from '@radix-ui/react-slot';
import { cva } from 'class-variance-authority';
import { cn } from '@/lib/utils';

const buttonVariants = cva(
  'inline-flex items-center justify-center whitespace-nowrap rounded-xl text-sm font-medium transition-all duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/30 focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 active:scale-[0.98]',
  {
    variants: {
      variant: {
        default: 'bg-violet-500 text-white hover:bg-violet-600 shadow-warm',
        destructive: 'bg-terra-500 text-white hover:bg-terra-500/90',
        outline: 'border border-cream-300 bg-white hover:bg-cream-100 hover:text-ink-900',
        secondary: 'bg-cream-100 text-ink-700 border border-cream-200 hover:bg-cream-200',
        ghost: 'hover:bg-cream-100 text-ink-700',
        link: 'text-violet-500 underline-offset-4 hover:underline',
        warm: 'bg-gradient-to-r from-amber-600 to-amber-700 text-white hover:from-amber-700 hover:to-amber-800 shadow-warm',
      },
      size: {
        default: 'h-10 px-5 py-2.5 gap-2',
        sm: 'h-9 rounded-lg px-3 gap-1.5',
        lg: 'h-12 rounded-xl px-8 gap-2.5 text-base',
        icon: 'h-10 w-10',
      },
    },
    defaultVariants: {
      variant: 'default',
      size: 'default',
    },
  }
);

const Button = React.forwardRef(({ className, variant, size, asChild = false, ...props }, ref) => {
  const Comp = asChild ? Slot : 'button';
  return (
    <Comp
      className={cn(buttonVariants({ variant, size, className }))}
      ref={ref}
      {...props}
    />
  );
});
Button.displayName = 'Button';

export { Button, buttonVariants };
