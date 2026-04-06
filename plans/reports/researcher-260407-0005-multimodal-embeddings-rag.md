# Multimodal Embeddings for RAG: Research Report

**Date:** 2026-04-07  
**Context:** Digital twin agent for mobile/frontend dev. Evaluating whether embedding UI designs, screenshots, wireframes alongside text adds value.

---

## 1. Model Landscape

| Model | Provider | Dims | API Cost | Notes |
|---|---|---|---|---|
| **voyage-multimodal-3** | Voyage AI (MongoDB) | 1024 | $0.12/1M tokens; $0.00003–$0.0012/image | Best cross-modal benchmark perf; 32K token ctx |
| **Cohere Embed v4** | Cohere | 1536 | ~$0.12/1M tokens | Only major commercial model native multimodal same vector space |
| **Jina CLIP v2** | Jina AI | 1024 | Free (self-host) / Jina API | 0.9B params; Matryoshka; 89 languages; decent text-text retrieval too |
| **Nomic Embed Vision** | Nomic | 768 | Free (self-host) | Shares vector space with Nomic Embed Text; text ↔ image interop out-of-box |
| **SigLIP / CLIP** | Google / OpenAI | 512–1024 | Free (self-host) | Research-grade; no text-text retrieval; not production-ready for RAG |

**API-ready options worth considering:** voyage-multimodal-3, Cohere Embed v4. Self-host: Nomic Embed Vision + Jina CLIP v2.

---

## 2. Benchmark Quality

**MMEB leaderboard** (cross-modal retrieval, ~36 tasks):
- voyage-multimodal-3: state-of-art on MMEB, beats Cohere multimodal by 13.7pp and OpenAI v3-large by 5.1pp
- Jina CLIP v2: competitive but primarily tested on image-text cross-retrieval (fashion, product)
- Nomic Embed Vision: good for its size; text-text retrieval degrades vs. pure text models

**Caveat:** MMEB distractors are considered too easy — hard-negative retrieval quality is less differentiated. Real-world precision on niche domains (mobile UI, design tokens) untested.

**Text-text retrieval loss:** All multimodal models sacrifice some text-text retrieval quality vs. dedicated text embedders (bge-m3, OpenAI te3-large). Nomic is the smallest gap. This matters if your RAG corpus is 95% text.

---

## 3. Real-World Adoption

**Actual production use of multimodal RAG for design/UI work: rare.** Most documented cases are:
- Enterprise doc retrieval (PDFs with charts, infographics)
- E-commerce (product image + description search)
- Medical imaging + report retrieval

Design/UI-specific multimodal RAG: no published case studies found. This is experimental territory as of early 2026.

**Common production pattern** for design context: VLM captions (GPT-4o, Claude) → text description → text-only embedding. Simpler, cheaper, and retrieval quality is acceptable because design intent is usually capturable in text.

---

## 4. When Multimodal Embeddings Add Value vs. Text Captions

**Multimodal embeddings win when:**
- User queries with an image ("find components that look like this")
- Visual similarity matters beyond what text can describe (layout density, color scheme)
- Corpus is too large to re-caption with a VLM at ingestion time

**Text captions (VLM → text embed) win when:**
- Queries are text-only ("find the login screen design")
- You control caption quality (GPT-4o captions are semantically rich)
- You want to keep a single text embedding model (simpler stack)

**For a digital twin doing mobile dev:** queries will almost always be text-driven ("how does the auth flow look", "what color is the primary button"). VLM captions beat native multimodal here — cleaner retrieval, simpler ops.

---

## 5. Dimensions & pgvector Compatibility

Two approaches:
1. **Single multimodal model** (voyage-multimodal-3): text + image → same 1024-dim space. One table, simple queries. Tradeoff: text-text quality slightly lower.
2. **Separate models** (bge-m3 for text + Nomic Vision for images): two pgvector tables, two query paths. Better text quality, more ops complexity.

Current stack uses bge-m3 (1024 dims, pgvector). voyage-multimodal-3 outputs 1024 dims — compatible if you switch. Nomic Vision outputs 768 dims — separate table needed.

**pgvector supports both strategies** via different tables or a single table with a `modality` column.

---

## 6. Cost Reality Check

At typical ingestion scale (1,000 screenshots/wireframes):
- voyage-multimodal-3: ~$0.30–$1.20 per 1,000 images (varies by resolution) + $0.12/1M text tokens
- VLM captions (GPT-4o-mini) for 1,000 images: ~$1–3 for caption generation, then text embedding is near-zero (bge-m3 self-hosted)

**Cost difference is small at small scale.** Architecture complexity difference is significant.

---

## 7. Honest Assessment

**Verdict: Not worth investing in now. Revisit at 6 months.**

Reasons:
1. **YAGNI** — no evidence this project retrieves images by visual similarity. Text queries dominate.
2. **VLM caption path is simpler and already good** — Claude/GPT-4o captions of UI screenshots capture layout, components, colors well enough for text retrieval.
3. **No production playbook for UI/design multimodal RAG** — this is genuinely experimental. You'd be pioneering, not following proven patterns.
4. **Text-text quality regression** — switching from bge-m3 to voyage-multimodal-3 trades known multilingual strength for multimodal capability you don't yet need.
5. **The useful trigger** — if users start querying with screenshot images ("find me something like this design"), then multimodal becomes justified. Not before.

**If forced to choose today:** voyage-multimodal-3 via API (best benchmark, 1024 dims matching current stack, free tier covers initial ingestion). But don't.

---

## Sources

- [Voyage Multimodal 3 announcement](https://blog.voyageai.com/2024/11/12/voyage-multimodal-3/)
- [Voyage AI pricing](https://docs.voyageai.com/docs/pricing)
- [MMEB Leaderboard (HuggingFace)](https://huggingface.co/spaces/TIGER-Lab/MMEB-Leaderboard)
- [Nomic Embed Vision blog](https://www.nomic.ai/blog/posts/nomic-embed-vision)
- [Jina CLIP v2 paper](https://arxiv.org/abs/2412.08802)
- [Weaviate: Multimodal Embeddings and RAG practical guide](https://weaviate.io/blog/multimodal-guide)
- [Microsoft ISE: Multimodal RAG with Vision](https://devblogs.microsoft.com/ise/multimodal-rag-with-vision/)
- [KX Systems: Guide to Multimodal RAG 2025](https://medium.com/kx-systems/guide-to-multimodal-rag-for-images-and-text-10dab36e3117)
- [Milvus: Best Embedding Models for RAG 2026](https://milvus.io/blog/choose-embedding-model-rag-2026.md)

---

## Unresolved Questions

1. Does the digital twin ever receive image inputs from users (screenshots posted in chat)? If yes, the case for multimodal strengthens significantly.
2. What fraction of ingested Confluence/design docs contain non-captioned images that a VLM can't easily describe?
3. Nomic Embed Vision's exact multilingual performance vs bge-m3 on Vietnamese — not benchmarked.
