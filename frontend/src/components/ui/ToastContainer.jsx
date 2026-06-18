import { motion, AnimatePresence } from 'framer-motion';
import { AlertCircle, Info, CheckCircle2, X } from 'lucide-react';
import { useToastStore } from '../../store/toastStore';

const STYLES = {
  error: { Icon: AlertCircle, ring: 'border-terra-500/30', icon: 'text-terra-500', bar: 'bg-terra-500' },
  info: { Icon: Info, ring: 'border-violet-500/30', icon: 'text-violet-500', bar: 'bg-violet-500' },
  success: { Icon: CheckCircle2, ring: 'border-forest-500/30', icon: 'text-forest-500', bar: 'bg-forest-500' },
};

// Top-right stack of slide-in, dismissible toasts. Mounted once at the app shell.
export default function ToastContainer() {
  const toasts = useToastStore((s) => s.toasts);
  const dismiss = useToastStore((s) => s.dismiss);

  return (
    <div className="fixed top-4 right-4 z-[100] flex flex-col gap-2 w-[min(360px,calc(100vw-2rem))] pointer-events-none">
      <AnimatePresence initial={false}>
        {toasts.map((t) => {
          const cfg = STYLES[t.type] || STYLES.error;
          const { Icon } = cfg;
          return (
            <motion.div
              key={t.id}
              layout
              initial={{ opacity: 0, x: 40, scale: 0.96 }}
              animate={{ opacity: 1, x: 0, scale: 1 }}
              exit={{ opacity: 0, x: 40, scale: 0.96 }}
              transition={{ duration: 0.22, ease: 'easeOut' }}
              className={`pointer-events-auto relative overflow-hidden flex items-start gap-2.5 pl-3.5 pr-2.5 py-3
                          bg-white rounded-xl border ${cfg.ring} shadow-warm-lg`}
            >
              <span className={`absolute left-0 top-0 bottom-0 w-1 ${cfg.bar}`} />
              <Icon size={16} className={`flex-shrink-0 mt-0.5 ${cfg.icon}`} />
              <div className="flex-1 min-w-0">
                {t.title && <p className="text-xs font-semibold text-ink-900">{t.title}</p>}
                <p className="text-xs text-ink-700 leading-snug break-words">{t.message}</p>
              </div>
              <button
                onClick={() => dismiss(t.id)}
                className="flex-shrink-0 p-1 rounded-md text-ink-500 hover:text-ink-900 hover:bg-cream-100 transition-colors"
                title="Dismiss"
              >
                <X size={13} />
              </button>
            </motion.div>
          );
        })}
      </AnimatePresence>
    </div>
  );
}
