import { useEffect, useRef, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { useAgentStore } from '../store/agentStore';
import * as agentService from '../services/agentService';
import AgentMessage from '../components/agents/AgentMessage';
import SourceDrawer from '../components/chat/SourceDrawer';
import AttachmentViewer from '../components/agents/AttachmentViewer';
import ImageLightbox from '../components/agents/ImageLightbox';
import {
  Send, StopCircle, Plus, Bot, History, MessageSquarePlus, Trash2, Sparkles, Loader2,
  FileText, Image as ImageIcon, X,
} from 'lucide-react';

export default function AgentsPage() {
  const { conversationId } = useParams();
  const navigate = useNavigate();
  const {
    turns,
    conversations,
    isStreaming,
    isLoadingTurns,
    sendQuery,
    cancelRun,
    setActiveConversation,
    startNewConversation,
    loadConversations,
    deleteConversation,
    resolveApproval,
    activeConversationId,
  } = useAgentStore();

  const [input, setInput] = useState('');
  const [selectedSource, setSelectedSourceRaw] = useState(null);
  const [showHistory, setShowHistory] = useState(false);
  const [attachments, setAttachments] = useState([]); // {key, filename, kind, id, status}
  const [viewing, setViewing] = useState(null);        // {id, filename, kind} being viewed
  const bottomRef = useRef(null);
  const inputRef = useRef(null);
  const fileInputRef = useRef(null);

  // Source drawer and attachment viewer are mutually exclusive (one side panel).
  const setSelectedSource = (s) => { setViewing(null); setSelectedSourceRaw(s); };

  useEffect(() => {
    loadConversations();
  }, [loadConversations]);

  useEffect(() => {
    if (conversationId) {
      setActiveConversation(conversationId);
    } else {
      startNewConversation();
    }
  }, [conversationId, setActiveConversation, startNewConversation]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [turns]);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  // Follow the conversation id the backend assigns on the first turn.
  useEffect(() => {
    if (activeConversationId && activeConversationId !== conversationId) {
      navigate(`/agents/${activeConversationId}`, { replace: true });
    }
  }, [activeConversationId]); // eslint-disable-line react-hooks/exhaustive-deps

  const uploading = attachments.some((a) => a.status === 'uploading');

  const handleSubmit = (e) => {
    e.preventDefault();
    const query = input.trim();
    if (!query || isStreaming || uploading) return;
    const ready = attachments.filter((a) => a.status === 'ready');
    setInput('');
    setAttachments([]);
    sendQuery(query, ready);
  };

  const onPickFiles = (e) => {
    const files = Array.from(e.target.files || []);
    e.target.value = ''; // allow re-picking the same file
    files.forEach(addFile);
  };

  const addFile = async (file) => {
    const key = `${file.name}-${Date.now()}-${Math.random()}`;
    setAttachments((prev) => [...prev, { key, filename: file.name, status: 'uploading' }]);
    try {
      const res = await agentService.uploadAttachment(file, activeConversationId);
      setAttachments((prev) =>
        prev.map((a) => (a.key === key ? { ...a, id: res.id, kind: res.kind, status: 'ready' } : a))
      );
    } catch {
      setAttachments((prev) => prev.map((a) => (a.key === key ? { ...a, status: 'error' } : a)));
    }
  };

  const removeAttachment = (key) =>
    setAttachments((prev) => prev.filter((a) => a.key !== key));

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  const handleNew = () => {
    startNewConversation();
    navigate('/agents');
    setShowHistory(false);
    inputRef.current?.focus();
  };

  // Open an attachment: images in a lightbox, documents in the side panel.
  // (Citation-only attachments have no id and aren't openable.)
  const handleAttachmentClick = (a) => {
    if (!a?.id) return;
    if (a.kind === 'image') setViewing({ ...a });
    else { setSelectedSourceRaw(null); setViewing({ ...a }); }
  };

  const isEmpty = turns.length === 0 && !isLoadingTurns;

  return (
    <div className="flex h-full">
      {/* min-w-0 lets this column shrink so a wide element (e.g. a table) can't
          push the source drawer off-screen. */}
      <div className="flex-1 min-w-0 flex flex-col h-full">
        {/* Header */}
        <div className="flex items-center justify-between px-4 md:px-8 h-14 border-b border-cream-200 flex-shrink-0 relative">
          <div className="flex items-center gap-2">
            <Bot size={18} className="text-amber-900" />
            <h2 className="font-semibold text-ink-900 text-sm">Agents</h2>
          </div>
          <div className="flex items-center gap-1.5">
            <button onClick={handleNew} className="btn-ghost !py-1.5 !px-2.5 text-xs" title="New agent conversation">
              <MessageSquarePlus size={15} /> New
            </button>
            <button
              onClick={() => setShowHistory((v) => !v)}
              className="btn-ghost !py-1.5 !px-2.5 text-xs"
              title="Conversation history"
            >
              <History size={15} /> History
            </button>

            {/* History dropdown */}
            {showHistory && (
              <div className="absolute right-4 top-full mt-1 z-40 w-72 max-h-96 overflow-y-auto py-1.5
                              bg-white rounded-xl border border-cream-200 shadow-warm-lg animate-fade-in">
                {conversations.length === 0 ? (
                  <p className="px-3 py-3 text-xs text-ink-600">No agent conversations yet</p>
                ) : (
                  conversations.map((conv) => (
                    <div key={conv.id} className="group flex items-center hover:bg-cream-50 transition-colors">
                      <button
                        onClick={() => { navigate(`/agents/${conv.id}`); setShowHistory(false); }}
                        className={`flex-1 min-w-0 text-left px-3 py-2 text-xs truncate
                          ${conv.id === activeConversationId ? 'text-amber-900 font-medium' : 'text-ink-700'}`}
                      >
                        {conv.title || 'Untitled'}
                      </button>
                      <button
                        onClick={() => deleteConversation(conv.id)}
                        className="flex-shrink-0 p-1.5 mr-1 rounded-md text-ink-600 opacity-0 group-hover:opacity-100 hover:bg-terra-500/10 hover:text-terra-500 transition-all"
                        title="Delete"
                      >
                        <Trash2 size={13} />
                      </button>
                    </div>
                  ))
                )}
              </div>
            )}
          </div>
        </div>

        {/* Thread */}
        <div className="flex-1 overflow-y-auto px-4 md:px-8 py-6">
          <AnimatePresence mode="wait">
            {isLoadingTurns ? (
              <motion.div
                key="loading"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="flex items-center justify-center h-full"
              >
                <Loader2 size={22} className="text-violet-500 animate-spin" />
              </motion.div>
            ) : isEmpty ? (
              <motion.div key="empty" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
                <EmptyState onSuggestionClick={(q) => sendQuery(q)} />
              </motion.div>
            ) : (
              <motion.div
                key="turns"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="max-w-3xl mx-auto space-y-6"
              >
                {turns.map((turn, idx) => (
                  <AgentMessage
                    key={turn.id || idx}
                    turn={turn}
                    isStreaming={isStreaming && idx === turns.length - 1 && turn.role === 'assistant'}
                    onDocumentClick={setSelectedSource}
                    onAttachmentClick={handleAttachmentClick}
                    onResolveApproval={resolveApproval}
                  />
                ))}
                <div ref={bottomRef} />
              </motion.div>
            )}
          </AnimatePresence>
        </div>

        {/* Input */}
        <div className="px-4 md:px-8 py-4 pb-5">
          <form onSubmit={handleSubmit} className="max-w-3xl mx-auto">
            {/* Pending attachment chips (detach with × before sending) */}
            {attachments.length > 0 && (
              <div className="flex flex-wrap gap-1.5 mb-2">
                {attachments.map((a) => (
                  <div
                    key={a.key}
                    className={`inline-flex items-center gap-1.5 pl-2 pr-1 py-1 rounded-lg border text-xs
                      ${a.status === 'error'
                        ? 'bg-terra-500/5 border-terra-500/30 text-terra-500'
                        : 'bg-cream-100 border-cream-200 text-ink-700'}`}
                  >
                    {a.status === 'uploading' ? (
                      <Loader2 size={12} className="animate-spin text-violet-500" />
                    ) : a.kind === 'image' ? (
                      <ImageIcon size={12} className="text-sand-600" />
                    ) : (
                      <FileText size={12} className="text-violet-500" />
                    )}
                    <span className="truncate max-w-[160px]">{a.filename}</span>
                    {a.status === 'error' && <span className="font-medium">failed</span>}
                    <button
                      type="button"
                      onClick={() => removeAttachment(a.key)}
                      className="p-0.5 rounded hover:bg-black/10 text-ink-600 transition-colors"
                      title="Remove"
                    >
                      <X size={12} />
                    </button>
                  </div>
                ))}
              </div>
            )}

            <div className="relative flex items-end gap-3 bg-cream-50 border border-cream-200/60 rounded-2xl
              shadow-[0_8px_60px_rgba(180,155,120,0.2)]
              focus-within:border-violet-400 focus-within:ring-2 focus-within:ring-violet-500/20 focus-within:shadow-[0_8px_68px_rgba(139,92,246,0.17)]
              transition-all duration-200 p-1.5">
              {/* Attach (+) */}
              <input
                ref={fileInputRef}
                type="file"
                multiple
                hidden
                onChange={onPickFiles}
                accept=".pdf,.docx,.doc,.html,.htm,.txt,.md,image/*"
              />
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                title="Add attachments"
                className="flex-shrink-0 p-2.5 rounded-xl text-ink-600 hover:text-ink-900 hover:bg-cream-100 transition-all"
              >
                <Plus size={18} />
              </button>
              <textarea
                ref={inputRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Ask the agent — it can search documents, check live sources, and propose actions…"
                rows={1}
                className="flex-1 resize-none min-h-[40px] max-h-32 py-2.5 px-1 bg-transparent
                  text-ink-900 placeholder:text-cream-400 text-sm focus:outline-none"
                style={{ height: `${Math.min(Math.max(40, input.split('\n').length * 24 + 16), 128)}px` }}
              />
              {isStreaming ? (
                <button
                  type="button"
                  onClick={cancelRun}
                  className="flex-shrink-0 p-2.5 rounded-xl bg-terra-500/10 text-terra-500 hover:bg-terra-500/20 transition-all"
                  title="Stop"
                >
                  <StopCircle size={18} />
                </button>
              ) : (
                <button
                  type="submit"
                  disabled={!input.trim() || uploading}
                  className="flex-shrink-0 p-2.5 rounded-xl bg-violet-500 text-white hover:bg-violet-600
                    disabled:opacity-30 disabled:hover:bg-violet-500 active:scale-95 transition-all duration-200"
                  title={uploading ? 'Waiting for attachments to finish uploading…' : 'Send'}
                >
                  <Send size={18} />
                </button>
              )}
            </div>
            <p className="text-[11px] text-cream-400 mt-2.5 text-center">
              The agent reasons over documents and live sources. Actions always ask for your approval first.
            </p>
          </form>
        </div>
      </div>

      {/* Source drawer (document citations) */}
      <AnimatePresence>
        {selectedSource && (
          <SourceDrawer source={selectedSource} onClose={() => setSelectedSourceRaw(null)} />
        )}
      </AnimatePresence>

      {/* Attachment document viewer (side panel) */}
      <AnimatePresence>
        {viewing && viewing.kind !== 'image' && (
          <AttachmentViewer attachment={viewing} onClose={() => setViewing(null)} />
        )}
      </AnimatePresence>

      {/* Attachment image preview (lightbox) */}
      <AnimatePresence>
        {viewing && viewing.kind === 'image' && (
          <ImageLightbox attachment={viewing} onClose={() => setViewing(null)} />
        )}
      </AnimatePresence>
    </div>
  );
}

const suggestions = [
  'Summarize our leave policy and check for any open HR tickets about it',
  'What does the latest research say about marine conservation here?',
  'Draft a short answer on admission requirements, citing the source documents',
  'Find the exam regulations and list the key deadlines',
];

function EmptyState({ onSuggestionClick }) {
  return (
    <div className="flex flex-col items-center justify-center h-full text-center">
      <motion.div
        initial={{ scale: 0.8, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        transition={{ duration: 0.5, ease: 'easeOut' }}
        className="relative mb-8"
      >
        <div className="w-20 h-20 rounded-3xl bg-gradient-to-br from-amber-900/15 to-violet-500/15 flex items-center justify-center">
          <Sparkles size={36} className="text-amber-900" />
        </div>
        <div className="absolute -inset-2 bg-amber-900/5 rounded-[28px] blur-xl -z-10" />
      </motion.div>

      <motion.h2
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.15, duration: 0.4 }}
        className="font-serif text-2xl font-bold text-ink-900 mb-2"
      >
        What should the agent work on?
      </motion.h2>
      <motion.p
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.25, duration: 0.4 }}
        className="text-ink-600 max-w-md mb-10"
      >
        The agent plans its steps, reasons over documents and live sources, and asks
        before taking any action.
      </motion.p>

      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.35, duration: 0.4 }}
        className="grid grid-cols-1 sm:grid-cols-2 gap-3 max-w-lg w-full"
      >
        {suggestions.map((text) => (
          <button
            key={text}
            onClick={() => onSuggestionClick(text)}
            className="group flex items-start gap-3 p-4 text-left bg-white rounded-2xl border border-cream-200
              shadow-warm-sm hover:shadow-warm hover:-translate-y-0.5 transition-all duration-200"
          >
            <div className="flex-shrink-0 w-8 h-8 rounded-lg bg-amber-900/10 text-amber-900 flex items-center justify-center group-hover:scale-110 transition-transform">
              <Bot size={16} />
            </div>
            <span className="text-sm text-ink-700 group-hover:text-ink-900 transition-colors leading-snug">
              {text}
            </span>
          </button>
        ))}
      </motion.div>
    </div>
  );
}
