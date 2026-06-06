import { useEffect, useState, useCallback } from 'react';
import { useParams, Link } from 'react-router-dom';
import * as documentService from '../services/documentService';
import { Document, Page, pdfjs } from 'react-pdf';
import 'react-pdf/dist/Page/AnnotationLayer.css';
import 'react-pdf/dist/Page/TextLayer.css';
import {
  ArrowLeft,
  FileText,
  Calendar,
  Tag,
  Loader2,
  AlertCircle,
  Download,
  Eye,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react';

// Configure PDF.js worker — required by react-pdf
pdfjs.GlobalWorkerOptions.workerSrc = '/pdf.worker.mjs';

// Detect whether the browser has a native PDF viewer (true in Chrome/Firefox/Edge, false in Qt WebEngineView)
const browserSupportsPDF = navigator.pdfViewerEnabled ?? false;

const pdfOptions = {
  disableFontFace: true,
  disableRange: true,
  disableStream: true,
  disableAutoFetch: true,
};

export default function DocumentViewerPage() {
  const { id } = useParams();
  const [doc, setDoc] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);
  const [fileUrl, setFileUrl] = useState(null);
  const [showViewer, setShowViewer] = useState(false);

  // React-PDF state (only used when browser doesn't support PDF natively)
  const [numPages, setNumPages] = useState(null);
  const [currentPage, setCurrentPage] = useState(1);

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

    // Cleanup blob URL on unmount
    return () => {
      if (fileUrl) URL.revokeObjectURL(fileUrl);
    };
  }, [id]);

  const onDocumentLoadSuccess = useCallback(({ numPages }) => {
    setNumPages(numPages);
    setCurrentPage(1);
  }, []);

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
          {showViewer && doc.file_extension === '.pdf' && fileUrl && (
            browserSupportsPDF ? (
              /* Browser-native rendering: full-featured plugin (Chrome, Firefox, Edge) */
              <div
                className="mb-6 rounded-lg overflow-hidden border border-cream-200"
                style={{ height: '70vh' }}
              >
                <iframe
                  src={fileUrl}
                  title="Document Viewer"
                  className="w-full h-full"
                  style={{ border: 'none' }}
                />
              </div>
            ) : (
              /* React-PDF rendering: JS canvas fallback for Qt WebEngineView and unsupported browsers */
              <div className="mb-6 rounded-lg border border-cream-200 overflow-hidden">
                {/* Page navigation toolbar */}
                <div className="flex items-center justify-between bg-white px-4 py-2 border-b border-cream-200">
                  <button
                    onClick={() => setCurrentPage((p) => Math.max(p - 1, 1))}
                    disabled={currentPage <= 1}
                    className="btn-ghost !p-1.5 disabled:opacity-40"
                  >
                    <ChevronLeft size={16} />
                  </button>
                  <span className="text-xs text-sand-500">
                    Page {currentPage} of {numPages ?? '—'}
                  </span>
                  <button
                    onClick={() => setCurrentPage((p) => Math.min(p + 1, numPages ?? p))}
                    disabled={currentPage >= (numPages ?? 1)}
                    className="btn-ghost !p-1.5 disabled:opacity-40"
                  >
                    <ChevronRight size={16} />
                  </button>
                </div>

                {/* PDF canvas */}
                <div className="overflow-y-auto bg-sand-50 flex justify-center p-4" style={{ maxHeight: '65vh' }}>
                  <Document
                    file={fileUrl}
                    onLoadSuccess={onDocumentLoadSuccess}
                    options={pdfOptions}
                    loading={
                      <div className="flex items-center justify-center py-12">
                        <Loader2 size={24} className="text-violet-500 animate-spin" />
                      </div>
                    }
                    error={
                      <div className="flex items-center justify-center py-12 text-sm text-terra-500">
                        <AlertCircle size={16} className="mr-2" />
                        Failed to load PDF
                      </div>
                    }
                  >
                    <Page
                      // key={currentPage}
                      pageNumber={currentPage}
                      width={700}
                      renderTextLayer={true}
                      renderAnnotationLayer={true}
                      renderMode="canvas"
                    />
                  </Document>
                </div>
              </div>
            )
          )}

          {/* Loading state while blob URL is being fetched */}
          {showViewer && !fileUrl && doc.file_extension === '.pdf' && (
            <div className="card p-5 mb-6 text-center text-sm text-sand-500">
              <Loader2 size={20} className="animate-spin inline mr-2" />
              Loading PDF...
            </div>
          )}

          {/* Non-PDF file preview not available */}
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
            <EntitiesSection entities={doc.entities} />
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
function EntitiesSection({ entities }) {
  const [showAll, setShowAll] = useState(false);
  const visible = showAll ? entities : entities.slice(0, 10);

  return (
    <div className="mb-6">
      <h3 className="text-sm font-semibold text-ink-900 mb-2">
        Entities
        <span className="ml-2 text-xs font-normal text-sand-500">
          ({entities.length} found)
        </span>
      </h3>
      <div className="flex flex-wrap gap-2">
        {visible.map((entity, idx) => (
          <span
            key={idx}
            className="badge bg-forest-500/10 text-forest-500"
          >
            {entity.name || entity}
          </span>
        ))}
      </div>
      {entities.length > 10 && (
        <button
          onClick={() => setShowAll((v) => !v)}
          className="mt-2 text-xs text-violet-500 hover:underline"
        >
          {showAll
            ? 'Show less'
            : `Show ${entities.length - 10} more entities`}
        </button>
      )}
    </div>
  );
}