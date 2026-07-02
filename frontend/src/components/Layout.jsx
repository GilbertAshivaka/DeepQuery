import { useState, useRef, useEffect } from 'react';
import { Outlet, NavLink, useNavigate, useLocation } from 'react-router-dom';
import ErrorBoundary from './ErrorBoundary';
import ToastContainer from './ui/ToastContainer';
import { useAuthStore } from '../store/authStore';
import { useChatStore } from '../store/chatStore';
import {
  MessageSquare,
  Bot,
  Plug,
  ScrollText,
  Search,
  Shield,
  LogOut,
  Plus,
  Menu,
  X,
  ChevronRight,
  MoreHorizontal,
  Pin,
  Trash2,
  Network,
  ScatterChart,
  Settings,
  ChevronsUpDown,
} from 'lucide-react';

const navItems = [
  { to: '/chat', icon: MessageSquare, label: 'Chat' },
  { to: '/agents', icon: Bot, label: 'Agents' },
  { to: '/connectors', icon: Plug, label: 'Connectors' },
  { to: '/search', icon: Search, label: 'Search' },
];

const graphNavItems = [
  { to: '/graph',  icon: Network,      label: 'Knowledge Graph' },
  { to: '/corpus', icon: ScatterChart, label: 'Corpus Explorer' },
];

const adminNavItems = [
  { to: '/skills', icon: ScrollText, label: 'Skills' },
  { to: '/admin', icon: Shield, label: 'Admin' },
];

