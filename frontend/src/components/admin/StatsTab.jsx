import { useEffect } from 'react';
import { useAdminStore } from '../../store/adminStore';
import {
  FileText,
  Users,
  MessageSquare,
  TrendingUp,
  AlertTriangle,
  Loader2,
} from 'lucide-react';

export default function StatsTab() {
  const {
    stats,
    trendingTopics,
    knowledgeGaps,
    loadStats,
    loadTrendingTopics,
    loadKnowledgeGaps,
  } = useAdminStore();

  useEffect(() => {
    loadStats();
    loadTrendingTopics();
    loadKnowledgeGaps();
  }, [loadStats, loadTrendingTopics, loadKnowledgeGaps]);

  if (!stats) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 size={24} className="text-violet-500 animate-spin" />
      </div>
    );
  }

  return (
    <div className="p-6 space-y-8 max-w-5xl">
      {/* Stat cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard
          icon={FileText}
          label="Documents"
          value={stats.total_documents ?? 0}
          color="violet"
        />
        <StatCard
          icon={Users}
          label="Users"
          value={stats.total_users ?? 0}
          color="forest"
        />
        <StatCard
          icon={MessageSquare}
          label="Queries"
          value={stats.total_queries ?? 0}
          color="sand"
        />
        <StatCard
          icon={TrendingUp}
          label="Conversations"
          value={stats.total_conversations ?? 0}
          color="terra"
        />
      </div>

      {/* Collection breakdown */}
      {stats.documents_by_collection && (
        <div className="card p-5">
          <h3 className="text-sm font-semibold text-ink-900 mb-4">Documents by Collection</h3>
          <div className="space-y-3">
            {Object.entries(stats.documents_by_collection).map(([name, count]) => {
              const total = stats.total_documents || 1;
              const pct = Math.round((count / total) * 100);
              return (
                <div key={name}>
                  <div className="flex items-center justify-between text-xs mb-1">
                    <span className="text-ink-700 capitalize">{name}</span>
                    <span className="text-sand-500">{count} ({pct}%)</span>
                  </div>
                  <div className="h-2 bg-cream-100 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-violet-500 rounded-full transition-all"
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      <div className="grid md:grid-cols-2 gap-6">
        {/* Trending Topics */}
        <div className="card p-5">
          <div className="flex items-center gap-2 mb-4">
            <TrendingUp size={16} className="text-violet-500" />
            <h3 className="text-sm font-semibold text-ink-900">Trending Topics (7 days)</h3>
          </div>
          {trendingTopics.length === 0 ? (
            <p className="text-xs text-sand-400 py-4 text-center">No data yet</p>
          ) : (
            <div className="space-y-2">
              {trendingTopics.map((topic, idx) => (
                <div
                  key={idx}
                  className="flex items-center gap-3 py-2 px-3 rounded-lg bg-cream-50"
                >
                  <span className="text-[10px] text-sand-400 w-4 text-right">
                    #{idx + 1}
                  </span>
                  <span className="text-sm text-ink-700 flex-1 truncate">
                    {topic.topic || topic.query}
                  </span>
                  <span className="text-xs text-sand-500">
                    {topic.count} queries
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Knowledge Gaps */}
        <div className="card p-5">
          <div className="flex items-center gap-2 mb-4">
            <AlertTriangle size={16} className="text-terra-500" />
            <h3 className="text-sm font-semibold text-ink-900">Knowledge Gaps</h3>
          </div>
          {knowledgeGaps.length === 0 ? (
            <p className="text-xs text-sand-400 py-4 text-center">
              No gaps detected — great coverage!
            </p>
          ) : (
            <div className="space-y-2">
              {knowledgeGaps.map((gap, idx) => (
                <div
                  key={idx}
                  className="flex items-start gap-3 py-2 px-3 rounded-lg bg-terra-500/5 border border-terra-500/10"
                >
                  <AlertTriangle size={14} className="text-terra-500 mt-0.5 flex-shrink-0" />
                  <div>
                    <p className="text-sm text-ink-700">{gap.query || gap.topic}</p>
                    <p className="text-[10px] text-sand-400 mt-0.5">
                      {gap.count} unanswered queries
                    </p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function StatCard({ icon: Icon, label, value, color }) {
  const colorMap = {
    violet: { icon: 'text-violet-500', card: 'stat-violet', gradient: 'from-violet-500 to-violet-400' },
    forest: { icon: 'text-forest-500', card: 'stat-forest', gradient: 'from-forest-500 to-forest-400' },
    sand: { icon: 'text-amber-800', card: 'stat-amber', gradient: 'from-amber-800 to-amber-700' },
    terra: { icon: 'text-terra-500', card: 'stat-terra', gradient: 'from-terra-500 to-terra-600' },
  };

  const colors = colorMap[color] || colorMap.violet;

  return (
    <div className={`rounded-2xl border p-5 shadow-warm-sm hover:shadow-warm transition-all duration-200 ${colors.card}`}>
      <div className={`w-10 h-10 rounded-xl flex items-center justify-center mb-3 bg-white/80`}>
        <Icon size={20} className={colors.icon} />
      </div>
      <p className="text-2xl font-bold text-ink-900">{value}</p>
      <p className="text-xs text-ink-600 mt-0.5">{label}</p>
    </div>
  );
}
