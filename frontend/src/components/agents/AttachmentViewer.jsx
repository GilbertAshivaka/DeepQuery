import { useEffect, useState } from 'react';
import { X, FileText, Loader2, AlertCircle, Download } from 'lucide-react';
import * as agentService from '../../services/agentService';

// Native PDF plugin present? (false in Qt WebEngine / some desktop shells.)
const browserSupportsPDF = navigator.pdfViewerEnabled ?? false;

/**
 * Claude-style right-hand side panel for a *document* attachment — keeps the
 * conversation in view. Shows the original PDF inline where the browser supports
 * it, otherwise the parsed text (always available for documents).
 */
export default function AttachmentViewer({ attachment, onClose }) {
  const [meta, setMeta] = useState(null);
  const [pdfUrl, setPdfUrl] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let objectUrl;
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      setPdfUrl(null);
      try {
        const data = await agentService.getAttachment(attachment.id);
        if (cancelled) return;
        setMeta(data);
        if (data.file_extension === '.pdf' && browserSupportsPDF) {
          const blob = await agentService.getAttachmentBlob(attachment.id);
          if (cancelled) return;
          objectUrl = URL.createObjectURL(blob);
          setPdfUrl(objectUrl);
        }
      } catch {
        if (!cancelled) setError('Could not load this attachment.');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [attachment.id]);

  const download = async () => {
    try {
      const blob = await agentService.getAttachmentBlob(attachment.id);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = attachment.filename || 'attachment';
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      /* ignore */
    }
  };

  return (
    <div className="w-96 flex-shrink-0 border-l border-cream-200 bg-white flex flex-col h-full animate-slide-right">
      {/* Header */}
      <div className="flex items-center justify-between px-5 h-14 border-b border-cream-200 flex-shrink-0">
        <div className="flex items-center gap-2 min-w-0">
          <FileText size={16} className="text-violet-500 flex-shrink-0" />
          <h3 className="font-semibold text-ink-900 text-sm truncate">{attachment.filename}</h3>
        </div>
        <div className="flex items-center gap-1 flex-shrink-0">
          <button onClick={download} className="btn-ghost !p-1" title="Download">
            <Download size={16} />
          </button>
          <button onClick={onClose} className="btn-ghost !p-1" title="Close">
            <X size={18} />
          </button>
        </div>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto">
        {loading ? (
          <div className="flex items-center justify-center h-full">
            <Loader2 size={22} className="text-violet-500 animate-spin" />
          </div>
        ) : error ? (
          <div className="flex flex-col items-center justify-center h-full text-center px-5">
            <AlertCircle size={28} className="text-terra-500 mb-2" />
            <p className="text-sm text-terra-500">{error}</p>
          </div>
        ) : pdfUrl ? (
          <iframe src={pdfUrl} title={attachment.filename} className="w-full h-full" style={{ border: 'none' }} />
        ) : meta?.extracted_text ? (
          <div className="p-5">
            <p className="text-xs text-sand-500 mb-2">Parsed text</p>
            <pre className="text-sm text-ink-700 leading-relaxed whitespace-pre-wrap font-sans">
              {meta.extracted_text}
            </pre>
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center h-full text-center px-5 text-sm text-sand-500">
            <FileText size={28} className="mb-2 text-cream-400" />
            No preview available. Use download to open the file.
          </div>
        )}
      </div>
    </div>
  );
}
