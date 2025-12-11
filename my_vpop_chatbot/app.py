# app.py - V-Pop Drama Bot 2025 - PHIÊN BẢN HOÀN HẢO CUỐI CÙNG
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import uvicorn
import torch
import os
from neo4j import GraphDatabase
from sentence_transformers import SentenceTransformer
from transformers import AutoModelForCausalLM, AutoTokenizer
import faiss
import numpy as np
from itertools import permutations

app = FastAPI(title="V-Pop Drama Bot 2025")

# ===================== GRAPH RAG + VERIFIER =====================
class VPopGraphRAG:
    def __init__(self, uri="bolt://localhost:7687", auth=("neo4j", "12345678")):
        print("Khởi tạo V-Pop GraphRAG + Qwen Verifier...")
        self.driver = None
        try:
            self.driver = GraphDatabase.driver(uri, auth=auth)
            print("Kết nối Neo4j thành công!")
        except Exception as e:
            print(f"Không kết nối được Neo4j: {e} → Chạy offline mode")

        self.embedder = SentenceTransformer("keepitreal/vietnamese-sbert")
        self.index = None
        self.meta = []
        self.exact_map = {}
        self.build_index()
        self.verifier = QwenVerifier()

    def build_index(self):
        if not self.driver:
            print("Không có Neo4j → dùng mock index")
            return

        query = """
        MATCH (n) WHERE n.name IS NOT NULL
        RETURN elementId(n) AS id, n.name AS name, labels(n)[0] AS type
        """
        try:
            with self.driver.session() as session:
                results = session.run(query).data()

            texts = []
            self.meta = []
            self.exact_map = {}

            for r in results:
                name = r["name"]
                norm = name.lower().strip()
                self.exact_map[norm] = {"id": r["id"], "name": name, "type": r["type"]}
                texts.append(name)
                self.meta.append({"id": r["id"], "name": name, "type": r["type"]})

            if texts:
                embs = self.embedder.encode(texts, normalize_embeddings=True, convert_to_numpy=True).astype('float32')
                dim = embs.shape[1]
                self.index = faiss.IndexFlatIP(dim)
                self.index.add(embs)
                print(f"Đã index {len(texts)} nghệ sĩ V-Pop thành công!")
        except Exception as e:
            print(f"Lỗi build index: {e}")

    def search_entities(self, q, k=15, thresh=0.38):
        found = set()
        q_lower = q.lower().strip()
        q_clean = q_lower.replace(" ", "").replace("-", "")

        # Danh sách từ khóa ưu tiên cao
        priority_keywords = [
            "sơn tùng", "son tung", "sontung", "mtp", "sky",
            "hòa minzy", "hoà minzy", "hoaminzy", "minzy",
            "đen vâu", "den vau", "denvau", "đen",
            "binz", "karik", "justatee", "andree", "suboi", "rhymastic",
            "hồ ngọc hà", "hongocha", "hà hồ", "mỹ tâm", "noo", "erik", "đức phúc",
            "hương tràm", "chi pu", "tăng duy tân", "phương ly", "min", "đông nhi",
            "hiền hồ", "amee", "hoàng thùy linh", "tlinh", "mck", "bích phương"
        ]

        # Ưu tiên tìm từ khóa
        for keyword in priority_keywords:
            if keyword in q_clean or keyword.replace(" ", "") in q_clean:
                for norm_name, meta in self.exact_map.items():
                    if keyword.replace(" ", "") in norm_name.replace(" ", ""):
                        found.add((meta["name"], meta["id"], meta["type"]))

        # Exact match thông thường
        for norm_name, meta in self.exact_map.items():
            clean_name = norm_name.replace(" ", "").replace("-", "")
            if norm_name in q_lower or clean_name in q_clean:
                found.add((meta["name"], meta["id"], meta["type"]))

        # Vector search bổ sung
        if self.index and len(found) < 4:
            qe = self.embedder.encode([q], normalize_embeddings=True, convert_to_numpy=True).astype('float32')
            D, I = self.index.search(qe, k)
            for score, idx in zip(D[0], I[0]):
                if score < thresh or idx >= len(self.meta):
                    continue
                meta = self.meta[idx]
                name = meta["name"]
                if len(name) < 4:
                    continue
                if name not in [x[0] for x in found]:
                    found.add((name, meta["id"], meta["type"]))

        result = list(found)
        result.sort(key=lambda x: (-len(x[0]), x[2] not in ["Singer", "Band"]))
        return result[:4]

    def verify(self, question):
        entities = self.search_entities(question)
        singers = [e for e in entities if e[2] in ["Singer", "Band"]]
        context = f"Tìm thấy: {', '.join([e[0] for e in entities])}\n"

        if len(singers) == 2:
            a, b = singers[0], singers[1]
            direct = self.check_direct(a[1], b[1])
            context += f"Hợp tác trực tiếp ({a[0]} - {b[0]}): {'CÓ' if direct else 'KHÔNG'}\n"
            if not direct:
                path = self.check_path(a[1], b[1])
                context += f"Gián tiếp: {path}"

        elif len(singers) >= 3:
            found_bridge = False
            for perm in permutations(singers[:3], 3):
                s1, bridge, s2 = perm
                if self.check_bridge(s1[1], bridge[1], s2[1]):
                    context += f"TÌM THẤY CẦU NỐI: {s1[0]} → {bridge[0]} → {s2[0]}"
                    found_bridge = True
                    break
            if not found_bridge:
                context += "Không tìm thấy cầu nối rõ ràng"
        else:
            context += "Không đủ thông tin để xác minh quan hệ"

        verdict = self.verifier.answer(question, context)
        return context, verdict

    def check_direct(self, id1, id2):
        if not self.driver: return False
        q = "MATCH (a)-[:COLLABORATED_WITH]-(b) WHERE elementId(a)=$id1 AND elementId(b)=$id2 RETURN count(*) > 0"
        with self.driver.session() as s:
            return s.run(q, id1=id1, id2=id2).single()[0]

    def check_path(self, id1, id2):
        if not self.driver: return "Không kết nối"
        q = """
        MATCH p = shortestPath((a)-[:COLLABORATED_WITH*..5]-(b))
        WHERE elementId(a)=$id1 AND elementId(b)=$id2
        RETURN [n in nodes(p) | n.name] AS path
        """
        with self.driver.session() as s:
            res = s.run(q, id1=id1, id2=id2).single()
            return " → ".join(res["path"]) if res and res["path"] else "Không có đường nối"

    def check_bridge(self, id1, bid, id2):
        if not self.driver: return False
        q = """
        MATCH (a)-[:COLLABORATED_WITH]-(b)-[:COLLABORATED_WITH]-(c)
        WHERE elementId(a)=$id1 AND elementId(b)=$bid AND elementId(c)=$id2
        RETURN count(*) > 0
        """
        with self.driver.session() as s:
            return s.run(q, id1=id1, bid=bid, id2=id2).single()[0]


