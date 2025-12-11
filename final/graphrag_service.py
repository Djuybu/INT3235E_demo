# graphrag_service.py
import os
import json
from typing import List, Dict, Any
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from neo4j import GraphDatabase
import pandas as pd
import networkx as nx
from sentence_transformers import SentenceTransformer
import numpy as np
import faiss
import threading
from pyvis.network import Network

# -------------------
# CONFIG từ ENV
# -------------------
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASS = os.getenv("NEO4J_PASS", "neo4j")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")  # optional
EMBED_MODEL = os.getenv("EMBED_MODEL", "all-MiniLM-L6-v2")
EMBED_DIM = int(os.getenv("EMBED_DIM", "384"))  # model dim (all-MiniLM-L6-v2 -> 384)

# -------------------
# GLOBALS
# -------------------
driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
model = None  # Lazy init: load khi cần
index = None               # faiss index
docs_meta: List[Dict] = [] # metadata per index vector
docs_emb: np.ndarray = None
KG: nx.Graph = nx.Graph()
lock = threading.Lock()

app = FastAPI(title="GraphRAG Service")

# -------------------
# Lazy load model helper
# -------------------
def get_model():
    global model
    if model is None:
        model = SentenceTransformer(EMBED_MODEL)
    return model

# -------------------
# Pydantic models
# -------------------
class BuildRequest(BaseModel):
    node_query: str = "MATCH (n) RETURN id(n) AS id, labels(n)[0] AS label, properties(n) AS props"
    edge_query: str = "MATCH (a)-[r]->(b) RETURN id(a) AS src, id(b) AS tgt, type(r) AS rel, properties(r) AS rel_props"
    include_edges_as_docs: bool = True

class QueryRequest(BaseModel):
    question: str
    top_k: int = 10
    expand_hop: int = 1
    max_nodes: int = 200
    use_llm: bool = True
    llm_model: str = "gpt-4o-mini"  # placeholder

# -------------------
# Helpers: text for node/edge
# -------------------
def node_text(node_id: int, data: dict) -> str:
    label = data.get("label") or "Node"
    props = data.get("props") or {}
    name = props.get("name") or props.get("title") or props.get("id") or str(node_id)
    extra = ", ".join(f"{k}: {v}" for k, v in props.items() if k not in ("name","title","id"))
    return f"[{label}] {name}" + (f" ({extra})" if extra else "")

def edge_text(u:int, v:int, edata:dict) -> str:
    rel = edata.get("rel") or edata.get("type") or "REL"
    rel_props = edata.get("rel_props") or {}
    props_str = ", ".join(f"{k}: {v}" for k,v in rel_props.items())
    return f"{u} -[{rel}]-> {v}" + (f" ({props_str})" if props_str else "")

# -------------------
# Build index endpoint
# -------------------
@app.post("/build_index")
def build_index(req: BuildRequest):
    global index, docs_meta, docs_emb, KG
    with lock:
        try:
            # 1) export nodes
            with driver.session() as session:
                node_rows = list(session.run(req.node_query))
                edge_rows = list(session.run(req.edge_query))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Neo4j query error: {e}")

        nodes = []
        for r in node_rows:
            rec = dict(r.items())
            nodes.append(rec)
        edges = []
        for r in edge_rows:
            rec = dict(r.items())
            edges.append(rec)

        # 2) build networkx KG
        G = nx.Graph()
        for n in nodes:
            nid = int(n.get("id"))
            G.add_node(nid, label=n.get("label"), props=n.get("props") or {})
        for e in edges:
            s = int(e.get("src")); t = int(e.get("tgt"))
            G.add_edge(s, t, rel=e.get("rel"), rel_props=e.get("rel_props") or {})

        # 3) create docs: one doc per node; optionally one per edge
        docs = []
        meta = []
        for n, data in G.nodes(data=True):
            txt = node_text(n, {"label": data.get("label"), "props": data.get("props")})
            docs.append(txt)
            meta.append({"type":"node","id":int(n),"label":data.get("label"),"text":txt})
        if req.include_edges_as_docs:
            for u,v,edata in G.edges(data=True):
                txt = edge_text(u,v, {"rel": edata.get("rel"), "rel_props": edata.get("rel_props")})
                docs.append(txt)
                meta.append({"type":"edge","u":int(u),"v":int(v),"rel":edata.get("rel"),"text":txt})

        # 4) compute embeddings
        if len(docs) == 0:
            raise HTTPException(status_code=400, detail="No docs produced from graph.")
        emb = get_model().encode(docs, convert_to_numpy=True, show_progress_bar=True)
        faiss.normalize_L2(emb)

        # 5) build FAISS index (Inner product on normalized vectors == cosine)
        dim = emb.shape[1]
        idx = faiss.IndexFlatIP(dim)
        idx.add(emb)

        # assign globals
        KG = G
        index = idx
        docs_meta = meta
        docs_emb = emb

        return {"status":"ok", "nodes": G.number_of_nodes(), "edges": G.number_of_edges(), "docs": len(docs)}

