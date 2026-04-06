# Voyage AI vs BGE-M3: Multilingual Embedding Research

**Date:** 2026-04-07  
**Context:** Current stack uses BGE-M3 (1024-dim) via Ollama locally. Anthropic recommends Voyage AI. Evaluating switch for Vietnamese+English RAG.

---

## 1. Voyage AI Model Lineup

| Model | Dims (default) | Context | Free Tier | Price/MTok | Multilingual |
|---|---|---|---|---|---|
| **voyage-3-large** | 1024 (also 2048/512/256) | — | 200M tokens | $0.18 | Yes (26+ langs evaluated) |
| **voyage-3.5** | 1024 | — | 200M tokens | $0.06 | Yes |
| **voyage-3.5-lite** | 1024 | — | 200M tokens | $0.02 | Yes |
| **voyage-multilingual-2** | 1024 | — | 50M tokens | $0.12 | Yes (17 langs evaluated incl. Vietnamese) |
| **voyage-3** | 1024 | — | 200M tokens | $0.06 | Yes (300+ langs claimed) |
| **voyage-3-lite** | 512 | — | 200M tokens | $0.02 | Partial |
| **voyage-code-3** | 1024 | — | 200M tokens | $0.18 | Code-focused |

Notes:
- voyage-4 family also exists (voyage-4-large, voyage-4, voyage-4-lite) at 2048-dim default — not evaluated here, limited public benchmarks
- `voyage-3-m-exp` exists on HuggingFace as an experimental multilingual variant (not production)
- Free tier: 200M tokens is generous for testing; 50M for voyage-multilingual-2 is more restrictive

---

## 2. MTEB Benchmark: Voyage vs BGE-M3

**MTEB Overall (English, all tasks):**

| Model | MTEB Overall | Notes |
|---|---|---|
| BGE-M3 | 63.0 | Open source, self-hosted |
| voyage-3-large | ~67+ | Ranks #1 across 8 domains/100 datasets per Voyage's internal eval |
| voyage-3 | ~65 | General purpose |
| text-embedding-3-small (OpenAI) | 62.26 | English-first |

**Critical caveat:** Voyage's internal benchmarks compare against OpenAI-v3-large and Cohere-v3-English — not BGE-M3 directly. Voyage-3-large claims +9.74% over OpenAI-v3-large and +20.71% over Cohere-v3-English. No published Voyage vs BGE-M3 MTEB head-to-head found.

**MTEB Multilingual leaderboard leaders (2025-2026):**

| Model | MTEB Multilingual | Type |
|---|---|---|
| Qwen3-Embedding-8B | 70.58 | Open source |
| bge-multilingual-gemma2 | 74.1 | Open source |
| NVIDIA Llama-Embed-Nemotron-8B | ~71+ | Open source |
| BGE-M3 | ~59.56 (MMTEB) / 63.0 (overall) | Open source |
| voyage-3-large | Not independently published on MTEB multilingual leaderboard | API |

Voyage AI benchmarks are self-reported on proprietary evaluation spreadsheets, not submitted to MTEB leaderboard for independent verification.

---

## 3. Multilingual Benchmarks: MIRACL / MKQA

**BGE-M3 (from original paper arxiv 2402.03216):**
- MIRACL (18 langs, nDCG@10): **70.0** (all modes: dense+sparse+multi-vec)
- MIRACL dense only: **67.8**
- MKQA (26 langs, Recall@100): **75.5%**

**voyage-multilingual-2:**
- Evaluated on 17 languages including Vietnamese
- Outperforms OpenAI text-embedding-3-large on Vietnamese (vi), Chinese (zh), Hindi (hi) in Voyage's own eval (2024 blog post)
- Exact nDCG@10 scores not published per language; only relative improvement claims vs OpenAI
- No MIRACL submission found on official MIRACL leaderboard

**voyage-3-large multilingual domain:**
- Claims #1 across multilingual domain (62 datasets, 26 languages)
- Evaluated on internal spreadsheet only; not MTEB-submitted

**Key gap:** No peer-reviewed MIRACL score for any Voyage model found. BGE-M3's MIRACL numbers are from published arxiv paper. Direct numerical comparison is not possible with high confidence.

---

## 4. Vietnamese Language Support

**BGE-M3:**
- Explicitly trained on 170+ language corpus; Vietnamese is mid-resource (not low-resource)
- ViRanker paper (arxiv 2509.09131) used BGE-M3 as base for Vietnamese reranking: NDCG@3 = 0.6815 on MMARCO-VI (fine-tuned variant)
- VN-MTEB benchmark (arxiv 2507.21500) exists; BGE-M3 results not yet confirmed from search

