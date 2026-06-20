import { useSettingsStore } from '../../store/settingsStore';
import Switch from '../ui/Switch';

export default function AppearanceSection() {
  const { appearance, setAppearance } = useSettingsStore();

  return (
    <div className="space-y-8 animate-fade-in">
      <section className="card p-6">
        <h3 className="font-semibold text-ink-900 mb-1">Interface</h3>
        <p className="text-sm text-ink-600 mb-5">
          Personal display preferences. Stored in this browser.
        </p>

        <div className="divide-y divide-cream-200">
          <ToggleRow
            title="Expand sidebar by default"
            description="Open the navigation sidebar when the app loads."
            checked={appearance.sidebarDefaultOpen}
            onChange={(v) => setAppearance({ sidebarDefaultOpen: v })}
          />
          <ToggleRow
            title="Expand thinking panel by default"
            description="Show the agent's reasoning panel expanded on new answers."
            checked={appearance.thinkingPanelDefaultExpanded}
            onChange={(v) => setAppearance({ thinkingPanelDefaultExpanded: v })}
          />

          <div className="flex items-center justify-between py-4">
            <div className="pr-6">
              <p className="text-sm font-medium text-ink-900">Density</p>
              <p className="text-xs text-ink-600 mt-0.5">Spacing of lists and message content.</p>
            </div>
            <div className="flex p-0.5 rounded-xl bg-cream-100 border border-cream-200">
              {['comfortable', 'compact'].map((d) => (
                <button
                  key={d}
                  onClick={() => setAppearance({ density: d })}
                  className={`px-3 py-1.5 text-xs font-medium rounded-lg capitalize transition-all
                    ${
                      appearance.density === d
                        ? 'bg-white text-ink-900 shadow-warm-sm'
                        : 'text-ink-600 hover:text-ink-900'
                    }`}
                >
                  {d}
                </button>
              ))}
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}

function ToggleRow({ title, description, checked, onChange }) {
  return (
    <div className="flex items-center justify-between py-4">
      <div className="pr-6">
        <p className="text-sm font-medium text-ink-900">{title}</p>
        <p className="text-xs text-ink-600 mt-0.5">{description}</p>
      </div>
      <Switch checked={checked} onChange={onChange} label={title} />
    </div>
  );
}
