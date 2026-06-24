# Tecnologia de RAG do BMO

Documentação técnica do **RAG (Retrieval-Augmented Generation)** do Segundo
Cérebro do BMO: como as notas do Obsidian viram contexto pro LLM. É um **RAG
híbrido autêntico** — combina **busca vetorial (densa)**, **busca léxica
(palavra-chave)** e **expansão pelo grafo de `[[wikilinks]]`**, sem depender de
LangChain/LlamaIndex nem de banco vetorial (tudo stdlib + numpy).

> Resumo da mecânica: **o embedding (caro) é gerado no PC; o índice pronto vai
> pra Raspberry, que só faz cosseno (leve).** A *query* é 1 embedding que a Rasp
> pede ao PC pela rede.

---

## 1. Por que híbrido

Cada sinal cobre uma fraqueza do outro:

| Sinal | Acha bem | Falha em |
|---|---|---|
| **Léxico** (palavra-chave) | nomes próprios, termos exatos, tags, títulos de seção | sinônimo / paráfrase ("senhoras" ≠ "mulheres") |
| **Denso** (vetorial) | significado / paráfrase | termo raro exato, sigla específica |
| **Grafo** (`[[links]]`) | contexto relacional (notas vizinhas) | relevância textual sozinho |

O vault já tem o **grafo feito à mão** (os `[[links]]` que você escreve), então
a parte "graph" é autêntica e barata — não precisa de LLM extraindo entidades.

---

## 2. Arquitetura e fluxo

```
   ┌──────────────────────── PC (compute pesado) ────────────────────────┐
   │  Ollama  ──/v1/embeddings──  bge-m3 (1024-dim)                       │
   │     ▲                                   ▲                            │
   │     │ (build: embeda TODOS os chunks)   │ (query: 1 embedding)       │
   │  scripts/build_rag_index.py             │                            │
   │     │  1) GET /api/brain/export  ◀───── notas                        │
   │     │  2) chunka (mesmo chunk_markdown)                              │
   │     │  3) embeda (cache local)                                       │
   │     │  4) POST /api/brain/index ──────► índice pronto                │
   └─────┼───────────────────────────────────┼────────────────────────────┘
         │ (índice)                           │ (LAN: EMBED_URL)
   ┌─────▼───────────────────────────────────▼────────────────────────────┐
   │  RASPBERRY (runtime leve)                                             │
   │  .rag_index/index.json  ──►  vector_index (cosseno, numpy)            │
   │  knowledge.search_hybrid:  LÉXICO + DENSO (RRF) + GRAFO  ──► chat     │
   └───────────────────────────────────────────────────────────────────────┘
```

- **Indexar = caro = PC.** Roda quando você manda (builder).
- **Consultar = leve = Rasp.** Cosseno sobre vetores prontos + 1 embedding da
  query (pedido ao PC). Se o PC estiver off, **cai pro léxico** automaticamente.

---

## 3. Chunking (a unidade de busca)

`knowledge.chunk_markdown(text, level)` quebra a nota por **heading** do nível
`rag_chunk_level` (default **2 = `##`**):

- O trecho antes do 1º `##` vira o chunk de **intro** (`section = ""`).
- Cada `##` abre um chunk novo; `###`+ ficam DENTRO do chunk pai.
- `level = 0` desliga (a nota inteira é 1 chunk — comportamento antigo).

Cada chunk vai pro LLM com o cabeçalho **`### Nota › Seção` + tags + trecho**
(função `chat._fmt_hit`). Assim o modelo sabe de qual nota **e seção** veio o
contexto. No painel (editor) a **prévia ao vivo** mostra os chunks separados por
uma linha ondulada (componente `ChunkPreview`).

---

## 4. Os três sinais de retrieval

### 4.1 Léxico (`knowledge.search` / `_score_note`)
Busca por palavra-chave, no nível de chunk. Normaliza (minúsculas, sem acento),
tokeniza (`\W+`, termos ≥2 letras, stopwords PT). Pontua cada chunk:

