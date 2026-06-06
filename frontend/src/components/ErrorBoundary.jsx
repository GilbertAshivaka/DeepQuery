import { Component } from 'react';
import { AlertTriangle, RotateCcw } from 'lucide-react';

/**
 * Catches render-time errors in its subtree so a single broken page shows a
 * fallback instead of unmounting the whole app (the React "white screen").
 *
 * Reset behaviour:
 *  - Navigating away resets it automatically when given key={location.pathname}.
 *  - The "Try again" button clears the error in place for transient failures.
 */
export default class ErrorBoundary extends Component {
  state = { error: null };

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    // Surface to the console so the failure isn't silent.
    console.error('Render error caught by ErrorBoundary:', error, info);
  }

  handleReset = () => this.setState({ error: null });

  render() {
    if (this.state.error) {
      return (
        <div className="h-full flex flex-col items-center justify-center gap-4 p-8 text-center bg-cream-50">
          <div className="w-12 h-12 rounded-2xl bg-terra-500/10 flex items-center justify-center">
            <AlertTriangle size={24} className="text-terra-500" />
          </div>
          <div>
            <h2 className="font-serif text-lg font-bold text-ink-900">
              Something went wrong on this page
            </h2>
            <p className="text-sm text-ink-600 mt-1 max-w-md">
              The rest of the app is still working — you can navigate away or try
              reloading this view.
            </p>
          </div>
          <pre className="max-w-lg overflow-auto text-[11px] text-terra-600 bg-terra-500/5 border border-terra-500/15 rounded-lg px-3 py-2 text-left">
            {this.state.error?.message || String(this.state.error)}
          </pre>
          <button
            onClick={this.handleReset}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-amber-800 text-white text-sm font-medium hover:bg-amber-900 transition"
          >
            <RotateCcw size={15} /> Try again
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
