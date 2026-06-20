import { useEffect, useState } from 'react';
import { useAuthStore } from '../../store/authStore';
import * as settingsService from '../../services/settingsService';
import { toastError, toastSuccess } from '../../store/toastStore';
import { Loader2, Lock, Check } from 'lucide-react';

export default function AccountSection() {
  const { user, loadProfile, setUser } = useAuthStore();
  const [form, setForm] = useState({ full_name: '', email: '' });
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    loadProfile();
  }, [loadProfile]);

  useEffect(() => {
    setForm({ full_name: user?.full_name || '', email: user?.email || '' });
  }, [user?.full_name, user?.email]);

  const dirty =
    form.full_name !== (user?.full_name || '') || form.email !== (user?.email || '');

  const handleSave = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      const updated = await settingsService.updateProfile({
        full_name: form.full_name,
        email: form.email,
      });
      setUser(updated);
      toastSuccess('Profile updated.', 'Account');
    } catch (err) {
      toastError(err?.response?.data?.detail || 'Failed to update profile.', 'Account');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-8 animate-fade-in">
      {/* Profile */}
      <section className="card p-6">
        <h3 className="font-semibold text-ink-900 mb-1">Profile</h3>
        <p className="text-sm text-ink-600 mb-5">
          Your account details. Username and role are managed by an administrator.
        </p>

        <form onSubmit={handleSave} className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-ink-700 mb-1">Username</label>
              <input value={user?.username || ''} disabled className="input opacity-60 cursor-not-allowed" />
            </div>
            <div>
              <label className="block text-sm font-medium text-ink-700 mb-1">Role</label>
              <input value={user?.role || ''} disabled className="input opacity-60 cursor-not-allowed capitalize" />
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-ink-700 mb-1">Full name</label>
            <input
              value={form.full_name}
              onChange={(e) => setForm({ ...form, full_name: e.target.value })}
              className="input"
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

          <div className="flex justify-end pt-1">
            <button type="submit" disabled={!dirty || saving} className="btn-primary text-sm">
              {saving ? <Loader2 size={16} className="animate-spin" /> : <Check size={16} />}
              Save changes
            </button>
          </div>
        </form>
      </section>

      <PasswordCard />
    </div>
  );
}

function PasswordCard() {
  const [form, setForm] = useState({ current: '', next: '', confirm: '' });
  const [saving, setSaving] = useState(false);

  const tooShort = form.next.length > 0 && form.next.length < 8;
  const mismatch = form.confirm.length > 0 && form.next !== form.confirm;
  const canSubmit =
    form.current && form.next.length >= 8 && form.next === form.confirm && !saving;

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!canSubmit) return;
    setSaving(true);
    try {
      await settingsService.changePassword(form.current, form.next);
      setForm({ current: '', next: '', confirm: '' });
      toastSuccess('Password changed. Other sessions were signed out.', 'Account');
    } catch (err) {
      toastError(err?.response?.data?.detail || 'Failed to change password.', 'Account');
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="card p-6">
      <div className="flex items-center gap-2 mb-1">
        <Lock size={16} className="text-ink-700" />
        <h3 className="font-semibold text-ink-900">Change password</h3>
      </div>
      <p className="text-sm text-ink-600 mb-5">
        Changing your password signs out your other active sessions.
      </p>

      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className="block text-sm font-medium text-ink-700 mb-1">Current password</label>
          <input
            type="password"
            value={form.current}
            onChange={(e) => setForm({ ...form, current: e.target.value })}
            className="input"
            autoComplete="current-password"
          />
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-ink-700 mb-1">New password</label>
            <input
              type="password"
              value={form.next}
              onChange={(e) => setForm({ ...form, next: e.target.value })}
              className={tooShort ? 'input-error' : 'input'}
              autoComplete="new-password"
            />
            {tooShort && (
              <p className="mt-1 text-xs text-terra-500">Must be at least 8 characters.</p>
            )}
          </div>
          <div>
            <label className="block text-sm font-medium text-ink-700 mb-1">Confirm</label>
            <input
              type="password"
              value={form.confirm}
              onChange={(e) => setForm({ ...form, confirm: e.target.value })}
              className={mismatch ? 'input-error' : 'input'}
              autoComplete="new-password"
            />
            {mismatch && <p className="mt-1 text-xs text-terra-500">Passwords don't match.</p>}
          </div>
        </div>
        <div className="flex justify-end pt-1">
          <button type="submit" disabled={!canSubmit} className="btn-primary text-sm">
            {saving ? <Loader2 size={16} className="animate-spin" /> : <Lock size={16} />}
            Update password
          </button>
        </div>
      </form>
    </section>
  );
}