- título da nota: **+4/termo**; tags: **+3/termo** (bônus de nota, em `_note_base`);
- **nome da seção (heading): +5×peso** — bater no título de uma seção é sinal forte;
- conteúdo do chunk: **+1×peso por ocorrência** (teto 5, pra repetição não dominar);
- **peso = 3 se o termo NÃO está no título da nota** (termo *discriminante*), senão 1.
  Sem isso o chunk de intro — que repete o título — venceria sempre (era um bug real:
  perguntar "membros" caía na intro em vez da seção "Membros").

Retorna o **melhor chunk de cada nota** (`{title, section, tags, snippet, score}`).

### 4.2 Denso / vetorial (`_dense_search` + `services/vector_index.py`)
- Embeda a query (`services/embeddings.py` → Ollama `/v1/embeddings`, bge-m3).
- Cosseno contra o índice (vetores **normalizados**, então cosseno = produto escalar).
  Usa **numpy** se disponível (rápido); senão cosseno em Python puro.
- Top-`rag_dense_k` (default 6) chunks por `(note_id, seção)`. O texto do chunk é
  re-derivado das notas da Rasp (o índice **não guarda texto**, só vetores).

### 4.3 Grafo (`_graph_neighbors`)
A partir das notas-semente (top do fundido), puxa o **melhor chunk dos vizinhos**
a 1 hop pelos `[[links]]` (`rag_graph_hops`, default 1). Dá o contexto relacional.

### 4.4 Fusão (RRF) e limiar
- **Reciprocal Rank Fusion** (`_rrf`, `score = Σ 1/(60+rank)`) combina léxico+denso
  por chunk. Hit que aparece nos dois ganha `source = "hibrido"`.
- Na fusão, **o léxico entra só com matches fortes (`score ≥ 4`)** — score 3 (um
  termo genérico no corpo) é ruído e empata com o denso real.
- Cada hit carrega: `score` (léxico), `dense` (cosseno 0–1), `source`
  (`lexico|denso|hibrido|grafo`), `rrf`.
- O **RAG automático** (`chat._auto_notes`, injeta sem o modelo pedir) só usa
  matches fortes: **`score ≥ 4` OU `dense ≥ 0.6`** — pra não poluir conversa fiada.

`knowledge.search_hybrid(query, k)` devolve os `k` principais + até 2 vizinhos de
grafo. Cai pro léxico puro se faltar índice/endpoint de embedding.

---

## 5. Arquivos

| Arquivo | Papel |
|---|---|
| `bmo_os/services/knowledge.py` | grafo das notas, `chunk_markdown`, `search` (léxico) e `search_hybrid` (denso+grafo), carregamento do índice |
| `bmo_os/services/embeddings.py` | cliente `/v1/embeddings` (Ollama/llama.cpp). Usado no build (PC) e na query (Rasp) |
| `bmo_os/services/vector_index.py` | `pack_index` (build) + `VectorIndex` (cosseno, numpy/puro) |
| `scripts/build_rag_index.py` | **builder, roda no PC**: export → chunk → embeda → index → push |
| `bmo_os/services/chat.py` | usa `search_hybrid` no RAG automático e na tool `notes_query` |
| `bmo_os/main.py` | endpoints `web_brain_export` / `web_brain_index` / `_rag_status` |

---

## 6. Endpoints HTTP (painel)

| Método | Rota | Pra quê |
|---|---|---|
| `GET` | `/api/brain` | snapshot do cérebro + **status do RAG** (`rag: {hybrid, indexed, model, embed_url}`) |
| `GET` | `/api/brain/export` | dump das notas (`{id, title, body}`) pro builder |
| `POST` | `/api/brain/index` | recebe o índice pronto (gerado no PC) e salva no perfil |
| `GET` | `/api/brain/search?q=` | testa o RAG híbrido (mostra `score`, `dense`, `source` por acerto) |

---

## 7. Formato do índice

`profiles/<sub>/knowledge/.rag_index/index.json` (gerado no PC, salvo na Rasp):

```jsonc
{
  "model": "bge-m3",
  "dim": 1024,
  "count": 93,
  "keys":    [["adcr bela vista", "Membros ADCR Bela Vista:"], ...],  // (note_id, seção)
  "hashes":  ["a1b2c3...", ...],                                      // hash do texto do chunk
  "vectors": "<base64 de float32 N*dim, JÁ NORMALIZADOS>"
}
```

