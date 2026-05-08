import { useEffect, useState } from 'react';
import { useAdminStore } from '../../store/adminStore';
import { Link } from 'react-router-dom';
import {
  FileText,
  Trash2,
  Search,
  Loader2,
  ExternalLink,
} from 'lucide-react';

export default function DocumentsTab() {
  const { documents, isLoading, loadDocuments, deleteDocument } = useAdminStore();
  const [search, setSearch] = useState('');
  const [deleteConfirm, setDeleteConfirm] = useState(null);

  useEffect(() => {
    loadDocuments();
  }, [loadDocuments]);

  const filtered = documents.filter((doc) => {
    if (!search.trim()) return true;
    const q = search.toLowerCase();
    return (
      doc.title?.toLowerCase().includes(q) ||
      doc.collection?.toLowerCase().includes(q) ||
      doc.document_type?.toLowerCase().includes(q)
    );
  });

  const handleDelete = async (docId) => {
    try {
      await deleteDocument(docId);
      setDeleteConfirm(null);
    } catch {
      // Error handled in store
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 size={24} className="text-violet-500 animate-spin" />
      </div>
    );
  }

  return (
    <div className="p-6">
      {/* Search */}
      <div className="relative max-w-md mb-6">
        <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-sand-400" />
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Filter documents…"
          className="input pl-9 !py-2 text-sm"
        />
      </div>

      {filtered.length === 0 ? (
        <div className="text-center py-16">
          <FileText size={40} className="mx-auto text-cream-300 mb-3" />
          <p className="text-sm text-sand-500">
            {documents.length === 0 ? 'No documents uploaded yet' : 'No matching documents'}
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          {filtered.map((doc) => (
            <div
              key={doc.id}
              className="flex items-center gap-4 p-4 rounded-xl bg-white border border-cream-200 hover:shadow-warm transition-all"
            >
              <FileText size={18} className="text-sand-400 flex-shrink-0" />

              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-ink-900 truncate">
                  {doc.original_filename || doc.title || 'Untitled Document'}
                </p>
                <div className="flex items-center gap-3 mt-0.5">
                  {doc.collection && (
                    <span className="badge-info text-[10px]">{doc.collection}</span>
                  )}
                  <span className="text-[10px] text-sand-400 uppercase">
                    {(doc.document_type || doc.category || 'other').replace(/_/g, ' ')}
                  </span>
                  {doc.created_at && (
                    <span className="text-[10px] text-sand-400">
                      {new Date(doc.created_at).toLocaleDateString()}
                    </span>
                  )}
                </div>
              </div>

              <div className="flex items-center gap-1">
                <Link
                  to={`/documents/${doc.id}`}
                  className="btn-ghost !p-2 text-sand-400 hover:text-violet-500"
                  title="View"
                >
                  <ExternalLink size={16} />
                </Link>
                {deleteConfirm === doc.id ? (
                  <div className="flex items-center gap-1">
                    <button
                      onClick={() => handleDelete(doc.id)}
                      className="px-2 py-1 text-xs font-medium text-white bg-terra-500 rounded-lg hover:bg-terra-500/90"
                    >
                      Confirm
                    </button>
                    <button
                      onClick={() => setDeleteConfirm(null)}
                      className="px-2 py-1 text-xs font-medium text-ink-700 bg-cream-100 rounded-lg"
                    >
                      Cancel
                    </button>
                  </div>
                ) : (
                  <button
                    onClick={() => setDeleteConfirm(doc.id)}
                    className="btn-ghost !p-2 text-sand-400 hover:text-terra-500"
                    title="Delete"
                  >
                    <Trash2 size={16} />
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
