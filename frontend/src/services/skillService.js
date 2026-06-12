import api from './api';

/**
 * Skill File & Sync API (/api/skills/*) — admin only.
 * Skill files (human-intent body + corpus-derived fact sections), version history,
 * dependencies, and Skill-Sync change proposals (the diff-review surface).
 */

// ── Skill files ─────────────────────────────────────────────
export async function listSkills() {
  const { data } = await api.get('/api/skills');
  return data; // [{id, name, description, kind, current_version, is_archived, fact_sections, metadata}]
}

export async function getSkill(skillId) {
  const { data } = await api.get(`/api/skills/${skillId}`);
  return data; // + body, versions[], dependencies[]
}

export async function createSkill(body) {
  // body: {name, description, kind, body, metadata} OR {markdown}
  const { data } = await api.post('/api/skills', body);
  return data;
}

export async function rollbackSkill(skillId, versionNo) {
  const { data } = await api.post(`/api/skills/${skillId}/rollback`, { version_no: versionNo });
  return data;
}

export async function declareDependency(skillId, { depType, depRef, factSection = null }) {
  const { data } = await api.post(`/api/skills/${skillId}/dependencies`, {
    dep_type: depType,
    dep_ref: depRef,
    fact_section: factSection,
  });
  return data;
}

// ── Skill-Sync proposals (diff review) ──────────────────────
export async function listProposals(status = 'pending') {
  const { data } = await api.get('/api/skills/proposals', { params: { status } });
  return data; // [{id, skill_id, fact_section, old_content, new_content, trigger_document_id, trigger_summary, confidence, status, created_at}]
}

export async function approveProposal(proposalId) {
  const { data } = await api.post(`/api/skills/proposals/${proposalId}/approve`);
  return data; // {status, skill}
}

export async function rejectProposal(proposalId) {
  const { data } = await api.post(`/api/skills/proposals/${proposalId}/reject`);
  return data; // {status, proposal_id}
}
