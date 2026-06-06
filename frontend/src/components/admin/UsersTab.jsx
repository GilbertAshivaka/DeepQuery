import { useEffect, useState } from 'react';
import { useAdminStore } from '../../store/adminStore';
import {
  Users as UsersIcon,
  Plus,
  Pencil,
  Trash2,
  Loader2,
  X,
} from 'lucide-react';

const ROLES = [
  { value: 'student', label: 'Student' },
  { value: 'lecturer', label: 'Lecturer' },
  { value: 'researcher', label: 'Researcher' },
  { value: 'hod', label: 'Head of Department' },
  { value: 'admin', label: 'Admin' },
];

export default function UsersTab() {
  const { users, isLoading, loadUsers, createUser, updateUser, deleteUser } =
    useAdminStore();
  const [showForm, setShowForm] = useState(false);
  const [editingUser, setEditingUser] = useState(null);
  const [deleteConfirm, setDeleteConfirm] = useState(null);

  useEffect(() => {
    loadUsers();
  }, [loadUsers]);

  const handleEdit = (user) => {
    setEditingUser(user);
    setShowForm(true);
  };

  const handleCreate = () => {
    setEditingUser(null);
    setShowForm(true);
  };

  const handleDelete = async (userId) => {
    try {
      await deleteUser(userId);
      setDeleteConfirm(null);
    } catch {
      // handled in store
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
      <div className="flex items-center justify-between mb-6">
        <p className="text-sm text-sand-500">{users.length} users</p>
        <button onClick={handleCreate} className="btn-primary text-sm">
          <Plus size={16} /> Add User
        </button>
      </div>

      {/* User form modal */}
      {showForm && (
        <UserFormModal
          user={editingUser}
          onSave={async (data) => {
            if (editingUser) {
              await updateUser(editingUser.id, data);
            } else {
              await createUser(data);
            }
            setShowForm(false);
          }}
          onClose={() => setShowForm(false)}
        />
      )}

      {/* Users list */}
      {users.length === 0 ? (
        <div className="text-center py-16">
          <UsersIcon size={40} className="mx-auto text-cream-300 mb-3" />
          <p className="text-sm text-sand-500">No users found</p>
        </div>
      ) : (
        <div className="space-y-2">
          {users.map((user) => (
            <div
              key={user.id}
              className="flex items-center gap-4 p-4 rounded-xl bg-white border border-cream-200"
            >
              <div className="w-9 h-9 rounded-full bg-sand-400 text-white text-sm font-bold flex items-center justify-center flex-shrink-0">
                {user.username?.[0]?.toUpperCase() || 'U'}
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-ink-900">{user.username}</p>
                <p className="text-[11px] text-sand-500">
                  {user.email || 'No email'} ·{' '}
                  <span className="capitalize">{user.role}</span>
                  {user.department && ` · ${user.department}`}
                </p>
              </div>
              <span
                className={`badge text-[10px] ${
                  user.is_active !== false ? 'badge-success' : 'badge-error'
                }`}
              >
                {user.is_active !== false ? 'Active' : 'Inactive'}
              </span>
              <div className="flex items-center gap-1">
                <button
                  onClick={() => handleEdit(user)}
                  className="btn-ghost !p-2 text-sand-400 hover:text-violet-500"
                >
                  <Pencil size={14} />
                </button>
                {deleteConfirm === user.id ? (
                  <div className="flex items-center gap-1">
                    <button
                      onClick={() => handleDelete(user.id)}
                      className="px-2 py-1 text-xs text-white bg-terra-500 rounded-lg"
                    >
                      Confirm
                    </button>
                    <button
                      onClick={() => setDeleteConfirm(null)}
                      className="px-2 py-1 text-xs text-ink-700 bg-cream-100 rounded-lg"
                    >
                      Cancel
                    </button>
                  </div>
                ) : (
                  <button
                    onClick={() => setDeleteConfirm(user.id)}
                    className="btn-ghost !p-2 text-sand-400 hover:text-terra-500"
                  >
                    <Trash2 size={14} />
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

function UserFormModal({ user, onSave, onClose }) {
  const [form, setForm] = useState({
    username: user?.username || '',
    email: user?.email || '',
    password: '',
    full_name: user?.full_name || '',
    role: user?.role || 'student',
    department: user?.department || '',
    is_active: user?.is_active !== false,
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const payload = { ...form };
      if (user && !payload.password) {
        delete payload.password;
      }
      // Remove department before sending to backend if not needed
      delete payload.department;
      await onSave(payload);
    } catch (err) {
      // Defensive: handle both axios and fetch errors
      let detail = err?.response?.data?.detail || err?.message || 'Failed to save user';
      setError(detail);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink-900/30 backdrop-blur-sm">
      <div className="card w-full max-w-md mx-4 p-6 animate-slide-up">
        <div className="flex items-center justify-between mb-5">
          <h3 className="font-semibold text-ink-900">
            {user ? 'Edit User' : 'Create User'}
          </h3>
          <button onClick={onClose} className="btn-ghost !p-1">
            <X size={18} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          {error && (
            <div className="p-3 rounded-xl bg-terra-500/10 text-terra-500 text-sm">
              {error}
            </div>
          )}

          <div>
            <label className="block text-sm font-medium text-ink-700 mb-1">Username</label>
            <input
              type="text"
              value={form.username}
              onChange={(e) => setForm({ ...form, username: e.target.value })}
              className="input"
              required
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-ink-700 mb-1">Full Name</label>
            <input
              type="text"
              value={form.full_name}
              onChange={(e) => setForm({ ...form, full_name: e.target.value })}
              className="input"
              required
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-ink-700 mb-1">Email</label>
            <input
              type="email"
              value={form.email}
              onChange={(e) => setForm({ ...form, email: e.target.value })}
              className="input"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-ink-700 mb-1">
              {user ? 'New Password (leave blank to keep)' : 'Password'}
            </label>
            <input
              type="password"
              value={form.password}
              onChange={(e) => setForm({ ...form, password: e.target.value })}
              className="input"
              {...(!user ? { required: true } : {})}
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-ink-700 mb-1">Role</label>
            <select
              value={form.role}
              onChange={(e) => setForm({ ...form, role: e.target.value })}
              className="input"
            >
              {ROLES.map((r) => (
                <option key={r.value} value={r.value}>
                  {r.label}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium text-ink-700 mb-1">Department</label>
            <input
              type="text"
              value={form.department}
              onChange={(e) => setForm({ ...form, department: e.target.value })}
              className="input"
              placeholder="Optional"
            />
          </div>

          <label className="flex items-center gap-2 text-sm text-ink-700 cursor-pointer">
            <input
              type="checkbox"
              checked={form.is_active}
              onChange={(e) => setForm({ ...form, is_active: e.target.checked })}
              className="w-4 h-4 rounded border-cream-300 text-violet-500 focus:ring-violet-500"
            />
            Active
          </label>

          <div className="flex gap-3 pt-2">
            <button type="button" onClick={onClose} className="btn-secondary flex-1">
              Cancel
            </button>
            <button type="submit" disabled={saving} className="btn-primary flex-1">
              {saving ? (
                <Loader2 size={16} className="animate-spin" />
              ) : user ? (
                'Save Changes'
              ) : (
                'Create User'
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