# -------------------
# Retriever + k-hop expand
# -------------------
def retrieve_and_expand(question: str, top_k=10, expand_hop=1, max_nodes=200):
    if index is None or docs_emb is None or len(docs_meta)==0:
        raise RuntimeError("Index not built. Call /build_index first.")
    q_emb = get_model().encode([question], convert_to_numpy=True)
    faiss.normalize_L2(q_emb)
    D, I = index.search(q_emb, top_k)
    hits = I[0].tolist()
    retrieved = [docs_meta[i] for i in hits]

    seed_nodes = set()
    for it in retrieved:
        if it["type"] == "node":
            seed_nodes.add(int(it["id"]))
        else:
            seed_nodes.add(int(it["u"])); seed_nodes.add(int(it["v"]))

    # k-hop expansion
    frontier = set(seed_nodes)
    for _ in range(expand_hop):
        new_frontier = set()
        for n in frontier:
            if n in KG:
                new_frontier.update(set(KG.neighbors(n)))
        seed_nodes.update(new_frontier)
        frontier = new_frontier
        if len(seed_nodes) >= max_nodes:
            break

    subG = KG.subgraph(seed_nodes).copy()
    node_texts = [node_text(n, subG.nodes[n]) for n in subG.nodes()]
    edge_texts = [edge_text(u,v, subG.edges[(u,v)]) for u,v in subG.edges()]
    context = "\n".join(node_texts + edge_texts)
    return {"subgraph": subG, "context": context, "retrieved": retrieved}

# -------------------
# LLM answer helper (uses OpenAI if key provided; otherwise returns context)
# -------------------
def llm_answer(question:str, context:str, model_name="gpt-4o-mini", max_tokens=400):
    if OPENAI_API_KEY is None:
        # fallback: return the context so user can inspect
        return {"answer": None, "note": "OPENAI_API_KEY not set; returning context only.", "context": context}
    import openai
    openai.api_key = OPENAI_API_KEY
    prompt = f"""Dưới đây là thông tin rút trích từ đồ thị tri thức (subgraph):
{context}

Hỏi: {question}

Trả lời ngắn gọn, dựa trên subgraph; nếu cần, trích dẫn node (label/name).
"""
    resp = openai.ChatCompletion.create(
        model=model_name,
        messages=[{"role":"user","content":prompt}],
        temperature=0.0,
        max_tokens=max_tokens
    )
    text = resp["choices"][0]["message"]["content"]
    return {"answer": text, "context": context}

# -------------------
# API: query endpoint
# -------------------
@app.post("/query")
def query_graph(req: QueryRequest):
    try:
        res = retrieve_and_expand(req.question, top_k=req.top_k, expand_hop=req.expand_hop, max_nodes=req.max_nodes)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    subG = res["subgraph"]
    context = res["context"]
    retrieved = res["retrieved"]
    out = {
        "nodes": subG.number_of_nodes(),
        "edges": subG.number_of_edges(),
        "retrieved": retrieved
    }
    if req.use_llm:
        ans = llm_answer(req.question, context, model_name=req.llm_model)
        out["answer"] = ans.get("answer")
        out["llm_note"] = ans.get("note", None)
    else:
        out["context"] = context
    return out

# -------------------
# API: visualize subgraph (returns HTML file path)
# -------------------
@app.post("/visualize")
def visualize_query(req: QueryRequest):

    try:
        res = retrieve_and_expand(
            req.question,
            top_k=req.top_k,
            expand_hop=req.expand_hop,
            max_nodes=req.max_nodes
        )
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    subG = res["subgraph"]

    # Tạo file output HTML
    out_html = "subgraph_visualization.html"

    # Giới hạn 100 node để tránh crash
    if subG.number_of_nodes() > 100:
        degrees = dict(subG.degree())
        top_nodes = sorted(degrees, key=degrees.get, reverse=True)[:100]
        subG = subG.subgraph(top_nodes).copy()
    
    # Tạo mạng PyVis
    net = Network(
        height="900px",
        width="100%",
        bgcolor="#111111",
        font_color="white",
        directed=True
    )

    net.set_options("""
    var options = {
      "physics": {
        "enabled": true,
        "barnesHut": {
          "gravitationalConstant": -8000,
          "springLength": 100,
          "springStrength": 0.05
        }
      },
      "nodes": {"shape": "dot", "size": 15},
      "edges": {"arrows": "to", "color": "#00ff88"}
    }
    """)

    # Thêm node
    for n, data in subG.nodes(data=True):
        name = data.get("props", {}).get("name", f"ID_{n}")
        label = data.get("label", "Unknown")
        title = f"{label}: {name}"
        color = {
            "Singer": "#ff6b6b",
            "Band": "#4ecdc4",
            "Institution": "#45b7d1",
            "Label": "#f9ca24",
            "Origin": "#6c5ce7",
            "Gene": "#a29bfe"
        }.get(label, "#95a5a6")
        net.add_node(n, label=name, title=title, color=color, size=20)

    # Thêm edge
    for u, v, edata in subG.edges(data=True):
        rel = edata.get("rel", "")
        if "COLLABORATED_WITH" in rel:
            net.add_edge(u, v, title="COLLABORATED_WITH", width=2, color="#ff4757")
        else:
            net.add_edge(u, v, title=rel, color="#2ed573")

    # Xuất file HTML
    net.write_html(out_html)

    import webbrowser, os
    webbrowser.open(f"file://{os.path.abspath(out_html)}")

    return {
        "html": out_html,
        "nodes": subG.number_of_nodes(),
        "edges": subG.number_of_edges()
    }


# -------------------
# Health check
# -------------------
@app.get("/health")
def health():
    return {"status":"ok", "nodes_in_memory": KG.number_of_nodes(), "edges_in_memory": KG.number_of_edges()}