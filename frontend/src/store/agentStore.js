import { create } from 'zustand';
import * as agentService from '../services/agentService';

// A fresh assistant turn — the live scaffold the SSE events fill in.
const newAssistantTurn = () => ({
  id: `temp-assistant-${Date.now()}`,
  role: 'assistant',
  content: '',
  threadId: null,      // the durable run handle (run_started) — resume/reconnect key
  plan: [],            // [{id, label, status}]
  // The CoT timeline — reasoning, tool activity, and streamed thinking deltas
  // interleaved in arrival order: [{kind:'thinking'|'reasoning'|'tool', ...}]
  trace: [],
  citations: [],
  verification: null,  // {outcome, corrected_answer, explanation}
  approval: null,      // single-action gate (approval_required)
  batch: null,         // multi-action gate (batch_approval_required): {items:[…]}
  question: null,      // agent's question (question event): {text, context, status}
  skills: [],          // loaded playbooks (skill_loaded): [{name, version}]
  proposedAction: null,
  intent: null,
  grounded: null,
  attachments: [],
  created_at: new Date().toISOString(),
});

// Map a terminal action status onto the plan's awaiting-approval step.
const PLAN_FOR = { executed: 'done', rejected: 'rejected', failed: 'failed', blocked: 'failed' };

// LocalStorage key for the in-flight run (Tier 2 reconnect).
const LIVE_RUN_KEY = 'deepquery.agent.liveRun';
const rememberLiveRun = (threadId, conversationId) => {
  try {
    if (threadId) localStorage.setItem(LIVE_RUN_KEY, JSON.stringify({ threadId, conversationId }));
  } catch { /* storage may be unavailable */ }
};
const forgetLiveRun = () => {
  try { localStorage.removeItem(LIVE_RUN_KEY); } catch { /* ignore */ }
};
export const peekLiveRun = () => {
  try { return JSON.parse(localStorage.getItem(LIVE_RUN_KEY) || 'null'); } catch { return null; }
};