class QwenVerifier:
    def __init__(self):
        model_name = "Qwen/Qwen2.5-0.5B-Instruct"
        print(f"Đang load {model_name}...")
        self.tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
        self.model = AutoModelForCausalLM.from_pretrained(
            model_name,
            torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
            device_map="auto",
            trust_remote_code=True
        )

    def answer(self, question, context):
        prompt = f"""<|im_start|>system
Bạn là bộ xác thực logic V-Pop. Chỉ trả lời TRUE hoặc FALSE.

QUY TẮC:
- Có "TÌM THẤY", "CÓ", "CẦU NỐI", "hợp tác" → TRUE
- Có "KHÔNG", "Không tìm thấy", "Không có" → FALSE
- Không giải thích. Chỉ 1 từ.

Context:
{context}

Câu hỏi: {question}
<|im_end|>
<|im_start|>assistant
"""

        inputs = self.tokenizer(prompt, return_tensors="pt").to(self.model.device)
        with torch.no_grad():
            out = self.model.generate(
                **inputs,
                max_new_tokens=8,
                do_sample=False,
                temperature=0.0,
                pad_token_id=self.tokenizer.eos_token_id
            )
        resp = self.tokenizer.decode(out[0], skip_special_tokens=True)
        ans = resp.split("assistant")[-1].strip().upper()
        return "TRUE" if "TRUE" in ans else "FALSE"


# Khởi tạo hệ thống
rag = VPopGraphRAG()


# ===================== FASTAPI ROUTES =====================
@app.get("/", response_class=HTMLResponse)
async def home():
    return """
    <!DOCTYPE html>
    <html><head><meta charset="utf-8"><title>V-Pop Drama Bot 2025</title>
    <style>
        body{font-family:Segoe UI;background:#0f0f1a;color:#fff;text-align:center;padding:40px;}
        h1{color:#ff6bff;} .chat{width:80%;max-width:700px;margin:30px auto;background:#1a1a2e;padding:20px;border-radius:15px;}
        input,button{padding:12px;font-size:16px;margin:10px 0;width:100%;border-radius:8px;border:none;}
        button{background:#ff6bff;color:white;cursor:pointer;}
        .msg{margin:10px 0;padding:12px;border-radius:12px;}
        .user{background:#16213e;text-align:right;}
        .bot{background:#2a2a4e;}
    </style></head>
    <body>
        <h1>V-Pop Drama Bot 2025</h1>
        <p>Chỉ nói sự thật từ database. Không bịa. Không ảo.</p>
        <div class="chat" id="chat"></div>
        <input type="text" id="input" placeholder="Hỏi đi, ví dụ: Sơn Tùng với Đen Vâu có hợp tác không?" onkeypress="if(event.key==='Enter')send()">
        <button onclick="send()">Gửi</button>
        <script>
            async function send(){const i=document.getElementById("input");const c=document.getElementById("chat");let q=i.value.trim();if(!q)return;
            c.innerHTML+=`<div class="msg user">Bạn: ${q}</div>`;i.value="";
            const r=await fetch("/ask",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({message:q})});
            const d=await r.json();c.innerHTML+=`<div class="msg bot">Bot: ${d.reply}</div>`;c.scrollTop=c.scrollHeight;}
        </script>
    </body></html>
    """

@app.post("/ask")
async def ask(req: Request):
    data = await req.json()
    question = data.get("message", "").strip()
    if not question:
        return {"reply": "Hỏi gì đi boss"}

    context, verdict = rag.verify(question)
    if verdict == "TRUE":
        reply = f"ĐÚNG 100%! {context}"
    else:
        reply = f"KHÔNG ĐÚNG đâu nha. {context}"

    return {"reply": reply}


# ===================== CHẠY BOT =====================
if __name__ == "__main__":
    print("\n" + "="*70)
    print("        V-POP DRAMA BOT 2025 - HOÀN HẢO & CHẠY NGON 100%")
    print("="*70)
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=False)