Não guarda o **texto** do chunk: a Rasp re-deriva pela chave `(note_id, seção)`
com o mesmo `chunk_markdown` — economiza tamanho e garante que o texto bate. O
`hash` permite detectar chunk que mudou desde o build (vetor velho).

---

## 8. Configuração

Chaves em `bmo_config.json` (editáveis; default no `core/config.py`):

| Chave | Default | O quê |
|---|---|---|
| `rag_hybrid` | `true` | liga denso + grafo (senão só léxico) |
| `rag_chunk_level` | `2` | nível de heading que quebra em chunks (`##`); `0` = nota inteira |
| `embed_model` | `bge-m3` | modelo de embedding |
| `embed_url` | `""` | endpoint `/v1/embeddings`; `""` = AUTO (`.env EMBED_URL` → `127.0.0.1:11434`) |
| `rag_dense_k` | `6` | quantos chunks a busca densa traz pra fusão |
| `rag_graph_hops` | `1` | saltos de `[[link]]` na expansão de grafo |

No `.env` (por máquina): `EMBED_URL`, `EMBED_MODEL`. Na **Rasp**, aponte pro PC:
`EMBED_URL=jp-predator.local:11434` (hostname mDNS, à prova de DHCP).

---

## 9. Setup (uma vez)

### No PC — Ollama + modelo de embedding
```bash
# 1) instalar o Ollama (ollama.com), depois baixar o modelo multilíngue:
ollama pull bge-m3

# 2) deixar o Ollama acessível na LAN (a Rasp precisa alcançar):
#    Windows (persistente): variável de ambiente do usuário
setx OLLAMA_HOST "0.0.0.0:11434"
#    e reiniciar o Ollama. Libere a porta 11434 no firewall se preciso.
```

### Na Raspberry — apontar pro PC
No `/home/gravae/BMO/.env`:
```
EMBED_URL=jp-predator.local:11434
```
(`jp-predator` = hostname do PC; a Rasp resolve por mDNS.)

---

## 10. (Re)indexar

Sempre que **criar/editar notas**, rode o builder **no PC** (Ollama no ar):

```bash
cd BMO
python scripts/build_rag_index.py --pi 192.168.0.109:8000
# opções: --model bge-m3   --embed-url 127.0.0.1:11434
```

Ele baixa as notas da Rasp, chunka, embeda (com **cache** em
`scripts/.rag_cache.json` — só embeda o que mudou) e manda o índice pronto. A
Rasp recarrega sozinha no próximo uso (sem reiniciar).

> Futuro possível: disparar o build automaticamente quando o `drive_sync` baixar
> notas novas, ou um botão "reindexar" no painel.

---

## 11. Degradação graciosa

- **Ollama off / Rasp sem alcançar o PC** → `embed_one` falha → sem denso → **só
  léxico** (continua funcionando).
- **Sem índice** (`indexed = 0`) → idem, só léxico. O painel avisa pra rodar o builder.
- **numpy ausente** → cosseno em Python puro (mais lento, ok pra alguns milhares
  de chunks). A Rasp tem numpy (via opencv).

---

## 12. Verificação (exemplos reais, 42 notas → 93 chunks)

| Query (palavras ≠ das notas) | Acerto | Sinal |
|---|---|---|
| "quem comanda o grupo das senhoras" | `ADCR Bela Vista › Membros` | **denso** 0.39 (léxico erraria) |
| "qual o telefone pra contato" | `ADCR Sede › Localização e Contato` | **híbrido** (score 18 + denso 0.61) |
| "endereço da congregação bela vista" | `ADCR Bela Vista › Localização` | **híbrido** (25 + 0.64) |

Dá pra testar pelo painel (aba Cérebro → busca) ou:
```bash
curl "http://192.168.0.109:8000/api/brain/search?q=quem%20comanda%20as%20senhoras"
```

---

## 13. Limitações e roadmap

- **Não há rerank** (cross-encoder). Dá pra somar um reranker leve no PC ou usar o
  LLM como juiz nos top-N.
- **Graph-RAG local** (expansão de vizinhos), não global. Para perguntas
  "globais" (resumo de um tema espalhado), caberia **detecção de comunidades +
  resumos** (estilo Microsoft GraphRAG) — pesado em LLM no index-time, deixado de
  fora por ser exagero num vault pessoal.
- **Reindex manual** (rodar o builder). Ver §10.
