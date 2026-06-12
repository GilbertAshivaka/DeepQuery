import { useEffect } from 'react';
import { motion } from 'framer-motion';
import { X } from 'lucide-react';

/**
 * Shared modal shell — calm, elevated, dimmed canvas (UI guide §16). Reused by the
 * connector register/enable flows and the action-approval gate.
 */
export default function Modal({ title, onClose, children, footer, maxWidth = 'max-w-lg' }) {
  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && onClose?.();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      onClick={onClose}
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink-900/50 backdrop-blur-sm p-4"
    >
      <motion.div
        initial={{ opacity: 0, y: 12, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 8 }}
        transition={{ duration: 0.18, ease: 'easeOut' }}
        onClick={(e) => e.stopPropagation()}
        className={`w-full ${maxWidth} bg-white rounded-2xl border border-cream-200 shadow-warm-xl max-h-[88vh] flex flex-col`}
      >
        <div className="flex items-center justify-between px-5 h-14 border-b border-cream-200 flex-shrink-0">
          <h3 className="font-semibold text-ink-900 text-sm">{title}</h3>
          <button onClick={onClose} className="btn-ghost !p-1" title="Close">
            <X size={18} />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-5">{children}</div>
        {footer && (
          <div className="flex items-center justify-end gap-2 px-5 py-3.5 border-t border-cream-200 flex-shrink-0">
            {footer}
          </div>
        )}
      </motion.div>
    </motion.div>
  );
}
