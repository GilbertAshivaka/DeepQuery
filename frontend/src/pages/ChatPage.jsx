import { useEffect, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';
import { useChatStore } from '../store/chatStore';
import { motion, AnimatePresence } from 'framer-motion';
import MessageBubble from '../components/chat/MessageBubble';
import SourceDrawer from '../components/chat/SourceDrawer';
import AttachmentViewer from '../components/agents/AttachmentViewer';
import ImageLightbox from '../components/agents/ImageLightbox';
import * as agentService from '../services/agentService';
import { Send, StopCircle, Sparkles, Briefcase, GraduationCap, FlaskConical, Scale,
  Plus, X, Loader2, FileText, Image as ImageIcon } from 'lucide-react';

export default function ChatPage() {
  const { conversationId } = useParams();
  const {
    messages,
    isStreaming,
    activeConversationId,
    sendMessage,
    retryLast,
    cancelStream,
    setActiveConversation,
  } = useChatStore();

  const [input, setInput] = useState('');
  const [selectedSource, setSelectedSource] = useState(null);
  const [viewing, setViewing] = useState(null);   // an attached doc/image open in a panel
  const [pendingAttachments, setPendingAttachments] = useState([]);
  const [uploading, setUploading] = useState(false);

  // Only one right-side surface at a time (source drawer vs attachment viewer).
  const openSource = (s) => { setViewing(null); setSelectedSource(s); };
  const bottomRef = useRef(null);
  const inputRef = useRef(null);
  const fileRef = useRef(null);

  const handleFiles = async (e) => {
    const files = Array.from(e.target.files || []);
    e.target.value = '';  // allow re-selecting the same file
    if (!files.length) return;
    setUploading(true);
    try {
      for (const file of files) {
        // No conversation id: AgentAttachment.conversation_id FKs the *agent* conversations
        // table, not the classical chat one. Ownership is by user; the chat links the file
        // via the message's citation refs.
        const data = await agentService.uploadAttachment(file);
        setPendingAttachments((prev) => [...prev, { id: data.id, filename: data.filename, kind: data.kind }]);
      }
    } catch (err) {
      console.error('Attachment upload failed:', err);
    } finally {
      setUploading(false);
    }
  };

  // Open an attached file in-app like the agent: documents in a right-side panel, images
  // in a lightbox. (Citation-only refs use `attachment_id`; bubble chips use `id`.)
  const openAttachment = (a) => {
    const id = a?.attachment_id || a?.id;
    if (!id) return;
    setSelectedSource(null);  // only one right-side surface at a time
    setViewing({ id, filename: a.filename, kind: a.kind || 'document' });
  };

  useEffect(() => {
    if (conversationId) {
      setActiveConversation(conversationId);
    }
  }, [conversationId, setActiveConversation]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const handleSubmit = (e) => {
    e.preventDefault();
    const query = input.trim();
    if (!query || isStreaming || uploading) return;
    setInput('');
    sendMessage(query, pendingAttachments);
    setPendingAttachments([]);
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  const isEmpty = messages.length === 0;

  return (
    <div className="flex h-full">
      {/* Main chat area */}
      <div className="flex-1 flex flex-col h-full">
        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-4 md:px-8 py-6">
          <AnimatePresence mode="wait">
            {isEmpty ? (
              <motion.div
                key="empty"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
              >
                <EmptyState onSuggestionClick={(q) => sendMessage(q)} />
              </motion.div>
            ) : (
              <motion.div
                key="messages"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="max-w-3xl mx-auto space-y-6"
              >
                {messages.map((msg, idx) => (
                  <MessageBubble
                    key={msg.id || idx}
                    message={msg}
                    isStreaming={isStreaming && idx === messages.length - 1 && msg.role === 'assistant'}
                    onSourceClick={openSource}
                    onAttachmentClick={openAttachment}
                    onRetry={idx === messages.length - 1 && !isStreaming ? retryLast : undefined}
                  />
                ))}
                <div ref={bottomRef} />
              </motion.div>
            )}
          </AnimatePresence>
        </div>

        {/* Input area */}
        <div className="px-4 md:px-8 py-4 pb-5">
          <form
            onSubmit={handleSubmit}
            className="max-w-3xl mx-auto"
          >
            {/* Pending attachment chips (uploaded, attach on next send) */}
            {pendingAttachments.length > 0 && (
              <div className="flex flex-wrap gap-1.5 mb-2">
                {pendingAttachments.map((a) => (
                  <span
                    key={a.id}
                    className="inline-flex items-center gap-1.5 pl-2 pr-1 py-1 text-[11px] rounded-lg
                               bg-cream-100 border border-cream-200 text-ink-700"
                  >
                    {a.kind === 'image' ? <ImageIcon size={11} /> : <FileText size={11} />}
                    <span className="truncate max-w-[160px]">{a.filename}</span>
                    <button
                      type="button"
                      onClick={() => setPendingAttachments((prev) => prev.filter((x) => x.id !== a.id))}
                      className="p-0.5 rounded hover:bg-cream-300/60 text-ink-500"
                      title="Remove"
                    >
                      <X size={11} />
                    </button>
                  </span>
                ))}
                {uploading && (
                  <span className="inline-flex items-center gap-1.5 px-2 py-1 text-[11px] text-ink-500">
                    <Loader2 size={11} className="animate-spin" /> Uploading…
                  </span>
                )}
              </div>
            )}
            <div className="relative flex items-end gap-3 bg-cream-50 border border-cream-200/60 rounded-2xl
              shadow-[0_8px_60px_rgba(180,155,120,0.2)]
              focus-within:border-violet-400 focus-within:ring-2 focus-within:ring-violet-500/20 focus-within:shadow-[0_8px_68px_rgba(139,92,246,0.17)]
              transition-all duration-200 p-1.5">
              <input
                ref={fileRef}
                type="file"
                multiple
                onChange={handleFiles}
                className="hidden"
                accept=".pdf,.txt,.md,.docx,.doc,.csv,.png,.jpg,.jpeg,.gif,.webp"
              />
              <button
                type="button"
                onClick={() => fileRef.current?.click()}
                disabled={isStreaming || uploading}
                className="flex-shrink-0 p-2.5 rounded-xl text-ink-500 hover:text-ink-800 hover:bg-cream-100
                  disabled:opacity-40 transition-all self-end"
                title="Add attachments"
              >
                {uploading ? <Loader2 size={18} className="animate-spin" /> : <Plus size={18} />}
              </button>
              <textarea
                ref={inputRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Ask about your knowledge base…"
                rows={1}
                className="flex-1 resize-none min-h-[40px] max-h-32 py-2.5 px-3 bg-transparent
                  text-ink-900 placeholder:text-cream-400 text-sm
                  focus:outline-none"
                style={{
                  height: `${Math.min(
                    Math.max(40, input.split('\n').length * 24 + 16),
                    128
                  )}px`,
                }}
              />
              {isStreaming ? (
                <button
                  type="button"
                  onClick={cancelStream}
                  className="flex-shrink-0 p-2.5 rounded-xl bg-terra-500/10 text-terra-500 hover:bg-terra-500/20 transition-all"
                  title="Stop generating"
                >
                  <StopCircle size={18} />
                </button>
              ) : (
                <button
                  type="submit"
                  disabled={!input.trim()}
                  className="flex-shrink-0 p-2.5 rounded-xl bg-violet-500 text-white hover:bg-violet-600
                    disabled:opacity-30 disabled:hover:bg-violet-500
                    active:scale-95 transition-all duration-200"
                  title="Send message"
                >
                  <Send size={18} />
                </button>
              )}
            </div>
            <p className="text-[11px] text-cream-400 mt-2.5 text-center">
              Deep Query uses RAG to answer from your documents. Always verify critical information.
            </p>
          </form>
        </div>
      </div>

      {/* Source Drawer (document citations) */}
      <AnimatePresence>
        {selectedSource && (
          <SourceDrawer
            source={selectedSource}
            onClose={() => setSelectedSource(null)}
          />
        )}
      </AnimatePresence>

      {/* Attached document — right-side panel (PDF inline / parsed text), like the agent */}
      <AnimatePresence>
        {viewing && viewing.kind !== 'image' && (
          <AttachmentViewer attachment={viewing} onClose={() => setViewing(null)} />
        )}
      </AnimatePresence>

      {/* Attached image — lightbox */}
      <AnimatePresence>
        {viewing && viewing.kind === 'image' && (
          <ImageLightbox attachment={viewing} onClose={() => setViewing(null)} />
        )}
      </AnimatePresence>
    </div>
  );
}

const suggestions = [
  {
    icon: Scale,
    text: 'Summarize the termination provisions in this agreement',
    color: 'text-violet-500 bg-violet-500/10',
  },
  {
    icon: FlaskConical,
    text: 'What are the key findings across these studies?',
    color: 'text-amber-800 bg-amber-900/10',
  },
  {
    icon: Briefcase,
    text: 'What risks did the latest quarterly report flag?',
    color: 'text-forest-500 bg-forest-500/10',
  },
  {
    icon: GraduationCap,
    text: 'What do the examination regulations require?',
    color: 'text-terra-500 bg-terra-500/10',
  },
];

function EmptyState({ onSuggestionClick }) {
  return (
    <div className="flex flex-col items-center justify-center h-full text-center">
      {/* Animated icon */}
      <motion.div
        initial={{ scale: 0.8, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        transition={{ duration: 0.5, ease: 'easeOut' }}
        className="relative mb-8"
      >
        <div className="w-20 h-20 rounded-3xl bg-gradient-to-br from-violet-500/20 to-amber-900/10 flex items-center justify-center">
          <Sparkles size={36} className="text-violet-500" />
        </div>
        <div className="absolute -inset-2 bg-violet-500/5 rounded-[28px] blur-xl -z-10" />
      </motion.div>

      <motion.h2
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.15, duration: 0.4 }}
        className="font-serif text-2xl font-bold text-ink-900 mb-2"
      >
        What would you like to know?
      </motion.h2>
      <motion.p
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.25, duration: 0.4 }}
        className="text-ink-600 max-w-md mb-10"
      >
        Ask questions about your academic programs, policies,
        research, or any institutional knowledge.
      </motion.p>

      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.35, duration: 0.4 }}
        className="grid grid-cols-1 sm:grid-cols-2 gap-3 max-w-lg w-full"
      >
        {suggestions.map(({ icon: Icon, text, color }) => (
          <button
            key={text}
            onClick={() => onSuggestionClick(text)}
            className="group flex items-start gap-3 p-4 text-left bg-white rounded-2xl border border-cream-200
              shadow-warm-sm hover:shadow-warm hover:-translate-y-0.5 transition-all duration-200"
          >
            <div className={`flex-shrink-0 w-8 h-8 rounded-lg ${color} flex items-center justify-center
              group-hover:scale-110 transition-transform`}>
              <Icon size={16} />
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
