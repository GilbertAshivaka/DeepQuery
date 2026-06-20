import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuthStore } from '../store/authStore';
import {
  X,
  User,
  Palette,
  Cpu,
  KeyRound,
  Layers,
  ChevronLeft,
} from 'lucide-react';
import AccountSection from '../components/settings/AccountSection';
import AppearanceSection from '../components/settings/AppearanceSection';
import ModelsSection from '../components/settings/ModelsSection';
import ApiKeysSection from '../components/settings/ApiKeysSection';
import EmbeddingsSection from '../components/settings/EmbeddingsSection';

const SECTIONS = [
  { id: 'account', label: 'Account', icon: User, group: 'Account', Component: AccountSection },
  { id: 'appearance', label: 'Appearance', icon: Palette, group: 'Account', Component: AppearanceSection },
  { id: 'models', label: 'Models & Providers', icon: Cpu, group: 'Administration', admin: true, Component: ModelsSection },
  { id: 'keys', label: 'API Keys', icon: KeyRound, group: 'Administration', admin: true, Component: ApiKeysSection },
  { id: 'embeddings', label: 'Embeddings', icon: Layers, group: 'Administration', admin: true, Component: EmbeddingsSection },
];

export default function SettingsPage() {
  const navigate = useNavigate();
  const { user } = useAuthStore();
  const isAdmin = user?.role === 'admin';

  const sections = SECTIONS.filter((s) => !s.admin || isAdmin);
  const [activeId, setActiveId] = useState(sections[0]?.id || 'account');
  const active = sections.find((s) => s.id === activeId) || sections[0];
  const ActiveComponent = active?.Component;

  const close = () => navigate(-1);

  // Group the nav items, preserving order.
  const groups = sections.reduce((acc, s) => {
    (acc[s.group] = acc[s.group] || []).push(s);
    return acc;
  }, {});

  return (
    <div className="fixed inset-0 z-40 flex bg-cream-50">
      {/* Settings side-panel nav */}
      <aside className="flex flex-col w-72 flex-shrink-0 bg-sidebar border-r border-black/10">
        <div className="flex items-center gap-2 px-4 h-16 border-b border-black/10">
          <button
            onClick={close}
            className="p-2 -ml-1 rounded-xl text-ink-700 hover:text-ink-900 hover:bg-white/40 transition-all"
            title="Back to app"
          >
            <ChevronLeft size={18} />
          </button>
          <h1 className="font-serif text-lg font-bold text-ink-900">Settings</h1>
        </div>

        <nav className="flex-1 overflow-y-auto px-3 py-4 space-y-5">
          {Object.entries(groups).map(([group, items]) => (
            <div key={group}>
              <p className="px-3 mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-ink-600">
                {group}
              </p>
              <div className="space-y-1">
                {items.map(({ id, label, icon: Icon }) => (
                  <button
                    key={id}
                    onClick={() => setActiveId(id)}
                    className={`flex items-center gap-3 w-full px-3 py-2.5 rounded-xl text-sm font-medium transition-all duration-200
                      ${
                        activeId === id
                          ? 'bg-white/60 text-ink-900 shadow-warm-sm'
                          : 'text-ink-700 hover:text-ink-900 hover:bg-white/40'
                      }`}
                  >
                    <Icon size={18} />
                    <span>{label}</span>
                  </button>
                ))}
              </div>
            </div>
          ))}
        </nav>

        <div className="px-4 py-3 border-t border-black/10">
          <div className="flex items-center gap-3">
            <div className="flex items-center justify-center w-8 h-8 rounded-full bg-amber-800 text-white text-xs font-bold flex-shrink-0">
              {user?.username?.[0]?.toUpperCase() || 'U'}
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-ink-900 truncate">{user?.username}</p>
              <p className="text-[10px] text-ink-600 capitalize">{user?.role}</p>
            </div>
          </div>
        </div>
      </aside>

      {/* Content pane */}
      <div className="flex-1 flex flex-col overflow-hidden">
        <div className="flex items-center justify-between px-8 h-16 border-b border-cream-200 bg-white/70 backdrop-blur-sm">
          <div className="flex items-center gap-3">
            {active?.icon && (
              <div className="w-9 h-9 rounded-xl bg-violet-500/10 flex items-center justify-center">
                <active.icon size={18} className="text-violet-500" />
              </div>
            )}
            <h2 className="font-serif text-xl font-bold text-ink-900">{active?.label}</h2>
          </div>
          <button
            onClick={close}
            className="p-2 rounded-xl text-ink-600 hover:text-ink-900 hover:bg-cream-100 transition-all"
            title="Close settings"
          >
            <X size={20} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto">
          <div className="max-w-3xl mx-auto px-8 py-8">
            {ActiveComponent && <ActiveComponent />}
          </div>
        </div>
      </div>
    </div>
  );
}
