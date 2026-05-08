import { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import * as documentService from '../services/documentService';
import {
  ArrowLeft,
  FileText,
  Calendar,
  Tag,
  Loader2,
  AlertCircle,
  Download,
  Eye,
} from 'lucide-react';

export default function DocumentViewerPage() {
  const { id } = useParams();
  const [doc, setDoc] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);
  const [fileUrl, setFileUrl] = useState(null);
  const [showViewer, setShowViewer] = useState(false);

  useEffect(() => {
    const fetchDoc = async () => {
      setIsLoading(true);
      setError(null);
      try {
        const data = await documentService.getDocument(id);
        setDoc(data);

        // Auto-load PDF for viewing
        if (data.file_extension === '.pdf') {
          try {
            const blob = await documentService.getDocumentFileBlob(id);
            const url = URL.createObjectURL(blob);
            setFileUrl(url);
            setShowViewer(true);
          } catch {
            // File viewing not critical
          }
        }
      } catch (err) {
        setError(err.response?.data?.detail || 'Failed to load document');
      } finally {
        setIsLoading(false);
      }
    };
    fetchDoc();

    return () => {
      // Cleanup blob URL on unmount
      if (fileUrl) URL.revokeObjectURL(fileUrl);
    };
  }, [id]);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 size={32} className="text-violet-500 animate-spin" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-center">
        <AlertCircle size={40} className="text-terra-500 mb-3" />
        <p className="text-sm text-terra-500 mb-4">{error}</p>
        <Link to="/search" className="btn-secondary text-sm">
          <ArrowLeft size={16} /> Back to Search
        </Link>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* Header */}
      <div className="bg-white border-b border-cream-200 px-6 py-4">
        <div className="flex items-center gap-3 mb-3">
          <Link to="/search" className="btn-ghost !p-1.5">
            <ArrowLeft size={18} />
          </Link>
          <div className="flex-1 min-w-0">
            <h1 className="font-serif text-lg font-bold text-ink-900 truncate">
              {doc.original_filename || doc.title || doc.filename}
            </h1>
          </div>
          <div className="flex items-center gap-2">
            {doc.file_extension === '.pdf' && (
              <button
                onClick={() => setShowViewer((v) => !v)}
                className="btn-secondary text-xs flex items-center gap-1"
              >
                <Eye size={14} />
                {showViewer ? 'Hide PDF' : 'View PDF'}
              </button>
            )}
            <button
              onClick={async () => {
                try {
                  const blob = await documentService.getDocumentFileBlob(id);
                  const url = URL.createObjectURL(blob);
                  const a = document.createElement('a');
                  a.href = url;
                  a.download = doc.original_filename || 'document';
                  a.click();
                  URL.revokeObjectURL(url);
                } catch {
                  alert('Failed to download file');
                }
              }}
              className="btn-primary text-xs flex items-center gap-1"
            >
              <Download size={14} />
              Download
            </button>
          </div>
        </div>

        {/* Meta info */}
        <div className="flex flex-wrap items-center gap-4 text-xs text-sand-500">
          {doc.document_type && (
            <span className="flex items-center gap-1">
              <FileText size={12} />
              {doc.document_type.toUpperCase()}
            </span>
          )}
          {doc.collection && (
            <span className="flex items-center gap-1">
              <Tag size={12} />
              <span className="capitalize">{doc.collection}</span>
            </span>
          )}
          {doc.created_at && (
            <span className="flex items-center gap-1">
              <Calendar size={12} />
              {new Date(doc.created_at).toLocaleDateString()}
            </span>
          )}
          {doc.page_count && (
            <span>{doc.page_count} pages</span>
          )}
        </div>
      </div>

      {/* Document content area */}
      <div className="flex-1 overflow-y-auto p-6">
        <div className="max-w-4xl mx-auto">
          {/* PDF Viewer */}
          {showViewer && fileUrl && (
            <div className="mb-6 rounded-lg overflow-hidden border border-cream-200" style={{ height: '70vh' }}>
              <iframe
                src={fileUrl}
                title="Document Viewer"
                className="w-full h-full"
                style={{ border: 'none' }}
              />
            </div>
          )}

          {showViewer && !fileUrl && doc.file_extension === '.pdf' && (
            <div className="card p-5 mb-6 text-center text-sm text-sand-500">
              <Loader2 size={20} className="animate-spin inline mr-2" />
              Loading PDF...
            </div>
          )}

          {showViewer && doc.file_extension !== '.pdf' && (
            <div className="card p-5 mb-6 text-center text-sm text-sand-500">
              Preview not available for {doc.file_extension} files. Use the Download button.
            </div>
          )}

          {/* Summary */}
          {doc.summary && (
            <div className="card p-5 mb-6">
              <h3 className="text-sm font-semibold text-ink-900 mb-2">Summary</h3>
              <p className="text-sm text-ink-700 leading-relaxed">{doc.summary}</p>
            </div>
          )}

          {/* Keywords */}
          {doc.keywords && doc.keywords.length > 0 && (
            <div className="mb-6">
              <h3 className="text-sm font-semibold text-ink-900 mb-2">Keywords</h3>
              <div className="flex flex-wrap gap-2">
                {doc.keywords.map((kw, idx) => (
                  <span key={idx} className="badge-info">
                    {kw}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Entities */}
          {doc.entities && doc.entities.length > 0 && (
            <div className="mb-6">
              <h3 className="text-sm font-semibold text-ink-900 mb-2">Entities</h3>
              <div className="flex flex-wrap gap-2">
                {doc.entities.map((entity, idx) => (
                  <span
                    key={idx}
                    className="badge bg-forest-500/10 text-forest-500"
                  >
                    {entity.name || entity}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Document details card */}
          <div className="card p-5">
            <h3 className="text-sm font-semibold text-ink-900 mb-3">Details</h3>
            <dl className="space-y-2">
              {[
                ['Filename', doc.filename],
                ['Type', doc.document_type?.toUpperCase()],
                ['Collection', doc.collection],
                ['File Size', doc.file_size ? `${(doc.file_size / 1024).toFixed(1)} KB` : null],
                ['Uploaded By', doc.uploaded_by],
                ['Created', doc.created_at ? new Date(doc.created_at).toLocaleString() : null],
                ['Updated', doc.updated_at ? new Date(doc.updated_at).toLocaleString() : null],
              ]
                .filter(([, v]) => v)
                .map(([label, value]) => (
                  <div key={label} className="flex items-start">
                    <dt className="w-28 text-xs text-sand-500 flex-shrink-0">{label}</dt>
                    <dd className="text-sm text-ink-700">{value}</dd>
                  </div>
                ))}
            </dl>
          </div>
        </div>
      </div>
    </div>
  );
}
