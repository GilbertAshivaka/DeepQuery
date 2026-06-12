import { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import { X, Loader2 } from 'lucide-react';
import * as agentService from '../../services/agentService';

/**
 * Inline image preview — a centered lightbox on a dimmed canvas. The image is
 * fetched as an authed blob (the /content endpoint needs the bearer header) and
 * shown via an object URL.
 */
export default function ImageLightbox({ attachment, onClose }) {
  const [url, setUrl] = useState(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let objectUrl;
    let cancelled = false;
    (async () => {
      try {
        const blob = await agentService.getAttachmentBlob(attachment.id);
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setUrl(objectUrl);
      } catch {
        if (!cancelled) setError(true);
      }
    })();
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [attachment.id]);

  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      onClick={onClose}
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink-900/60 backdrop-blur-sm p-8"
    >
      <button
        onClick={onClose}
        className="absolute top-4 right-4 p-2 rounded-xl text-white/80 hover:text-white hover:bg-white/10 transition-all"
        title="Close"
      >
        <X size={22} />
      </button>

      <div className="max-w-[90vw] max-h-[88vh] flex flex-col items-center" onClick={(e) => e.stopPropagation()}>
        {error ? (
          <p className="text-sm text-white/80">Could not load this image.</p>
        ) : url ? (
          <img
            src={url}
            alt={attachment.filename}
            className="max-w-full max-h-[82vh] rounded-xl shadow-warm-xl object-contain"
          />
        ) : (
          <Loader2 size={26} className="text-white/80 animate-spin" />
        )}
        {attachment.filename && (
          <p className="mt-3 text-xs text-white/70 truncate max-w-full">{attachment.filename}</p>
        )}
      </div>
    </motion.div>
  );
}