export default function Layout() {
  const { user, logout } = useAuthStore();
  const {
    conversations,
    startNewConversation,
    setActiveConversation,
    loadConversations,
    deleteConversation,
    togglePinConversation,
  } = useChatStore();
  const navigate = useNavigate();
  const location = useLocation();
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [showHistory, setShowHistory] = useState(false);
  const [menuOpenId, setMenuOpenId] = useState(null);
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const menuRef = useRef(null);
  const userMenuRef = useRef(null);

  // Close menus on click outside
  useEffect(() => {
    const handleClickOutside = (e) => {
      if (menuRef.current && !menuRef.current.contains(e.target)) {
        setMenuOpenId(null);
      }
      if (userMenuRef.current && !userMenuRef.current.contains(e.target)) {
        setUserMenuOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const isAdmin = user?.role === 'admin';
  const canViewGraph = user?.role === 'admin' || user?.role === 'researcher';

  const handleNewChat = () => {
    startNewConversation();
    navigate('/chat');
  };

  const handleSelectConversation = (convId) => {
    setActiveConversation(convId);
    navigate(`/chat/${convId}`);
    setShowHistory(false);
  };

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  const toggleHistory = () => {
    if (!showHistory) {
      loadConversations();
    }
    setShowHistory(!showHistory);
  };

  return (
    <div className="flex h-screen overflow-hidden bg-cream-50">
      {/* App-wide ephemeral notifications (errors, info) */}
      <ToastContainer />
      {/* Sidebar */}
      <aside
        className={`
          flex flex-col bg-sidebar
          transition-all duration-300 ease-in-out relative
          ${sidebarOpen ? 'w-72' : 'w-16'}
        `}
      >
        {/* Logo */}
        <div className="relative flex items-center gap-3 px-4 h-16 border-b border-black/10">
          <img
            src="/deepqueryLogo.svg"
            alt="DeepQuery"
            className="w-8 h-8 rounded-lg object-cover flex-shrink-0"
          />
          {sidebarOpen && (
            <div className="animate-fade-in">
              <h1 className="font-mono text-lg font-bold text-amber-900 leading-tight">
                DeepQuery
              </h1>
            </div>
          )}
        </div>

        {/* Sidebar toggle + New Chat */}
        <div className="relative px-3 pt-4 pb-2 space-y-2">
          <div className={`flex ${sidebarOpen ? 'justify-end' : 'justify-center'}`}>
            <button
              onClick={() => setSidebarOpen(!sidebarOpen)}
              className="p-2.5 rounded-xl text-ink-700 hover:text-ink-900 hover:bg-white/40 transition-all"
              title={sidebarOpen ? 'Collapse sidebar' : 'Expand sidebar'}
            >
              {sidebarOpen ? <X size={16} /> : <Menu size={16} />}
            </button>
          </div>
          <button
            onClick={handleNewChat}
            className={`w-full inline-flex items-center justify-center gap-2 px-4 py-2.5
              bg-white/60 hover:bg-white/80 text-ink-900 font-medium rounded-xl
              border border-black/10
              active:scale-[0.98] transition-all duration-200
              ${!sidebarOpen ? '!px-0' : ''}`}
          >
            <Plus size={16} />
            {sidebarOpen && <span>New Chat</span>}
          </button>
        </div>

        {/* Navigation */}
        <nav className="relative flex-1 px-3 py-2 space-y-1 overflow-y-auto">
          {navItems.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium
                transition-all duration-200
                ${
                  isActive
                    ? 'bg-white/50 text-ink-900 shadow-warm-sm'
                    : 'text-ink-700 hover:text-ink-900 hover:bg-white/40'
                }
                ${!sidebarOpen ? 'justify-center !px-0' : ''}`
              }
            >
              <Icon size={18} />
              {sidebarOpen && <span>{label}</span>}
            </NavLink>
          ))}

          {canViewGraph &&
            graphNavItems.map(({ to, icon: Icon, label }) => (
              <NavLink
                key={to}
                to={to}
                className={({ isActive }) =>
                  `flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium
                  transition-all duration-200
                  ${
                    isActive
                      ? 'bg-white/50 text-ink-900 shadow-warm-sm'
                      : 'text-ink-700 hover:text-ink-900 hover:bg-white/40'
                  }
                  ${!sidebarOpen ? 'justify-center !px-0' : ''}`
                }
              >
                <Icon size={18} />
                {sidebarOpen && <span>{label}</span>}
              </NavLink>
            ))}

          {isAdmin &&
            adminNavItems.map(({ to, icon: Icon, label }) => (
              <NavLink
                key={to}
                to={to}
                className={({ isActive }) =>
                  `flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium
                  transition-all duration-200
                  ${
                    isActive
                      ? 'bg-white/50 text-ink-900 shadow-warm-sm'
                      : 'text-ink-700 hover:text-ink-900 hover:bg-white/40'
                  }
                  ${!sidebarOpen ? 'justify-center !px-0' : ''}`
                }
              >
                <Icon size={18} />
                {sidebarOpen && <span>{label}</span>}
              </NavLink>
            ))}

          {/* Conversation History Toggle */}
          {sidebarOpen && (
            <button
              onClick={toggleHistory}
              className="flex items-center gap-3 w-full px-3 py-2.5 mt-4 rounded-xl text-sm font-medium
                text-ink-700 hover:text-ink-900 hover:bg-white/40 transition-all duration-200"
            >
              <ChevronRight
                size={16}
                className={`transition-transform ${showHistory ? 'rotate-90' : ''}`}
              />
              <span>History</span>
            </button>
          )}

          {/* Conversation List */}
          {sidebarOpen && showHistory && (
            <div className="ml-2 space-y-0.5 animate-slide-up">
              {conversations.length === 0 ? (
                <p className="px-3 py-2 text-xs text-ink-600">No conversations yet</p>
              ) : (
                [...conversations]
                  .sort((a, b) => (b.is_pinned ? 1 : 0) - (a.is_pinned ? 1 : 0))
                  .map((conv) => (
                  <div
                    key={conv.id}
                    className="group relative flex items-center w-full rounded-lg
                      hover:bg-white/40 transition-all"
                  >
                    <button
                      onClick={() => handleSelectConversation(conv.id)}
                      className="flex items-center gap-2 flex-1 min-w-0 px-3 py-2 text-xs
                        text-ink-700 hover:text-ink-900 truncate transition-all"
                    >
                      {conv.is_pinned ? (
                        <Pin size={12} className="flex-shrink-0 text-amber-700 -rotate-45" />
                      ) : (
                        <MessageSquare size={12} className="flex-shrink-0 text-ink-600" />
                      )}
                      <span className="truncate">{conv.title || 'Untitled'}</span>
                    </button>

                    {/* Three-dot menu trigger */}
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        setMenuOpenId(menuOpenId === conv.id ? null : conv.id);
                      }}
                      className="flex-shrink-0 p-1 mr-1 rounded-md text-ink-600
                        opacity-0 group-hover:opacity-100 hover:bg-black/10
                        transition-all duration-150"
                    >
                      <MoreHorizontal size={14} />
                    </button>

                    {/* Dropdown menu */}
                    {menuOpenId === conv.id && (
                      <div
                        ref={menuRef}
                        className="absolute right-0 top-full mt-1 z-50 w-36 py-1
                          bg-white rounded-xl border border-cream-200 shadow-warm-lg
                          animate-fade-in"
                      >
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            togglePinConversation(conv.id);
                            setMenuOpenId(null);
                          }}
                          className="flex items-center gap-2 w-full px-3 py-2 text-xs text-ink-700
                            hover:bg-cream-50 transition-colors"
                        >
                          <Pin size={13} className={conv.is_pinned ? 'text-amber-700 -rotate-45' : ''} />
                          {conv.is_pinned ? 'Unpin' : 'Pin'}
                        </button>
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            deleteConversation(conv.id);
                            setMenuOpenId(null);
                          }}
                          className="flex items-center gap-2 w-full px-3 py-2 text-xs text-terra-500
                            hover:bg-terra-500/5 transition-colors"
                        >
                          <Trash2 size={13} />
                          Delete
                        </button>
                      </div>
                    )}
                  </div>
                ))
              )}
            </div>
          )}
        </nav>

        {/* User footer */}
        <div className="relative px-3 py-3 border-t border-black/10">
          <div className={`flex items-center gap-2 ${!sidebarOpen ? 'justify-center' : ''}`}>
            {/* Account button — opens the popup in both collapsed and expanded modes */}
            <div ref={userMenuRef} className={`relative ${sidebarOpen ? 'flex-1 min-w-0' : ''}`}>
              {userMenuOpen && (
                <div
                  className="absolute bottom-full left-0 mb-2 z-50 w-56 py-1.5
                    bg-white rounded-xl border border-cream-200 shadow-warm-lg animate-fade-in"
                >
                  {/* Account header */}
                  <div className="flex items-center gap-3 px-3 py-2">
                    <div className="flex items-center justify-center w-8 h-8 rounded-full bg-amber-800 text-white text-xs font-bold flex-shrink-0">
                      {user?.username?.[0]?.toUpperCase() || 'U'}
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-ink-900 truncate">
                        {user?.username}
                      </p>
                      <p className="text-[10px] text-ink-600 capitalize">{user?.role}</p>
                    </div>
                  </div>
                  <div className="my-1 border-t border-cream-200" />
                  <button
                    onClick={() => {
                      setUserMenuOpen(false);
                      navigate('/settings');
                    }}
                    className="flex items-center gap-2.5 w-full px-3 py-2 text-sm text-ink-700
                      hover:bg-cream-50 transition-colors"
                  >
                    <Settings size={15} className="text-ink-600" />
                    Settings
                  </button>
                  <div className="my-1 border-t border-cream-200" />
                  <button
                    onClick={() => {
                      setUserMenuOpen(false);
                      handleLogout();
                    }}
                    className="flex items-center gap-2.5 w-full px-3 py-2 text-sm text-terra-500
                      hover:bg-terra-500/5 transition-colors"
                  >
                    <LogOut size={15} />
                    Log out
                  </button>
                </div>
              )}

              <button
                onClick={() => setUserMenuOpen((o) => !o)}
                title={!sidebarOpen ? user?.username : undefined}
                className={`flex items-center gap-3 rounded-xl transition-all duration-200
                  ${sidebarOpen ? 'w-full px-2 py-1.5' : 'p-1'}
                  ${userMenuOpen ? 'bg-white/60 shadow-warm-sm' : 'hover:bg-white/40'}`}
              >
                <div className="flex items-center justify-center w-8 h-8 rounded-full bg-amber-800 text-white text-xs font-bold flex-shrink-0">
                  {user?.username?.[0]?.toUpperCase() || 'U'}
                </div>
                {sidebarOpen && (
                  <>
                    <div className="flex-1 min-w-0 text-left animate-fade-in">
                      <p className="text-sm font-medium text-ink-900 truncate">
                        {user?.username}
                      </p>
                      <p className="text-[10px] text-ink-600 capitalize">{user?.role}</p>
                    </div>
                    <ChevronsUpDown size={15} className="text-ink-600 flex-shrink-0" />
                  </>
                )}
              </button>
            </div>

            {/* Expanded only: standalone settings + logout icon buttons */}
            {sidebarOpen && (
              <>
                <button
                  onClick={() => navigate('/settings')}
                  className="p-1.5 rounded-lg text-ink-600 hover:text-violet-500 hover:bg-black/5 transition-all"
                  title="Settings"
                >
                  <Settings size={16} />
                </button>
                <button
                  onClick={handleLogout}
                  className="p-1.5 rounded-lg text-ink-600 hover:text-terra-500 hover:bg-black/5 transition-all"
                  title="Logout"
                >
                  <LogOut size={16} />
                </button>
              </>
            )}
          </div>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-hidden">
        <ErrorBoundary key={location.pathname}>
          <Outlet />
        </ErrorBoundary>
      </main>
    </div>
  );
}
