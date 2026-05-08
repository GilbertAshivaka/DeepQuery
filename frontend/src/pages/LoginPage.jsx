import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import { useAuthStore } from '../store/authStore';
import { BookOpen, Eye, EyeOff, Loader2, ArrowLeft } from 'lucide-react';

export default function LoginPage() {
  const { login, isLoading, error, clearError } = useAuthStore();
  const navigate = useNavigate();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    clearError();
    try {
      await login(username, password);
    } catch {
      // Error is set in store
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-hero px-4 relative overflow-hidden">
      {/* Animated background blobs */}
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        <motion.div
          animate={{ x: [0, 30, 0], y: [0, -20, 0] }}
          transition={{ duration: 8, repeat: Infinity, ease: 'easeInOut' }}
          className="absolute -top-40 -right-40 w-96 h-96 rounded-full bg-violet-500/5 blur-3xl"
        />
        <motion.div
          animate={{ x: [0, -20, 0], y: [0, 30, 0] }}
          transition={{ duration: 10, repeat: Infinity, ease: 'easeInOut' }}
          className="absolute -bottom-40 -left-40 w-96 h-96 rounded-full bg-amber-800/5 blur-3xl"
        />
        <motion.div
          animate={{ scale: [1, 1.1, 1] }}
          transition={{ duration: 6, repeat: Infinity, ease: 'easeInOut' }}
          className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] rounded-full bg-cream-200/30 blur-3xl"
        />
      </div>

      {/* Back to home */}
      <motion.button
        initial={{ opacity: 0, x: -16 }}
        animate={{ opacity: 1, x: 0 }}
        transition={{ delay: 0.3 }}
        onClick={() => navigate('/')}
        className="absolute top-6 left-6 flex items-center gap-1.5 text-sm text-ink-600 hover:text-ink-900 transition-colors"
      >
        <ArrowLeft size={16} />
        Home
      </motion.button>

      <motion.div
        initial={{ opacity: 0, y: 24 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, ease: 'easeOut' }}
        className="relative w-full max-w-md"
      >
        {/* Logo */}
        <div className="text-center mb-8">
          <motion.div
            initial={{ scale: 0.8 }}
            animate={{ scale: 1 }}
            transition={{ delay: 0.1, type: 'spring', stiffness: 200 }}
            className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-gradient-to-br from-amber-800 to-amber-950 text-amber-200 mb-4 shadow-warm-lg"
          >
            <BookOpen size={28} />
          </motion.div>
          <h1 className="font-serif text-3xl font-bold text-ink-900">Deep Query</h1>
          <p className="text-ink-600 mt-1">
            Semantic Knowledge Management Ecosystem
          </p>
          <p className="text-ink-600 text-sm">Pwani University</p>
        </div>

        {/* Login Card */}
        <div className="bg-white/90 backdrop-blur-md rounded-2xl border border-cream-200 shadow-warm-lg p-8">
          <h2 className="text-lg font-semibold text-ink-900 mb-6">Sign in to continue</h2>

          <form onSubmit={handleSubmit} className="space-y-5">
            {/* Error */}
            {error && (
              <motion.div
                initial={{ opacity: 0, y: -8 }}
                animate={{ opacity: 1, y: 0 }}
                className="p-3 rounded-xl bg-terra-500/10 border border-terra-500/20 text-terra-500 text-sm"
              >
                {error}
              </motion.div>
            )}

            {/* Username */}
            <div>
              <label
                htmlFor="username"
                className="block text-sm font-medium text-ink-700 mb-1.5"
              >
                Username
              </label>
              <input
                id="username"
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                className="input"
                placeholder="Enter your username"
                autoComplete="username"
                required
              />
            </div>

            {/* Password */}
            <div>
              <label
                htmlFor="password"
                className="block text-sm font-medium text-ink-700 mb-1.5"
              >
                Password
              </label>
              <div className="relative">
                <input
                  id="password"
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="input pr-10"
                  placeholder="Enter your password"
                  autoComplete="current-password"
                  required
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-cream-400 hover:text-ink-700 transition-colors"
                >
                  {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                </button>
              </div>
            </div>

            {/* Submit */}
            <button
              type="submit"
              disabled={isLoading || !username || !password}
              className="w-full inline-flex items-center justify-center gap-2 px-5 py-3
                bg-gradient-to-r from-amber-800 to-amber-900 text-white font-semibold rounded-xl
                hover:from-amber-900 hover:to-amber-950 active:scale-[0.98]
                transition-all duration-200 shadow-warm
                disabled:opacity-50 disabled:cursor-not-allowed disabled:active:scale-100"
            >
              {isLoading ? (
                <>
                  <Loader2 size={18} className="animate-spin" />
                  Signing in…
                </>
              ) : (
                'Sign In'
              )}
            </button>
          </form>

          <p className="mt-6 text-center text-xs text-ink-600">
            Contact your administrator for account access
          </p>
        </div>
      </motion.div>
    </div>
  );
}
