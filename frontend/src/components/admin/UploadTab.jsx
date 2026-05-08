import { useState, useCallback } from 'react';
import { useAdminStore } from '../../store/adminStore';
import {
  Upload,
  FileText,
  CheckCircle,
  AlertCircle,
  Loader2,
  X,
} from 'lucide-react';

const COLLECTIONS = [
  { value: 'academic', label: 'Academic', desc: 'Course materials, syllabi, research' },
  { value: 'departmental', label: 'Departmental', desc: 'Department policies, reports' },
  { value: 'administrative', label: 'Administrative', desc: 'Administrative documents' },
  { value: 'management', label: 'Management', desc: 'Strategic & management docs' },
];

const ACCEPTED_TYPES = {
  'application/pdf': '.pdf',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document': '.docx',
  'text/html': '.html',
};

export default function UploadTab() {
  const { uploadDocument, uploadJobs, clearUploadJobs } = useAdminStore();
  const [collection, setCollection] = useState('academic');
  const [isDragging, setIsDragging] = useState(false);
  const [error, setError] = useState(null);

  const handleFiles = useCallback(
    async (files) => {
      setError(null);
      for (const file of files) {
        if (!Object.keys(ACCEPTED_TYPES).includes(file.type)) {
          setError(`Unsupported file type: ${file.name}. Use PDF, DOCX, or HTML.`);
          continue;
        }
        try {
          await uploadDocument(file, collection);
        } catch (err) {
          setError(err.response?.data?.detail || `Failed to upload ${file.name}`);
        }
      }
    },
    [collection, uploadDocument]
  );

  const handleDrop = useCallback(
    (e) => {
      e.preventDefault();
      setIsDragging(false);
      const files = Array.from(e.dataTransfer.files);
      if (files.length) handleFiles(files);
    },
    [handleFiles]
  );

  const handleDragOver = (e) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = () => setIsDragging(false);

  const handleFileInput = (e) => {
    const files = Array.from(e.target.files || []);
    if (files.length) handleFiles(files);
    e.target.value = '';
  };

  return (
    <div className="p-6 max-w-3xl mx-auto space-y-6">
      {/* Collection selector */}
      <div>
        <label className="block text-sm font-medium text-ink-700 mb-2">
          Target Collection
        </label>
        <div className="grid grid-cols-2 gap-3">
          {COLLECTIONS.map(({ value, label, desc }) => (
            <button
              key={value}
              onClick={() => setCollection(value)}
              className={`p-3 rounded-xl border text-left transition-all ${
                collection === value
                  ? 'border-violet-500 bg-violet-500/5 ring-2 ring-violet-500/20'
                  : 'border-cream-200 hover:border-sand-400'
              }`}
            >
              <p className="text-sm font-medium text-ink-900">{label}</p>
              <p className="text-[11px] text-sand-500">{desc}</p>
            </button>
          ))}
        </div>
      </div>

      {/* Drop zone */}
      <div
        onDrop={handleDrop}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        className={`relative border-2 border-dashed rounded-2xl p-10 text-center transition-all ${
          isDragging
            ? 'border-violet-500 bg-violet-500/5'
            : 'border-cream-300 hover:border-sand-400'
        }`}
      >
        <input
          type="file"
          onChange={handleFileInput}
          multiple
          accept=".pdf,.docx,.html"
          className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
        />
        <Upload
          size={40}
          className={`mx-auto mb-3 ${
            isDragging ? 'text-violet-500' : 'text-cream-300'
          }`}
        />
        <p className="text-sm font-medium text-ink-700">
          Drop files here or click to browse
        </p>
        <p className="text-xs text-sand-400 mt-1">
          PDF, DOCX, HTML — Up to 50MB per file
        </p>
      </div>

      {/* Error */}
      {error && (
        <div className="p-3 rounded-xl bg-terra-500/10 border border-terra-500/20 text-terra-500 text-sm flex items-center gap-2">
          <AlertCircle size={16} />
          {error}
        </div>
      )}

      {/* Upload jobs */}
      {uploadJobs.length > 0 && (
        <div>
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-medium text-ink-700">Upload Progress</h3>
            <button
              onClick={clearUploadJobs}
              className="btn-ghost text-xs text-sand-400"
            >
              Clear all
            </button>
          </div>
          <div className="space-y-2">
            {uploadJobs.map((job) => (
              <UploadJobItem key={job.id} job={job} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function UploadJobItem({ job }) {
  const statusConfig = {
    uploading: { icon: Loader2, color: 'text-violet-500', label: 'Uploading…', spin: true },
    processing: { icon: Loader2, color: 'text-sand-500', label: 'Processing…', spin: true },
    completed: { icon: CheckCircle, color: 'text-forest-500', label: 'Completed' },
    failed: { icon: AlertCircle, color: 'text-terra-500', label: 'Failed' },
    pending: { icon: Loader2, color: 'text-sand-400', label: 'Pending…', spin: true },
  };

  const cfg = statusConfig[job.status] || statusConfig.pending;
  const Icon = cfg.icon;

  return (
    <div className="flex items-center gap-3 p-3 rounded-xl bg-cream-50 border border-cream-200">
      <FileText size={16} className="text-sand-400 flex-shrink-0" />
      <div className="flex-1 min-w-0">
        <p className="text-sm text-ink-700 truncate">{job.fileName}</p>
        {job.status === 'uploading' && (
          <div className="mt-1 h-1.5 bg-cream-200 rounded-full overflow-hidden">
            <div
              className="h-full bg-violet-500 rounded-full transition-all"
              style={{ width: `${job.progress}%` }}
            />
          </div>
        )}
      </div>
      <div className={`flex items-center gap-1.5 text-xs font-medium ${cfg.color}`}>
        <Icon size={14} className={cfg.spin ? 'animate-spin' : ''} />
        {cfg.label}
      </div>
    </div>
  );
}
