import { Routes, Route, Navigate } from 'react-router-dom';
import { useAuthStore } from './store/authStore';
import Layout from './components/Layout';
import LandingPage from './pages/LandingPage';
import LoginPage from './pages/LoginPage';
import ChatPage from './pages/ChatPage';
import AgentsPage from './pages/AgentsPage';
import ConnectorsPage from './pages/ConnectorsPage';
import SkillsPage from './pages/SkillsPage';
import SearchPage from './pages/SearchPage';
import AdminPage from './pages/AdminPage';
import DocumentViewerPage from './pages/DocumentViewerPage';
import KnowledgeGraphPage from './pages/KnowledgeGraphPage';
import CorpusExplorerPage from './pages/CorpusExplorerPage';
import SettingsPage from './pages/SettingsPage';

function ProtectedRoute({ children, roles }) {
  const { user, isAuthenticated } = useAuthStore();

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  if (roles && !roles.includes(user?.role)) {
    return <Navigate to="/chat" replace />;
  }

  return children;
}

export default function App() {
  const { isAuthenticated } = useAuthStore();

  return (
    <Routes>
      {/* Public landing page */}
      <Route
        path="/"
        element={
          isAuthenticated ? <Navigate to="/chat" replace /> : <LandingPage />
        }
      />

      <Route
        path="/login"
        element={
          isAuthenticated ? <Navigate to="/chat" replace /> : <LoginPage />
        }
      />

      {/* Authenticated app shell */}
      <Route
        path="/app"
        element={
          <ProtectedRoute>
            <Layout />
          </ProtectedRoute>
        }
      >
        <Route index element={<Navigate to="/chat" replace />} />
      </Route>

      <Route
        element={
          <ProtectedRoute>
            <Layout />
          </ProtectedRoute>
        }
      >
        <Route path="chat" element={<ChatPage />} />
        <Route path="chat/:conversationId" element={<ChatPage />} />
        <Route path="agents" element={<AgentsPage />} />
        <Route path="agents/:conversationId" element={<AgentsPage />} />
        <Route path="connectors" element={<ConnectorsPage />} />
        <Route
          path="skills"
          element={
            <ProtectedRoute roles={['admin']}>
              <SkillsPage />
            </ProtectedRoute>
          }
        />
        <Route path="search" element={<SearchPage />} />
        <Route path="documents/:id" element={<DocumentViewerPage />} />
        <Route
          path="graph"
          element={
            <ProtectedRoute roles={['admin', 'researcher']}>
              <KnowledgeGraphPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="corpus"
          element={
            <ProtectedRoute roles={['admin', 'researcher']}>
              <CorpusExplorerPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="admin"
          element={
            <ProtectedRoute roles={['admin']}>
              <AdminPage />
            </ProtectedRoute>
          }
        />
      </Route>

      {/* Full-screen settings shell — outside the app Layout (no app sidebar) */}
      <Route
        path="settings"
        element={
          <ProtectedRoute>
            <SettingsPage />
          </ProtectedRoute>
        }
      />

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