**Voyage AI:**
- voyage-multilingual-2 explicitly tested on Vietnamese; "slightly outperforms OpenAI on vi" (self-reported)
- voyage-3-large claims 300+ language support; Vietnamese included
- No independent Vietnamese-specific benchmark (VN-MTEB) results for Voyage found
- voyage-3-m-exp (HuggingFace experimental) exists but no production status

**Assessment:** BGE-M3's Vietnamese support is better documented and independently validated. Voyage's Vietnamese claim is self-reported against OpenAI only.

---

## 5. Models That Beat BGE-M3 on Multilingual Retrieval (2025-2026)

Open-source models confirmed ahead of BGE-M3 on MTEB multilingual:

| Model | MTEB Multilingual | Self-Host | API Available |
|---|---|---|---|
| **bge-multilingual-gemma2** | 74.1 | Yes | Via Together/HuggingFace |
| **Qwen3-Embedding-8B** | 70.58 | Yes | Via Together/API |
| **NVIDIA Llama-Embed-Nemotron-8B** | ~71+ | Yes | NVIDIA NIM |
| BGE-M3 | ~63–70 (task-dependent) | Yes | Via OpenRouter/DeepInfra |

API-only models better than BGE-M3 on multilingual:
- Cohere embed-v4: 65.2 MTEB overall (multilingual-native)
- voyage-3-large: Claims superiority but lacks independent multilingual MTEB submission

---

## 6. Mem0 + Voyage AI Integration

**Mem0 natively supported embedder providers (confirmed):**
`openai`, `ollama`, `huggingface`, `azure_openai`, `gemini`, `vertexai`, `together`, `lmstudio`, `langchain`, `aws_bedrock`

**Voyage AI: NOT a native Mem0 embedder provider.** Not in the provider enum.

**Integration path via LangChain wrapper:**

LangChain has `langchain_community.embeddings.VoyageAIEmbeddings` (confirmed in LangChain repo). Mem0 supports `langchain` provider:

```python
from langchain_community.embeddings import VoyageAIEmbeddings

voyage_embedder = VoyageAIEmbeddings(
    voyage_api_key=os.getenv("VOYAGE_API_KEY"),
    model="voyage-multilingual-2",  # or voyage-3-large
)

config = {
    "embedder": {
        "provider": "langchain",
        "config": {
            "langchain_embeddings": voyage_embedder,
            "embedding_dims": 1024,
        }
    },
    "vector_store": {
        "provider": "pgvector",
        "config": {
            "connection_string": "...",
            "embedding_model_dims": 1024,
        }
    }
}
```

**Risk:** Mem0's `langchain` provider behavior is documented but less battle-tested than `openai` or `ollama` providers. Check Mem0 GitHub issue #1455 and #1515 for known quirks.

---

## 7. Pricing Summary

| Model | Free Tier | Pay-as-you-go |
|---|---|---|
| voyage-3-large | 200M tokens | $0.18/MTok |
| voyage-3.5 | 200M tokens | $0.06/MTok |
| voyage-3.5-lite | 200M tokens | $0.02/MTok |
| voyage-multilingual-2 | 50M tokens | $0.12/MTok |
| voyage-3 | 200M tokens | $0.06/MTok |
| **BGE-M3 (Ollama)** | **Free (self-host)** | **$0/MTok** |
| BGE-M3 (OpenRouter) | Free credits | $0.01/MTok |

For 1M tokens/month: voyage-multilingual-2 = $120, voyage-3.5 = $60, voyage-3-large = $180. BGE-M3 via Ollama = $0.

---

## 8. Trade-off Matrix

| Dimension | BGE-M3 (Ollama) | voyage-multilingual-2 | voyage-3-large |
|---|---|---|---|
| MTEB overall | 63.0 (verified) | Not on leaderboard | ~67+ (self-reported) |
| MIRACL multilingual | 70.0 nDCG@10 (paper) | Not submitted | Not submitted |
| Vietnamese evidence | Mid-resource trained; ViRanker validated | Self-reported vs OpenAI only | Self-reported |
| Mem0 integration | Native (`ollama`) | Via LangChain wrapper | Via LangChain wrapper |
| Ops complexity | Local model, GPU/CPU needed | API, no infra | API, no infra |
| Cost | $0 | $0.12/MTok | $0.18/MTok |
| Hybrid retrieval | Yes (dense+sparse+ColBERT) | Dense only | Dense only |
| Anthropic endorsement | No | Yes | Yes |
| Free tier | Yes (local) | 50M tokens | 200M tokens |
| Adoption risk | MIT license, stable | MongoDB-acquired (2024); roadmap TBD | Same |

