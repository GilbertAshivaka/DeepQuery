import { useState } from 'react';
import { useSearchStore } from '../store/searchStore';
import { Link } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Search as SearchIcon,
  Filter,
  FileText,
  X,
  Loader2,
  ChevronDown,
  Sparkles,
} from 'lucide-react';

const COLLECTIONS = [
  { value: '', label: 'All Collections' },
  { value: 'academic', label: 'Academic' },
  { value: 'departmental', label: 'Departmental' },
  { value: 'administrative', label: 'Administrative' },
  { value: 'management', label: 'Management' },
];

const DOCUMENT_TYPES = [
  { value: '', label: 'All Types' },
  { value: 'pdf', label: 'PDF' },
  { value: 'docx', label: 'DOCX' },
  { value: 'html', label: 'HTML' },
];

export default function SearchPage() {
  const {
    query,
    results,
    isSearching,
    error,
    filters,
    setQuery,
    setFilter,
    clearFilters,
    search,
    clearResults,
  } = useSearchStore();

  const [showFilters, setShowFilters] = useState(false);

  const handleSubmit = (e) => {
    e.preventDefault();
    search();
  };

  const hasFilters = filters.collection || filters.document_type;

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* Header */}
      <div className="bg-white/80 backdrop-blur-sm border-b border-cream-200 px-6 py-5">
        <div className="flex items-center gap-3 mb-4">
          <div className="w-9 h-9 rounded-xl bg-amber-900/10 flex items-center justify-center">
            <SearchIcon size={18} className="text-amber-900" />
          </div>
          <h1 className="font-serif text-xl font-bold text-ink-900">
            Search Knowledge Base
          </h1>
        </div>

        {/* Search bar */}
        <form onSubmit={handleSubmit} className="flex gap-3">
          <div className="flex-1 relative">
            <SearchIcon
              size={18}
              className="absolute left-3.5 top-1/2 -translate-y-1/2 text-cream-400"
            />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search documents, policies, research…"
              className="input pl-10"
            />
            {query && (
              <button
                type="button"
                onClick={() => {
                  setQuery('');
                  clearResults();
                }}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-cream-400 hover:text-ink-700"
              >
                <X size={16} />
              </button>
            )}
          </div>

          <button
            type="button"
            onClick={() => setShowFilters(!showFilters)}
            className={`btn-secondary ${hasFilters ? '!border-amber-800 !text-amber-800' : ''}`}
          >
            <Filter size={16} />
            Filters
            {hasFilters && (
              <span className="w-2 h-2 rounded-full bg-amber-800" />
            )}
          </button>

          <button type="submit" disabled={!query.trim() || isSearching} className="btn-primary">
            {isSearching ? <Loader2 size={16} className="animate-spin" /> : <SearchIcon size={16} />}
            Search
          </button>
        </form>

        {/* Filters panel */}
        <AnimatePresence>
          {showFilters && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              className="overflow-hidden"
            >
              <div className="flex items-center gap-4 mt-4 pt-4 border-t border-cream-100">
                <SelectFilter
                  label="Collection"
                  options={COLLECTIONS}
                  value={filters.collection || ''}
                  onChange={(v) => setFilter('collection', v || null)}
                />
                <SelectFilter
                  label="Document Type"
                  options={DOCUMENT_TYPES}
                  value={filters.document_type || ''}
                  onChange={(v) => setFilter('document_type', v || null)}
                />
                {hasFilters && (
                  <button
                    onClick={clearFilters}
                    className="btn-ghost text-xs text-terra-500 mt-4"
                  >
                    Clear filters
                  </button>
                )}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* Results */}
      <div className="flex-1 overflow-y-auto px-6 py-4">
        {error && (
          <div className="p-4 rounded-xl bg-terra-500/10 border border-terra-500/20 text-terra-500 text-sm mb-4">
            {error}
          </div>
        )}

        {isSearching ? (
          <div className="flex flex-col items-center justify-center py-20">
            <div className="relative">
              <Loader2 size={32} className="text-violet-500 animate-spin" />
              <div className="absolute inset-0 bg-violet-500/10 rounded-full blur-xl" />
            </div>
            <p className="text-ink-600 text-sm mt-4">Searching knowledge base…</p>
          </div>
        ) : results.length > 0 ? (
          <div className="space-y-3 max-w-4xl">
            <p className="text-xs text-ink-600 mb-3">
              <span className="font-medium text-ink-900">{results.length}</span> result{results.length !== 1 ? 's' : ''} found
            </p>
            {results.map((result, idx) => (
              <motion.div
                key={idx}
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: idx * 0.05, duration: 0.3 }}
              >
                <SearchResultCard result={result} rank={idx + 1} />
              </motion.div>
            ))}
          </div>
        ) : query && !isSearching ? (
          <div className="flex flex-col items-center justify-center py-20 text-center">
            <div className="w-16 h-16 rounded-2xl bg-cream-200 flex items-center justify-center mb-4">
              <SearchIcon size={28} className="text-cream-400" />
            </div>
            <h3 className="font-semibold text-ink-900 mb-1">No results found</h3>
            <p className="text-ink-600 text-sm max-w-sm">
              Try different keywords or adjust your filters
            </p>
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center py-20 text-center">
            <div className="w-16 h-16 rounded-2xl bg-amber-900/10 flex items-center justify-center mb-4">
              <Sparkles size={28} className="text-amber-900" />
            </div>
            <h3 className="font-semibold text-ink-900 mb-1">
              Search Pwani University's knowledge base
            </h3>
            <p className="text-ink-600 text-sm max-w-sm">
              Find academic programs, policies, research papers, and institutional documents
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

function SelectFilter({ label, options, value, onChange }) {
  return (
    <div className="relative">
      <label className="block text-[10px] text-ink-600 mb-1 font-medium">{label}</label>
      <div className="relative">
        <select
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="input !py-2 !pr-8 text-sm appearance-none cursor-pointer"
        >
          {options.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
        <ChevronDown
          size={14}
          className="absolute right-3 top-1/2 -translate-y-1/2 text-cream-400 pointer-events-none"
        />
      </div>
    </div>
  );
}

function SearchResultCard({ result, rank }) {
  const score = result.relevance_score ?? result.score;
  const scorePercent = score != null ? Math.round(score * 100) : null;

  return (
    <div className="group bg-white rounded-2xl border border-cream-200 p-5 shadow-warm-sm
      hover:shadow-warm hover:-translate-y-0.5 transition-all duration-200">
      <div className="flex items-start gap-3">
        <span className="flex-shrink-0 w-7 h-7 rounded-lg bg-gradient-to-br from-violet-500 to-violet-600 text-white text-xs font-bold flex items-center justify-center shadow-sm">
          {rank}
        </span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1.5">
            <FileText size={14} className="text-amber-800 flex-shrink-0" />
            <h3 className="text-sm font-semibold text-ink-900 truncate group-hover:text-violet-500 transition-colors">
              {result.document_name || result.document_title || 'Unknown Document'}
            </h3>
            {result.collection && (
              <span className="inline-flex items-center px-2 py-0.5 text-[10px] font-medium rounded-full
                bg-amber-900/10 text-amber-900 border border-amber-900/10">
                {result.collection}
              </span>
            )}
          </div>

          {(result.chunk_text || result.text) && (
            <p className="text-sm text-ink-600 leading-relaxed line-clamp-3 mb-3">
              {result.chunk_text || result.text}
            </p>
          )}

          <div className="flex items-center gap-4">
            {scorePercent != null && (
              <div className="flex items-center gap-2">
                <div className="w-16 h-1.5 bg-cream-200 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-gradient-to-r from-violet-500 to-violet-400 rounded-full"
                    style={{ width: `${scorePercent}%` }}
                  />
                </div>
                <span className="text-[11px] text-ink-600 font-medium">
                  {scorePercent}%
                </span>
              </div>
            )}
            {result.document_id && (
              <Link
                to={`/documents/${result.document_id}`}
                className="text-[11px] font-medium text-violet-500 hover:text-violet-600 hover:underline transition-colors"
              >
                View document →
              </Link>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
