import { Routes, Route, Navigate } from 'react-router-dom';
import { useAuthStore } from './store/authStore';
import Layout from './components/Layout';
import LandingPage from './pages/LandingPage';
import LoginPage from './pages/LoginPage';
import ChatPage from './pages/ChatPage';
import SearchPage from './pages/SearchPage';
import AdminPage from './pages/AdminPage';
import DocumentViewerPage from './pages/DocumentViewerPage';

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
        <Route path="search" element={<SearchPage />} />
        <Route path="documents/:id" element={<DocumentViewerPage />} />
        <Route
          path="admin"
          element={
            <ProtectedRoute roles={['admin']}>
              <AdminPage />
            </ProtectedRoute>
          }
        />
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