export const useAgentStore = create((set, get) => {
  // Patch one turn (by id) in place and commit.
  const patchTurn = (turnId, mutate) => {
    set((s) => ({
      turns: s.turns.map((t) => {
        if (t.id !== turnId) return t;
        const next = { ...t };
        mutate(next);
        return next;
      }),
    }));
  };

  // The single event applier, shared by /run, /resume, and /events. It mutates the
  // assistant turn identified by `turnId` so a resumed continuation streams into the
  // same message that's awaiting approval/answer.
  const applyEvent = (turnId, event) => {
    switch (event.type) {
      case 'run_started':
        patchTurn(turnId, (t) => { t.threadId = event.thread_id || t.threadId; });
        if (event.conversation_id) set({ activeConversationId: event.conversation_id });
        rememberLiveRun(event.thread_id, event.conversation_id || get().activeConversationId);
        break;

      case 'plan':
        patchTurn(turnId, (t) => { t.plan = event.steps || []; });
        break;

      case 'step_status':
        patchTurn(turnId, (t) => {
          t.plan = t.plan.map((s) => (s.id === event.id ? { ...s, status: event.status } : s));
        });
        break;

      case 'thinking':
        patchTurn(turnId, (t) => {
          const last = t.trace[t.trace.length - 1];
          if (last && last.kind === 'thinking') {
            // Coalesce consecutive CoT deltas into one block.
            t.trace = [...t.trace.slice(0, -1), { ...last, content: last.content + (event.content || '') }];
          } else {
            t.trace = [...t.trace, { kind: 'thinking', content: event.content || '' }];
          }
        });
        break;

      case 'reasoning':
        patchTurn(turnId, (t) => { t.trace = [...t.trace, { kind: 'reasoning', text: event.text }]; });
        break;

      case 'tool_activity':
        patchTurn(turnId, (t) => {
          t.trace = [...t.trace, { kind: 'tool', tool: event.tool, detail: event.detail, status: event.status }];
        });
        break;

      case 'citations':
        patchTurn(turnId, (t) => { t.citations = event.citations || event.content || []; });
        break;

      case 'answer_token':
        patchTurn(turnId, (t) => { t.content += event.content || ''; });
        break;

      case 'verification_result':
        patchTurn(turnId, (t) => {
          t.verification = {
            outcome: event.outcome,
            corrected_answer: event.corrected_answer,
            explanation: event.explanation,
          };
          if (event.outcome === 'CORRECTED' && event.corrected_answer) {
            t.content = event.corrected_answer;
          }
        });
        break;

      case 'skill_loaded':
        patchTurn(turnId, (t) => {
          if (!t.skills.some((sk) => sk.name === event.name)) {
            t.skills = [...t.skills, { name: event.name, version: event.version }];
          }
        });
        break;

      case 'approval_required':
        // Single-action gate. The run parks here; resume on the same thread_id.
        patchTurn(turnId, (t) => {
          if (event.thread_id) t.threadId = event.thread_id;
          t.approval = {
            thread_id: event.thread_id,
            pending_id: event.pending_id,
            connector: event.connector,
            capability: event.capability,
            preview: event.preview,
            reasoning: event.reasoning,
            summary: event.summary || '',
            target: event.target || '',
            sources: event.sources || [],
            regated: !!event.regated,
            status: 'pending',
          };
        });
        break;

      case 'batch_approval_required':
        // Multi-action gate (R6). One approval covers a per-action toggle list.
        patchTurn(turnId, (t) => {
          if (event.thread_id) t.threadId = event.thread_id;
          t.batch = {
            thread_id: event.thread_id,
            status: 'pending',
            items: (event.batch || []).map((a) => ({
              pending_id: a.pending_id,
              connector: a.connector,
              capability: a.capability,
              preview: a.preview,
              summary: a.summary || '',
              target: a.target || '',
              reasoning: a.reasoning || '',
              preview_status: a.preview_status || 'resolved',
              sources: a.sources || [],
              decision: 'approve', // default-selected; user can deselect
              status: 'pending',
            })),
          };
        });
        break;

      case 'question':
        // The agent is blocked and asks the user (R7). Inline answer input.
        patchTurn(turnId, (t) => {
          if (event.thread_id) t.threadId = event.thread_id;
          t.question = { thread_id: event.thread_id, text: event.text, context: event.context || '', status: 'pending' };
        });
        break;

      case 'action_result':
        // Post-resume report on an executed/rejected/failed/blocked action. The grounded
        // message also streams as answer_token, so we use this only to set status.
        patchTurn(turnId, (t) => {
          if (t.approval && (t.approval.pending_id === event.pending_id || t.threadId === event.thread_id)) {
            const planStatus = PLAN_FOR[event.status];
            if (planStatus) {
              t.plan = t.plan.map((s) => (s.status === 'awaiting-approval' ? { ...s, status: planStatus } : s));
            }
            t.approval = { ...t.approval, status: event.status, error: event.error };
          }
          if (t.batch) {
            t.batch = {
              ...t.batch,
              items: t.batch.items.map((it) =>
                it.pending_id === event.pending_id ? { ...it, status: event.status, error: event.error } : it
              ),
            };
          }
        });
        break;

      case 'done':
        patchTurn(turnId, (t) => {
          if (event.answer && !t.content) t.content = event.answer;
          if (event.intent) t.intent = event.intent;
          if (event.citations?.length) t.citations = event.citations;
          if (event.verification) t.verification = event.verification;
          if (event.proposed_action) t.proposedAction = event.proposed_action;
          if (event.grounded != null) t.grounded = event.grounded;
        });
        if (event.conversation_id) set({ activeConversationId: event.conversation_id });
        // paused → the run is parked at a gate/question; the run is still live server-side.
        if (!event.paused) forgetLiveRun();
        break;

      case 'error':
        patchTurn(turnId, (t) => {
          t.isError = true;
          if (!t.content) t.content = `Something went wrong: ${event.message}`;
        });
        break;

      default:
        break;
    }
  };

  return {
    // State
    conversations: [],
    activeConversationId: null,
    turns: [],
    isStreaming: false,
    isStopping: false,
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
          // rejected/failed); otherwise it's still pending and re-opens the gate.
          approval: t.proposed_action?.pending_id
            ? {
                thread_id: t.proposed_action.thread_id,
                pending_id: t.proposed_action.pending_id,
                connector: t.proposed_action.connector,
                capability: t.proposed_action.capability,
                preview: t.proposed_action.preview,
                reasoning: t.proposed_action.reasoning,
                summary: t.proposed_action.summary || '',
                target: t.proposed_action.target || '',
                status: t.proposed_action.resolved_status || 'pending',
                ...(t.proposed_action.resolved_error ? { error: t.proposed_action.resolved_error } : {}),
              }
            : null,
          threadId: t.proposed_action?.thread_id || null,
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
      forgetLiveRun();
      set({ activeConversationId: null, turns: [], isStreaming: false, isStopping: false, streamController: null });
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

      const controller = agentService.runAgent(
        { query, conversationId: activeConversationId, attachmentIds },
        (event) => applyEvent(assistantTurn.id, event),
        () => {
          set({ isStreaming: false, isStopping: false, streamController: null });
          get().loadConversations();
        },
        (err) => {
          patchTurn(assistantTurn.id, (t) => {
            t.isError = true;
            if (!t.content) t.content = `Something went wrong: ${err.message}`;
          });
          set({ isStreaming: false, isStopping: false, streamController: null });
        }
      );

      set({ streamController: controller });
    },

    // Stop the run. For a durable controller run, ask it to wrap up gracefully
    // (cancel_run) and let the conclusion stream in — partial work persists. For a
    // non-durable run (no thread), just abort the SSE (backend cancels, turn unsaved).
    cancelRun: () => {
      const { streamController, turns } = get();
      const last = turns[turns.length - 1];
      const threadId = last?.role === 'assistant' ? last.threadId : null;
      if (threadId) {
        agentService.interjectThread(threadId, 'stop', 'cancel_run').catch(() => {});
        set({ isStopping: true }); // keep streaming until the run wraps up on its own
        return;
      }
      if (streamController) streamController.abort();
      forgetLiveRun();
      set({ isStreaming: false, streamController: null });
    },

    // ── Streaming resume (shared by approve/reject, batch, and answer) ──
    // Continues the paused run on its thread and streams the continuation into the
    // same assistant turn. Falls back to the legacy JSON endpoints when the gate
    // carries no thread_id (the non-durable backend).
    _resume: (turnId, threadId, body) => {
      const { streamController } = get();
      if (streamController) streamController.abort();
      set({ isStreaming: true });
      const controller = agentService.resumeThread(
        threadId,
        body,
        (event) => applyEvent(turnId, event),
        () => {
          set({ isStreaming: false, streamController: null });
          get().loadConversations();
        },
        (err) => {
          patchTurn(turnId, (t) => {
            if (t.approval && t.approval.status === 'approving') {
              t.approval = { ...t.approval, status: 'failed', error: err.message };
            }
          });
          set({ isStreaming: false, streamController: null });
        }
      );
      set({ streamController: controller });
    },

    resolveApproval: async (pendingId, decision) => {
      const turn = get().turns.find((t) => t.approval?.pending_id === pendingId);
      if (!turn) return;
      const threadId = turn.threadId || turn.approval?.thread_id;

      // Optimistic: show the gate working immediately.
      patchTurn(turn.id, (t) => { t.approval = { ...t.approval, status: 'approving' }; });

      if (threadId) {
        // Durable run → streaming resume (unlocks the grounded report + reconnect).
        get()._resume(turn.id, threadId, { decision });
        return;
      }

      // Legacy non-durable fallback: one-shot JSON, append the report as a new turn.
      try {
        const result =
          decision === 'approve'
            ? await agentService.approveAction(pendingId)
            : await agentService.rejectAction(pendingId);
        const status = result.status || (decision === 'approve' ? 'executed' : 'rejected');
        patchTurn(turn.id, (t) => {
          const planStatus = PLAN_FOR[status];
          if (planStatus) {
            t.plan = t.plan.map((s) => (s.status === 'awaiting-approval' ? { ...s, status: planStatus } : s));
          }
          t.approval = { ...t.approval, status, error: result.error };
        });
        if (result.message) {
          set((s) => ({
            turns: [...s.turns, { ...newAssistantTurn(), id: `action-msg-${pendingId}`, content: result.message }],
          }));
        }
        return result;
      } catch (err) {
        patchTurn(turn.id, (t) => { t.approval = { ...t.approval, status: 'failed', error: err.message }; });
        throw err;
      }
    },

    // Batch gate (R6): resume once with every per-action decision.
    resolveBatch: (threadId, batchDecisions) => {
      const turn = get().turns.find((t) => t.threadId === threadId && t.batch);
      if (!turn) return;
      patchTurn(turn.id, (t) => {
        t.batch = {
          ...t.batch,
          status: 'approving',
          items: t.batch.items.map((it) => ({ ...it, status: batchDecisions[it.pending_id] === 'reject' ? 'rejected' : 'approving' })),
        };
      });
      get()._resume(turn.id, threadId, { batch_decisions: batchDecisions });
    },

    // Question gate (R7): resume with the user's answer.
    answerQuestion: (threadId, answer) => {
      const turn = get().turns.find((t) => t.threadId === threadId && t.question);
      if (!turn) return;
      patchTurn(turn.id, (t) => { t.question = { ...t.question, status: 'answered', answer }; });
      get()._resume(turn.id, threadId, { answer });
    },

    // Mid-flight steering (R7): a note to a running controller run.
    interject: async (message, mode = 'augment') => {
      const last = get().turns[get().turns.length - 1];
      const threadId = last?.role === 'assistant' ? last.threadId : null;
      if (!threadId) return;
      try {
        await agentService.interjectThread(threadId, message, mode);
      } catch { /* best-effort */ }
    },

    // ── Tier 2: reattach to an in-flight run after a reload/refocus ──
    // Reads the persisted live-run handle, repaints from the one-GET snapshot, then
    // subscribes to the live event feed from where we left off (replay-then-live).
    reattachLiveRun: async () => {
      // Already have a live feed in this tab (e.g. we just started the run) — nothing to do.
      if (get().streamController) return;
      const live = peekLiveRun();
      if (!live?.threadId) return;
      // Only reattach within the conversation we're currently viewing.
      if (live.conversationId && live.conversationId !== get().activeConversationId) return;

      let snap;
      try {
        snap = await agentService.getThreadState(live.threadId);
      } catch {
        forgetLiveRun(); // 404/expired/410 — the run is gone
        return;
      }
      const status = snap.run_status;
      if (status === 'done' || status === 'error') {
        // Terminal: the assistant turn is already persisted; a normal history load shows it.
        forgetLiveRun();
        return;
      }

      // A paused single-action run persists its proposal turn, so setActiveConversation
      // already rehydrated the gate (+ thread_id) from the DB — reuse that turn rather
      // than painting a duplicate. Running runs and batch/question pauses aren't in the
      // DB yet, so we build the live turn from the snapshot.
      const existing = get().turns.find((t) => t.role === 'assistant' && t.threadId === live.threadId);

      // Build a live assistant turn from the snapshot (the in-flight turn isn't in the DB yet).
      const pa = snap.pending_approval;
      const isBatch = !!(pa && pa.batch);
      const turn = {
        ...newAssistantTurn(),
        id: `live-${live.threadId}`,
        threadId: live.threadId,
        plan: snap.plan || [],
        trace: (snap.trace || []).filter((e) => e.kind !== 'skill'),
        content: snap.answer || '',
        citations: snap.citations || [],
        verification: snap.verification?.outcome ? snap.verification : null,
        intent: snap.intent,
        grounded: snap.grounded,
        skills: (snap.trace || []).filter((e) => e.kind === 'skill').map((e) => ({ name: e.name, version: e.version })),
        approval: pa && !isBatch ? {
          thread_id: snap.thread_id, pending_id: pa.pending_id, connector: pa.connector,
          capability: pa.capability, preview: pa.preview, reasoning: pa.reasoning,
          summary: pa.summary || '', target: pa.target || '', sources: pa.sources || [],
          regated: !!pa.regated, status: 'pending',
        } : null,
        batch: isBatch ? {
          thread_id: snap.thread_id, status: 'pending',
          items: pa.batch.map((a) => ({
            pending_id: a.pending_id, connector: a.connector, capability: a.capability,
            preview: a.preview, summary: a.summary || '', target: a.target || '',
            reasoning: a.reasoning || '', preview_status: a.preview_status || 'resolved',
            sources: a.sources || [], decision: 'approve', status: 'pending',
          })),
        } : null,
        question: snap.pending_question ? {
          thread_id: snap.thread_id, text: snap.pending_question.text,
          context: snap.pending_question.context || '', status: 'pending',
        } : null,
      };

      // Target an existing turn (DB-rehydrated, or a prior reattach) when present;
      // otherwise add the freshly-built one.
      const turnId = existing ? existing.id : turn.id;
      if (!existing) {
        set((s) => ({ turns: [...s.turns, turn] }));
      }

      if (status === 'interrupted') {
        // The run died in a server restart — show the partial result, no live feed.
        forgetLiveRun();
        return;
      }

      // Subscribe to the live feed from the snapshot tip. For a paused run this replays
      // nothing new and returns immediately (the gate/question is already painted).
      set({ isStreaming: status === 'running' });
      const controller = agentService.subscribeThreadEvents(
        live.threadId,
        snap.last_event_id,
        (event) => applyEvent(turnId, event),
        () => {
          set({ isStreaming: false, streamController: null });
          get().loadConversations();
        },
        () => set({ isStreaming: false, streamController: null })
      );
      set({ streamController: controller });
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
  };
});
