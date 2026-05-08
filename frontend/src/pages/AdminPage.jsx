import { useEffect } from 'react';
import { useAdminStore } from '../store/adminStore';
import UploadTab from '../components/admin/UploadTab';
import DocumentsTab from '../components/admin/DocumentsTab';
import UsersTab from '../components/admin/UsersTab';
import StatsTab from '../components/admin/StatsTab';
import {
  Upload,
  FileText,
  Users,
  BarChart3,
  Shield,
} from 'lucide-react';

const tabs = [
  { id: 'upload', label: 'Upload', icon: Upload },
  { id: 'documents', label: 'Documents', icon: FileText },
  { id: 'users', label: 'Users', icon: Users },
  { id: 'stats', label: 'Analytics', icon: BarChart3 },
];

export default function AdminPage() {
  const { activeTab, setActiveTab, loadStats } = useAdminStore();

  useEffect(() => {
    loadStats();
  }, [loadStats]);

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* Header with tabs */}
      <div className="bg-white/80 backdrop-blur-sm border-b border-cream-200 px-6 pt-5">
        <div className="flex items-center gap-3 mb-5">
          <div className="w-9 h-9 rounded-xl bg-violet-500/10 flex items-center justify-center">
            <Shield size={18} className="text-violet-500" />
          </div>
          <h1 className="font-serif text-xl font-bold text-ink-900">
            Admin Panel
          </h1>
        </div>
        <div className="flex gap-1">
          {tabs.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => setActiveTab(id)}
              className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium rounded-t-xl border-b-2 transition-all duration-200
                ${
                  activeTab === id
                    ? 'border-amber-800 text-amber-900 bg-amber-900/5'
                    : 'border-transparent text-ink-600 hover:text-ink-900 hover:bg-cream-50'
                }`}
            >
              <Icon size={16} />
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-y-auto">
        {activeTab === 'upload' && <UploadTab />}
        {activeTab === 'documents' && <DocumentsTab />}
        {activeTab === 'users' && <UsersTab />}
        {activeTab === 'stats' && <StatsTab />}
      </div>
    </div>
  );
}
