import { cn } from '../../lib/utils';

/**
 * Switch — accessible on/off toggle in the warm design language.
 * Track turns violet-500 when on, cream when off; white thumb slides across.
 *
 * Props:
 *  - checked      boolean
 *  - onChange     (next: boolean) => void
 *  - disabled     boolean
 *  - size         'sm' | 'md'  (default 'md')
 *  - label        optional accessible label (aria-label)
 *  - id           optional id (for an external <label htmlFor>)
 */
export default function Switch({
  checked = false,
  onChange,
  disabled = false,
  size = 'md',
  label,
  id,
  className,
}) {
  const dims =
    size === 'sm'
      ? { track: 'h-5 w-9', thumb: 'h-4 w-4', on: 'translate-x-4', off: 'translate-x-0.5' }
      : { track: 'h-6 w-11', thumb: 'h-5 w-5', on: 'translate-x-5', off: 'translate-x-0.5' };

  return (
    <button
      type="button"
      role="switch"
      id={id}
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => !disabled && onChange?.(!checked)}
      className={cn(
        'relative inline-flex flex-shrink-0 items-center rounded-full',
        'transition-colors duration-200 ease-in-out',
        'focus:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/40 focus-visible:ring-offset-1',
        dims.track,
        checked ? 'bg-violet-500' : 'bg-cream-300',
        disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer',
        className
      )}
    >
      <span
        className={cn(
          'inline-block rounded-full bg-white shadow-warm-sm',
          'transform transition-transform duration-200 ease-in-out',
          dims.thumb,
          checked ? dims.on : dims.off
        )}
      />
    </button>
  );
}
