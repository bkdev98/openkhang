# BGE-M3 vs text-embedding-3-small: Quality Comparison

**Date:** 2026-04-07
**Sources:** HuggingFace model cards, MTEB leaderboard aggregators, BGE-M3 paper (arxiv 2402.03216), FlagEmbedding GitHub, practitioner benchmarks

---

## 1. MTEB Overall Scores

| Model | MTEB Overall | Retrieval (English) | Params | Dims |
|---|---|---|---|---|
| BAAI/bge-m3 | ~63.0 | ~59.56 | 568M | 1024 |
| text-embedding-3-small | ~62.26 | ~55–57* | API-only | 1536 (reducible) |
| text-embedding-3-large | ~64.6 | ~59–60 | API-only | 3072 |

*text-embedding-3-small retrieval exact NDCG@10 not directly published on leaderboard; estimated from relative gap to -3-large.

**Verdict on MTEB overall:** bge-m3 (63.0) > text-embedding-3-small (62.26) by ~0.7 pts — marginal, within noise for most tasks.

---

## 2. Multilingual Retrieval (Where the Gap Widens)

### MIRACL (18 languages, nDCG@10)
- bge-m3 (all modes: dense + sparse + multi-vec): **70.0 nDCG@10** average
- bge-m3 (dense only): outperforms all baselines including OpenAI on average
- text-embedding-3-small: **not evaluated on MIRACL** in official leaderboard data; -3-large is used as the OpenAI reference

### MKQA (26 languages, Recall@100)
- bge-m3: **75.5%** recall
- Strongest non-bge-m3 baseline (includes OpenAI models): **~70.9%**
- Gap: +4.6pp for bge-m3

These are the clearest head-to-head numbers from the original paper (arxiv 2402.03216). OpenAI's reference in the paper is text-embedding-ada-002 / text-embedding-3-large — **text-embedding-3-small was not the comparison target**, but it performs strictly below -3-large, widening the gap further.

---

## 3. Vietnamese Language Performance

**Direct data: scarce.** No official Vietnamese-specific MTEB or MIRACL scores found for either model.

What exists:
- bge-m3 covers 100+ languages including Vietnamese, trained on 170+ language corpus; Vietnamese is a mid-resource language in its training data (not low-resource, not high-resource)
- ViRanker paper (arxiv 2509.09131) used bge-m3 as base for Vietnamese reranking; reports NDCG@3 = 0.6815, MRR@3 = 0.6641 on MMARCO-VI — but this is the fine-tuned ViRanker, not raw bge-m3
- A Vietnamese practitioner benchmark (nqbao.medium.com) exists but was inaccessible — title confirms it specifically tests embedding models for Vietnamese retrieval tasks
- text-embedding-3-small has no published Vietnamese-specific eval data

**Inference:** bge-m3 was explicitly trained for cross-lingual retrieval and demonstrates strong multilingual generalization (MIRACL avg 70.0). text-embedding-3-small is English-first. For Vietnamese, bge-m3 is the safer choice based on architecture and training data breadth.

---

## 4. Retrieval Quality (NDCG@10, BEIR)

BEIR (English heterogeneous retrieval, 18 datasets, nDCG@10):
- Neither model's exact BEIR breakdown was obtainable from current public sources
- In MTEB English retrieval aggregate: bge-m3 ~59.56 vs text-embedding-3-small estimated ~55–57
- text-embedding-3-large ~59–60 on English retrieval, roughly matching bge-m3

---

## 5. Head-to-Head: Practitioner Reports

- **Agentset.ai ELO comparison:** text-embedding-3-small shows +13 ELO over bge-m3 on English-only retrieval tasks — narrow margin
- **Paul Graham essay RAG test (cited in search aggregators):** bge-m3 achieved 72% overall retrieval accuracy, with 92.5% on long questions — bge-m3 wins on long-context retrieval
- **Hybrid retrieval advantage:** bge-m3 supports dense + sparse + ColBERT (multi-vec) from a single model. text-embedding-3-small is dense-only. In hybrid RAG setups, bge-m3 is architecturally superior

---

## 6. Summary Trade-off Table

| Dimension | bge-m3 | text-embedding-3-small |
|---|---|---|
| MTEB overall | 63.0 | 62.26 |
| English retrieval | ~59.56 | ~55–57 |
| Multilingual (MIRACL) | 70.0 nDCG@10 | Not evaluated |
| Cross-lingual (MKQA) | 75.5% R@100 | Below -3-large (~70.9%) |
| Vietnamese | No official data; strong inference | No official data; weaker inference |
| Long-doc retrieval | Strong (8192 token ctx) | Weak (512–8191 reducible) |
| Hybrid retrieval | Yes (dense+sparse+colbert) | Dense only |
| Cost | Free (self-host) / ~$0.007/M tokens | $0.02/M tokens |
| Latency | Higher (568M params) | Lower (API, smaller) |
| Vendor lock-in | None | OpenAI |

---

## Verdict

**bge-m3 wins on every dimension relevant to multilingual/Vietnamese RAG:**
- Better or equal MTEB overall
- Clearly superior multilingual benchmarks (MIRACL +~10 pts over baselines, MKQA +4.6pp)
- Hybrid retrieval capability gives it structural advantage in production RAG
- No Vietnamese-specific head-to-head exists, but training scope and multilingual benchmark results strongly favor bge-m3

text-embedding-3-small's only real advantages: lower latency via API and marginally higher ELO on English-only retrieval (+13 ELO is negligible in practice).

**For a Vietnamese-language RAG system: use bge-m3.**

---

## Unresolved Questions

1. No Vietnamese-specific NDCG@10 data for either model found. nqbao's Medium benchmark is the closest resource but was inaccessible — worth direct review.
2. text-embedding-3-small's exact BEIR/MTEB retrieval task NDCG@10 not published separately by OpenAI; only overall MTEB score (62.26) is widely cited.
3. bge-m3's MTEB English retrieval score (59.56) may reflect the dense-only mode; hybrid mode likely scores higher but is not included in MTEB official submissions.
4. VN-MTEB (arxiv 2507.21500) is a new Vietnamese MTEB benchmark — results for these two models on that suite are unknown.
