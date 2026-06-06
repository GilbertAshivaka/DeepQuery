"""Manually rebuild BM25 indexes from ChromaDB data."""
import sys
sys.path.insert(0, 'backend')

from retrieval.bm25_retriever import bm25_retriever

print("Rebuilding BM25 indexes from ChromaDB...\n")

try:
    bm25_retriever.build_all_indexes()
    print("\n=== Rebuild Complete ===\n")

    # Verify the indexes are built
    print("Verifying indexes:")
    for coll_name, corpus in bm25_retriever._corpuses.items():
        doc_count = len(corpus)
        index_status = "READY" if bm25_retriever._indexes.get(coll_name) else "MISSING"
        print(f"  {coll_name:15} - {doc_count:5} docs [{index_status}]")

    print("\nBM25 indexes successfully rebuilt!")
    print("You can now restart your server.")

except Exception as e:
    print(f"Error rebuilding indexes: {e}")
    import traceback
    traceback.print_exc()
