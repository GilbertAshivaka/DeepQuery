import { create } from 'zustand';
import * as agentService from '../services/agentService';

// A fresh assistant turn — the live scaffold the SSE events fill in.
const newAssistantTurn = () => ({
  id: `temp-assistant-${Date.now()}`,
  role: 'assistant',
  content: '',
  plan: [],            // [{id, label, status}]
  // The CoT timeline — reasoning, tool activity, and streamed thinking deltas
  // interleaved in arrival order: [{kind:'thinking'|'reasoning'|'tool', ...}]
  trace: [],
  citations: [],
  verification: null,  // {outcome, corrected_answer, explanation}
  approval: null,      // approval_required payload (action runs end here)
  proposedAction: null,
  intent: null,
  grounded: null,
  attachments: [],
  created_at: new Date().toISOString(),
});

export const useAgentStore = create((set, get) => ({
  // State
  conversations: [],
  activeConversationId: null,
  turns: [],
  isStreaming: false,
  isLoadingTurns: false,
  streamController: null,

  // ── Conversation list / history (separate from chat) ──
  loadConversations: async () => {
    try {
      const data = await agentService.getConversations();
      set({ conversations: data });
    } catch {
      /* non-fatal */
    }
  },

  setActiveConversation: async (conversationId) => {
    if (!conversationId) {
      set({ activeConversationId: null, turns: [], isLoadingTurns: false });
      return;
    }
    // Already loaded in memory (e.g. the URL just updated to the id the backend
    // assigned after the first turn) — don't refetch and clobber the live
    // plan/CoT/streaming turns. This also prevents the post-send flicker.
    const current = get();
    if (conversationId === current.activeConversationId && current.turns.length > 0) {
      return;
    }
    // Genuine switch: clear immediately so the previous thread doesn't linger
    // under the new URL, and flag loading so the empty state doesn't flash.
    set({ activeConversationId: conversationId, turns: [], isLoadingTurns: true });
    try {
      const data = await agentService.getConversation(conversationId);
      // Drop a stale response if the user switched again mid-fetch.
      if (get().activeConversationId !== conversationId) return;
      // Rehydrate persisted turns, including the plan + CoT timeline.
      const loaded = (data.turns || []).map((t) => ({
        ...newAssistantTurn(),
        id: `${conversationId}-${t.created_at}`,
        role: t.role,
        content: t.content || '',
        intent: t.intent,
        citations: t.citations || [],
        plan: t.cot?.plan || [],
        trace: t.cot?.trace || [],
        grounded: t.grounded,
        verification: t.verification_status ? { outcome: t.verification_status } : null,
        proposedAction: t.proposed_action || null,
        // Rehydrate the approval gate (persisted on the turn so it survives a
        // reload). resolved_status, if present, makes it a record (executed/
        // rejected/failed); otherwise it's still pending and re-opens the modal.
        approval: t.proposed_action?.pending_id
          ? {
              pending_id: t.proposed_action.pending_id,
              connector: t.proposed_action.connector,
              capability: t.proposed_action.capability,
              preview: t.proposed_action.preview,
              reasoning: t.proposed_action.reasoning,
              status: t.proposed_action.resolved_status || 'pending',
              ...(t.proposed_action.resolved_error ? { error: t.proposed_action.resolved_error } : {}),
            }
          : null,
        attachments: t.attachments || [],
        created_at: t.created_at,
      }));
      set({ turns: loaded, isLoadingTurns: false });
    } catch {
      if (get().activeConversationId === conversationId) {
        set({ turns: [], isLoadingTurns: false });
      }
    }
  },

  startNewConversation: () => {
    const { streamController } = get();
    if (streamController) streamController.abort();
    set({ activeConversationId: null, turns: [], isStreaming: false, streamController: null });
  },

  // ── Run a query (streaming) ──
  // `attachments` = metadata objects [{id, filename, kind}] already uploaded.
  sendQuery: (query, attachments = []) => {
    const { activeConversationId, turns, streamController } = get();
    if (streamController) streamController.abort();

    const attachmentIds = attachments.map((a) => a.id).filter(Boolean);

    const userTurn = {
      id: `temp-user-${Date.now()}`,
      role: 'user',
      content: query,
      attachments: attachments.map((a) => ({ id: a.id, filename: a.filename, kind: a.kind })),
      created_at: new Date().toISOString(),
    };
    const assistantTurn = newAssistantTurn();

    set({ turns: [...turns, userTurn, assistantTurn], isStreaming: true });

    // Mutate the last (assistant) turn in place and commit.
    const patchLast = (mutate) => {
      const current = get().turns;
      const lastIdx = current.length - 1;
      if (lastIdx < 0) return;
      const updated = [...current];
      const last = { ...updated[lastIdx] };
      mutate(last);
      updated[lastIdx] = last;
      set({ turns: updated });
    };

    const controller = agentService.runAgent(
      { query, conversationId: activeConversationId, attachmentIds },
      // onEvent
      (event) => {
        switch (event.type) {
          case 'plan':
            patchLast((t) => { t.plan = event.steps || []; });
            break;
          case 'step_status':
            patchLast((t) => {
              t.plan = t.plan.map((s) =>
                s.id === event.id ? { ...s, status: event.status } : s
              );
            });
            break;
          case 'thinking':
            patchLast((t) => {
              const last = t.trace[t.trace.length - 1];
              if (last && last.kind === 'thinking') {
                // Coalesce consecutive CoT deltas into one block.
                t.trace = [
                  ...t.trace.slice(0, -1),
                  { ...last, content: last.content + (event.content || '') },
                ];
              } else {
                t.trace = [...t.trace, { kind: 'thinking', content: event.content || '' }];
              }
            });
            break;
          case 'reasoning':
            patchLast((t) => { t.trace = [...t.trace, { kind: 'reasoning', text: event.text }]; });
            break;
          case 'tool_activity':
            patchLast((t) => {
              t.trace = [
                ...t.trace,
                { kind: 'tool', tool: event.tool, detail: event.detail, status: event.status },
              ];
            });
            break;
          case 'citations':
            patchLast((t) => { t.citations = event.citations || event.content || []; });
            break;
          case 'answer_token':
            patchLast((t) => { t.content += event.content || ''; });
            break;
          case 'verification_result':
            patchLast((t) => {
              t.verification = {
                outcome: event.outcome,
                corrected_answer: event.corrected_answer,
                explanation: event.explanation,
              };
              // A CORRECTED answer is the authoritative one.
              if (event.outcome === 'CORRECTED' && event.corrected_answer) {
                t.content = event.corrected_answer;
              }
            });
            break;
          case 'approval_required':
            // The run stream ends here; resume via approve/reject endpoints.
            patchLast((t) => {
              t.approval = {
                pending_id: event.pending_id,
                connector: event.connector,
                capability: event.capability,
                preview: event.preview,
                reasoning: event.reasoning,
                sources: event.sources || [],
                status: 'pending',
              };
            });
            set({ isStreaming: false });
            break;
          case 'done':
            patchLast((t) => {
              if (event.answer) t.content = event.answer;
              if (event.intent) t.intent = event.intent;
              if (event.citations) t.citations = event.citations;
              if (event.verification) t.verification = event.verification;
              if (event.proposed_action) t.proposedAction = event.proposed_action;
              t.grounded = event.grounded;
            });
            if (event.conversation_id) set({ activeConversationId: event.conversation_id });
            break;
          case 'error':
            patchLast((t) => {
              t.isError = true;
              if (!t.content) t.content = `Something went wrong: ${event.message}`;
            });
            break;
          default:
            break;
        }
      },
      // onDone
      () => {
        set({ isStreaming: false, streamController: null });
        get().loadConversations();
      },
      // onError
      (err) => {
        patchLast((t) => {
          t.isError = true;
          if (!t.content) t.content = `Something went wrong: ${err.message}`;
        });
        set({ isStreaming: false, streamController: null });
      }
    );

    set({ streamController: controller });
  },

  // Stop the run (abort the SSE fetch — backend cancels, user turn kept).
  cancelRun: () => {
    const { streamController } = get();
    if (streamController) streamController.abort();
    set({ isStreaming: false, streamController: null });
  },

  // ── Approval resolution (resume after approval_required) ──
  resolveApproval: async (pendingId, decision) => {
    // Map a terminal approval outcome onto the plan's awaiting-approval step so the
    // checklist follows the action (executed → done, etc.).
    const PLAN_FOR = { executed: 'done', rejected: 'rejected', failed: 'failed' };
    const setStatus = (status, extra = {}) => {
      set((s) => ({
        turns: s.turns.map((t) => {
          if (t.approval?.pending_id !== pendingId) return t;
          const planStatus = PLAN_FOR[status];
          const plan = planStatus
            ? t.plan.map((step) =>
                step.status === 'awaiting-approval' ? { ...step, status: planStatus } : step
              )
            : t.plan;
          return { ...t, plan, approval: { ...t.approval, status, ...extra } };
        }),
      }));
    };
    setStatus('approving');
    try {
      const result =
        decision === 'approve'
          ? await agentService.approveAction(pendingId)
          : await agentService.rejectAction(pendingId);
      setStatus(result.status || (decision === 'approve' ? 'executed' : 'rejected'), {
        result: result.result,
        error: result.error,
      });
      // The agent reports back after an executed action — append its follow-up turn
      // (also persisted server-side, so a reload shows it too).
      if (result.message) {
        set((s) => ({
          turns: [
            ...s.turns,
            { ...newAssistantTurn(), id: `action-msg-${pendingId}`, content: result.message },
          ],
        }));
      }
      return result;
    } catch (err) {
      setStatus('failed', { error: err.message });
      throw err;
    }
  },

  deleteConversation: async (conversationId) => {
    try {
      await agentService.deleteConversation(conversationId);
      set((s) => ({
        conversations: s.conversations.filter((c) => c.id !== conversationId),
        ...(s.activeConversationId === conversationId
          ? { activeConversationId: null, turns: [] }
          : {}),
      }));
    } catch (err) {
      console.error('Failed to delete agent conversation:', err);
    }
  },
}));