---

## 9. Recommendation (Ranked)

**For Vietnamese + English RAG, ranked:**

**1. Stay on BGE-M3 (current) — strongly recommended if ops constraints allow**
- Best verified multilingual benchmarks (MIRACL 70.0)
- Hybrid retrieval (dense+sparse+ColBERT) is a structural advantage for RAG
- Zero cost
- Vietnamese support better documented than Voyage
- Only downside: Ollama requires local infra; if moving to cloud, use OpenRouter ($0.01/MTok)

**2. voyage-3.5 or voyage-3 — if Anthropic integration or ops simplicity is required**
- $0.06/MTok (same as OpenAI TE3-small)
- 200M free tier to validate
- Drops hybrid retrieval entirely (dense only)
- Vietnamese quality unverified vs BGE-M3 (only vs OpenAI)
- Not directly comparable to BGE-M3 in any published benchmark

**3. voyage-multilingual-2 — only if explicit multilingual contract/compliance needed**
- More expensive ($0.12/MTok), smaller free tier (50M)
- Does beat OpenAI on Vietnamese per Voyage's eval
- No MIRACL validation; worse economics than voyage-3.5 for equivalent multilingual task

**Do NOT choose Voyage AI based on MTEB/MIRACL score claims** — their benchmarks are self-reported on internal spreadsheets, not MTEB-submitted. BGE-M3's numbers are from peer-reviewed arxiv paper and MTEB leaderboard submissions.

**If switching away from self-hosted is the goal:** Prefer OpenRouter BGE-M3 ($0.01/MTok) over Voyage AI. Same model, same embeddings, no re-embedding needed, 10x cheaper than voyage-3.5.

---

## Unresolved Questions

1. **Voyage MIRACL scores:** Voyage AI has never submitted to MIRACL leaderboard. Without this, their multilingual claim is marketing, not benchmark.
2. **VN-MTEB results:** Neither BGE-M3 nor Voyage models have confirmed scores on VN-MTEB (arxiv 2507.21500) — the only Vietnamese-specific embedding benchmark. Worth checking directly.
3. **Mem0 LangChain embedder stability:** The `langchain` provider path for Voyage in Mem0 is documented but has known issues (GitHub #1455, #1515). Test before committing.
4. **voyage-3-m-exp production status:** This HuggingFace experimental model may be Voyage's actual multilingual-optimized model; no production docs exist.
5. **MongoDB acquisition impact:** Voyage AI was acquired by MongoDB in 2024. Long-term API pricing/availability post-acquisition unclear.

---

## Sources

- [Voyage AI Pricing Docs](https://docs.voyageai.com/docs/pricing) *(official)*
- [voyage-3-large blog post (Jan 2025)](https://blog.voyageai.com/2025/01/07/voyage-3-large/) *(official, self-reported)*
- [voyage-multilingual-2 blog post (Jun 2024)](https://blog.voyageai.com/2024/06/10/voyage-multilingual-2-multilingual-embedding-model/) *(official)*
- [MTEB Leaderboard HuggingFace](https://huggingface.co/spaces/mteb/leaderboard)
- [BGE-M3 paper arxiv 2402.03216](https://arxiv.org/abs/2402.03216) *(peer-reviewed)*
- [MMTEB: Massive Multilingual Text Embedding Benchmark](https://arxiv.org/html/2502.13595v4)
- [Qwen3-Embedding vs BGE-M3 analysis](https://medium.com/@mrAryanKumar/comparative-analysis-of-qwen-3-and-bge-m3-embedding-models-for-multilingual-information-retrieval-72c0e6895413)
- [Mem0 Embedders Config](https://docs.mem0.ai/components/embedders/config)
- [Mem0 LangChain Embedder Docs](https://docs.mem0.ai/components/embedders/models/langchain)
- [LangChain VoyageAI Embeddings](https://github.com/langchain-ai/langchain/blob/master/libs/langchain/langchain/embeddings/voyageai.py)
- [Best Open-Source Embedding Models 2026](https://www.bentoml.com/blog/a-guide-to-open-source-embedding-models)
- [MIRACL Project](https://project-miracl.github.io/)
- [Voyage Multilingual-2 Evaluation (TDS)](https://towardsdatascience.com/voyage-multilingual-2-embedding-evaluation-a544ac8f7c4b/)
- [Vietnamese Embedding Benchmark (nqbao)](https://nqbao.medium.com/benchmarking-text-embedding-models-for-vietnamese-retrieval-tasks-3c4342e0ff9d)
- [NVIDIA Llama-Embed-Nemotron-8B](https://huggingface.co/blog/nvidia/llama-embed-nemotron-8b)
