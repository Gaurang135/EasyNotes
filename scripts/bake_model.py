"""Download bge-small-en-v1.5 into the image at build time, then print its path."""
import sys
from fastembed import TextEmbedding

DEST = "/app/models"
m = TextEmbedding(model_name="BAAI/bge-small-en-v1.5", cache_dir=DEST)
# force a real embed so all files are materialized
list(m.embed(["warmup"]))
print(f"model cached under {DEST}", file=sys.stderr)
