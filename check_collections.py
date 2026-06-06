"""Check ChromaDB collections and document counts."""
import sys
sys.path.insert(0, 'backend')

from vectorstore.chroma_store import chroma_store
from core.constants import Collection

print("Checking ChromaDB collections...\n")

for collection in Collection:
    try:
        coll = chroma_store.get_collection(collection.value)
        count = coll.count()
        print(f"[OK] {collection.value:20} - {count:5} chunks")
    except Exception as e:
        print(f"[FAIL] {collection.value:20} - ERROR: {e}")
