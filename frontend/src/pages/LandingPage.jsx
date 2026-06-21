import { useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import {
  Brain,
  Search,
  Network,
  FileText,
  MessageSquare,
  Shield,
  ArrowRight,
  Sparkles,
} from 'lucide-react';
import { BackgroundPaths } from '../components/ui/background-paths';

const features = [
  {
    icon: Brain,
    title: 'RAG-Powered Chat',
    description:
      'Ask questions in natural language and get accurate answers grounded in your institutional documents.',
    color: 'violet',
  },
  {
    icon: Search,
    title: 'Semantic Search',
    description:
      'Go beyond keyword matching. Find documents by meaning using state-of-the-art embedding models.',
    color: 'amber',
  },
  {
    icon: Network,
    title: 'Knowledge Graphs',
    description:
      'Automatically extract entities and relationships, building a connected knowledge network.',
    color: 'forest',
  },
  {
    icon: FileText,
    title: 'Multi-Format Ingestion',
    description:
      'Upload PDFs, DOCX, HTML, and more. Documents are chunked, embedded, and indexed automatically.',
    color: 'terra',
  },
  {
    icon: MessageSquare,
    title: 'Self-Correcting AI',
    description:
      'Built-in hallucination detection and CRAG-based correction ensures trustworthy responses.',
    color: 'violet',
  },
  {
    icon: Shield,
    title: 'Admin Controls',
    description:
      'Manage users, monitor analytics, track trending topics, and identify knowledge gaps.',
    color: 'amber',
  },
];

const featureColors = {
  violet: {
    bg: 'bg-violet-500/10',
    text: 'text-violet-500',
    border: 'border-violet-500/20',
  },
  amber: {
    bg: 'bg-amber-900/10',
    text: 'text-amber-900',
    border: 'border-amber-900/20',
  },
  forest: {
    bg: 'bg-forest-500/10',
    text: 'text-forest-500',
    border: 'border-forest-500/20',
  },
  terra: {
    bg: 'bg-terra-500/10',
    text: 'text-terra-500',
    border: 'border-terra-500/20',
  },
};

const containerVariants = {
  hidden: {},
  visible: {
    transition: { staggerChildren: 0.1 },
  },
};

const itemVariants = {
  hidden: { opacity: 0, y: 24 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.5, ease: 'easeOut' } },
};

export default function LandingPage() {
  const navigate = useNavigate();

  return (
    <div className="min-h-screen bg-cream-50">
      {/* Hero section with animated background */}
      <BackgroundPaths
        title="Deep Query"
        subtitle="Semantic Knowledge Management System for High Accuracy Use Cases"
        buttonText="Get Started"
        onButtonClick={() => navigate('/login')}
      />

      {/* Features section */}
      <section className="relative py-24 px-6">
        <div className="max-w-6xl mx-auto">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, margin: '-100px' }}
            transition={{ duration: 0.6 }}
            className="text-center mb-16"
          >
            <div className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full bg-amber-900/10 text-amber-900 text-sm font-medium mb-4">
              <Sparkles size={14} />
              Powered by AI
            </div>
            <h2 className="font-serif text-4xl font-bold text-ink-900 mb-4">
              Everything you need to manage
              <br />
              institutional knowledge
            </h2>
            <p className="text-ink-600 text-lg max-w-2xl mx-auto">
              Deep Query combines retrieval-augmented generation, semantic search,
              and knowledge graphs into one powerful platform.
            </p>
          </motion.div>

          <motion.div
            variants={containerVariants}
            initial="hidden"
            whileInView="visible"
            viewport={{ once: true, margin: '-50px' }}
            className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6"
          >
            {features.map((feature) => {
              const colors = featureColors[feature.color];
              return (
                <motion.div
                  key={feature.title}
                  variants={itemVariants}
                  className={`group relative bg-white rounded-2xl border border-cream-200 p-6 
                    shadow-warm hover:shadow-warm-lg transition-all duration-300 hover:-translate-y-1`}
                >
                  <div
                    className={`w-12 h-12 rounded-xl ${colors.bg} flex items-center justify-center mb-4
                      group-hover:scale-110 transition-transform duration-300`}
                  >
                    <feature.icon size={24} className={colors.text} />
                  </div>
                  <h3 className="text-lg font-semibold text-ink-900 mb-2">
                    {feature.title}
                  </h3>
                  <p className="text-sm text-ink-600 leading-relaxed">
                    {feature.description}
                  </p>
                </motion.div>
              );
            })}
          </motion.div>
        </div>
      </section>

      {/* CTA section */}
      <section className="py-24 px-6">
        <motion.div
          initial={{ opacity: 0, scale: 0.95 }}
          whileInView={{ opacity: 1, scale: 1 }}
          viewport={{ once: true }}
          transition={{ duration: 0.6 }}
          className="max-w-3xl mx-auto text-center"
        >
          <div className="bg-gradient-to-br from-[#D9C3A8] via-[#D4A77F] to-[#DDA15E] rounded-3xl p-12 shadow-warm-xl relative overflow-hidden">
            {/* Decorative elements */}
            <div className="absolute top-0 right-0 w-64 h-64 bg-[#F2CC8F]/40 rounded-full blur-3xl -translate-y-1/2 translate-x-1/2" />
            <div className="absolute bottom-0 left-0 w-48 h-48 bg-violet-500/10 rounded-full blur-3xl translate-y-1/2 -translate-x-1/2" />

            <div className="relative z-10">
              <img
                src="/DeepQueryLogo.png"
                alt="DeepQuery"
                className="w-12 h-12 rounded-xl object-cover mx-auto mb-6"
              />
              <h2 className="font-serif text-3xl font-bold text-ink-900 mb-4">
                Ready to explore?
              </h2>
              <p className="text-ink-700 text-lg mb-8 max-w-lg mx-auto">
                Sign in to start querying your knowledge base
                with the power of AI.
              </p>
              <button
                onClick={() => navigate('/login')}
                className="inline-flex items-center gap-2 px-8 py-3.5 bg-white text-ink-900 font-semibold rounded-xl
                  hover:bg-cream-50 active:scale-[0.98] transition-all duration-200 shadow-warm-lg"
              >
                Sign In
                <ArrowRight size={18} />
              </button>
            </div>
          </div>
        </motion.div>
      </section>

      {/* Footer */}
      <footer className="border-t border-cream-200 py-8 px-6">
        <div className="max-w-6xl mx-auto flex flex-col md:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <img
              src="/DeepQueryLogo.png"
              alt="DeepQuery"
              className="w-6 h-6 rounded-lg object-cover"
            />
            <span className="text-sm font-semibold text-ink-900">DeepQuery</span>
          </div>
          <p className="text-xs text-ink-600">
            © {new Date().getFullYear()} DeepQuery · Semantic Knowledge Management Ecosystem
          </p>
        </div>
      </footer>
    </div>
  );
}
