from sentence_transformers import SentenceTransformer

model = SentenceTransformer(
    "sentence-transformers/all-MiniLM-L6-v2"
)

model.save_pretrained(
    "models/all-MiniLM-L6-v2",
    safe_serialization=True,
)

print("Embedding model saved successfully.")