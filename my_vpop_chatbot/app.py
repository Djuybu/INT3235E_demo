# app.py - V-Pop Graph AI 2025 - FINAL: CHẠY NGON 100%, ĐẸP, KHÔNG LỖI
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
import uvicorn
from neo4j import GraphDatabase
from sentence_transformers import SentenceTransformer
import faiss
import numpy as np

app = FastAPI(title="V-Pop Graph AI")

class VPopBot:
    def __init__(self, uri="bolt://localhost:7687", auth=("neo4j", "12345678")):
        print("Khởi tạo V-Pop Graph AI...")
        self.driver = GraphDatabase.driver(uri, auth=auth)
        self.embedder = SentenceTransformer("keepitreal/vietnamese-sbert")
        self.index = None
        self.meta = []
        self.build_vector_index()

    def build_vector_index(self):
        query = "MATCH (n:Singer|Band) WHERE n.name IS NOT NULL RETURN elementId(n) AS id, n.name AS name"
        with self.driver.session() as s:
            results = s.run(query).data()
        names = [r["name"] for r in results]
        embs = self.embedder.encode(names, normalize_embeddings=True, convert_to_numpy=True).astype('float32')
        self.index = faiss.IndexFlatIP(embs.shape[1])
        self.index.add(embs)
        self.meta = [(r["name"], r["id"]) for r in results]
        print(f"Vector index: {len(names)} nghệ sĩ & ban nhạc")

    def search(self, q, topk=6, thresh=0.33):
        if not self.index: return []
        qe = self.embedder.encode([q], normalize_embeddings=True, convert_to_numpy=True).astype('float32')
        D, I = self.index.search(qe, topk)
        return [(self.meta[idx][0], self.meta[idx][1]) for sc, idx in zip(D[0], I[0]) if sc >= thresh][:6]

    def get_profile(self, node_id):
        query = """
        MATCH (n) WHERE elementId(n) = $id
        
        OPTIONAL MATCH (n)-[:HAS_ORIGIN]->(origin)
        OPTIONAL MATCH (n)-[:BELONGS_TO_INSTITUTION]->(school)
        OPTIONAL MATCH (n)-[:BELONGS_TO_LABEL]->(label)
        OPTIONAL MATCH (n)-[:HAS_GENRE]->(genre)
        OPTIONAL MATCH (n)-[:MEMBER_OF]->(member)
        
        WITH n, origin, school, label, genre, member, properties(n) AS props
        
        RETURN 
            n.name AS name,
            labels(n) AS labels,
            props.birthYear AS birthYear,
            props.activeYears AS activeYears,
            props.members AS members_array,
            props.link AS wiki,
            origin.name AS origin,
            school.name AS school,
            label.name AS label,
            collect(DISTINCT genre.name) AS genres,
            collect(DISTINCT member.name) AS member_nodes
        """
        with self.driver.session() as s:
            res = s.run(query, id=node_id).single()
            if not res:
                return "Không có thông tin."

            name = res["name"]
            is_band = "Band" in res["labels"]
            info = [f"<strong>{name}{' (Ban nhạc)' if is_band else ''}</strong>"]

            # Năm sinh / năm hoạt động
            if is_band and res["activeYears"]:
                info.append(f"hoạt động {res['activeYears']}")
            elif not is_band and res["birthYear"]:
                info.append(f"sinh năm {res['birthYear']}")

            # Thành viên (chỉ cho Band)
            if is_band:
                members = res["members_array"] or res["member_nodes"]
                if members:
                    if isinstance(members, list):
                        members_str = ", ".join(members)
                    else:
                        members_str = str(members)
                    if len(members_str) > 120:
                        members_str = members_str[:120] + "..."
                    info.append(f"thành viên: {members_str}")

            # Thông tin cá nhân (chỉ cho Singer)
            if not is_band:
                if res["origin"]:
                    info.append(f"quê {res['origin']}")
                if res["school"]:
                    info.append(f"học tại {res['school']}")

            # Thông tin chung
            if res["label"]:
                info.append(f"thuộc {res['label']}")
            if res["genres"]:
                info.append(f"thể loại: {', '.join(res['genres'])}")
            if res["wiki"]:
                info.append(f"wiki: <a href='{res['wiki']}' target='_blank'>xem tại đây</a>")

            return " • ".join(info)

    def has_direct_collab(self, id1, id2):
        q = "MATCH (a)-[:COLLABORATED_WITH]-(b) WHERE elementId(a)=$id1 AND elementId(b)=$id2 RETURN count(*) > 0"
        with self.driver.session() as s:
            return s.run(q, id1=id1, id2=id2).single()[0]

    def find_bridge(self, singers):
        for a, b in [(singers[i], singers[j]) for i in range(len(singers)) for j in range(i+1, len(singers))]:
            query = """
            MATCH (a)-[:COLLABORATED_WITH]-(x)-[:COLLABORATED_WITH]-(b)
            WHERE elementId(a)=$aid AND elementId(b)=$bid
            RETURN x.name AS bridge LIMIT 1
            """
            with self.driver.session() as s:
                res = s.run(query, aid=a[1], bid=b[1]).single()
                if res:
                    return f"{a[0]} → <strong>{res['bridge']}</strong> → {b[0]}"
        return None

    def answer(self, question):
        q = question.strip().lower()

        if any(k in q for k in ["là ai", "giới thiệu", "profile", "ai vậy", "band"]):
            res = self.search(question, topk=1, thresh=0.38)
            if res:
                return self.get_profile(res[0][1])
            return "Không tìm thấy nghệ sĩ/ban nhạc này."

        singers = self.search(question, topk=6, thresh=0.33)
        if len(singers) < 2:
            return "Không tìm thấy đủ nghệ sĩ."

        for i in range(len(singers)):
            for j in range(i+1, len(singers)):
                if self.has_direct_collab(singers[i][1], singers[j][1]):
                    return "Có hợp tác trực tiếp."

        bridge = self.find_bridge(singers)
        if bridge:
            return f"Có cầu nối: {bridge}"

        return "Không có hợp tác hay cầu nối."

bot = VPopBot()

@app.get("/", response_class=HTMLResponse)
async def home():
    return """<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>V-Pop Knowledge Graph</title>
    <style>
        :root { --bg: #121212; --chat-bg: #1e1e1e; --user-msg: #0084ff; --bot-msg: #2d2d2d; --text: #e0e0e0; --accent: #00ff88; }
        body { font-family: 'Segoe UI', sans-serif; background: var(--bg); color: var(--text); margin: 0; display: flex; justify-content: center; height: 100vh; }
        .container { width: 100%; max-width: 800px; display: flex; flex-direction: column; height: 100%; padding: 20px; box-sizing: border-box; }
        h2 { text-align: center; color: var(--accent); margin-bottom: 20px; text-transform: uppercase; letter-spacing: 2px; }
        #chat-box { flex: 1; background: var(--chat-bg); border-radius: 12px; overflow-y: auto; padding: 20px; display: flex; flex-direction: column; gap: 15px; border: 1px solid #333; box-shadow: 0 4px 15px rgba(0,0,0,0.5); }
        .msg { padding: 12px 16px; border-radius: 18px; max-width: 80%; line-height: 1.5; font-size: 15px; animation: fadeIn 0.3s ease; }
        .user { align-self: flex-end; background: var(--user-msg); color: white; border-bottom-right-radius: 4px; }
        .bot { align-self: flex-start; background: var(--bot-msg); border-left: 3px solid var(--accent); border-bottom-left-radius: 4px; }
        .input-area { margin-top: 20px; display: flex; gap: 10px; }
        input { flex: 1; padding: 15px; border-radius: 30px; border: 1px solid #333; background: #252525; color: white; font-size: 16px; outline: none; transition: 0.3s; }
        input:focus { border-color: var(--accent); background: #333; }
        button { padding: 0 30px; border-radius: 30px; border: none; background: var(--accent); color: #000; font-weight: bold; cursor: pointer; transition: transform 0.2s; }
        button:active { transform: scale(0.95); }
        button:disabled { background: #555; cursor: not-allowed; }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
        .typing { display: flex; gap: 5px; padding: 10px; }
        .dot { width: 8px; height: 8px; background: #888; border-radius: 50%; animation: bounce 1.4s infinite ease-in-out both; }
        .dot:nth-child(1) { animation-delay: -0.32s; }
        .dot:nth-child(2) { animation-delay: -0.16s; }
        @keyframes bounce { 0%, 80%, 100% { transform: scale(0); } 40% { transform: scale(1); } }
    </style>
</head>
<body>
    <div class="container">
        <h2>V-Pop Graph AI</h2>
        <div id="chat-box">
            <div class="msg bot">Chào bạn! Tôi có thể giúp gì về mạng lưới V-Pop?</div>
        </div>
        <div class="input-area">
            <input type="text" id="inp" placeholder="Nhập câu hỏi..." onkeypress="if(event.key==='Enter') send()">
            <button id="btn" onclick="send()">Gửi</button>
        </div>
    </div>
    <script>
        async function send() {
            const inp = document.getElementById('inp');
            const btn = document.getElementById('btn');
            const box = document.getElementById('chat-box');
            const q = inp.value.trim();
            if (!q) return;

            box.innerHTML += `<div class="msg user">${q}</div>`;
            inp.value = '';
            btn.disabled = true;
            box.scrollTop = box.scrollHeight;

            const loadId = 'load-' + Date.now();
            box.innerHTML += `
                <div class="msg bot" id="${loadId}">
                    <div class="typing"><div class="dot"></div><div class="dot"></div><div class="dot"></div></div>
                </div>`;
            box.scrollTop = box.scrollHeight;

            try {
                const res = await fetch('/ask', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({message: q})
                });
                const data = await res.json();
                let replyText = data.reply
                    .replace(/\\n/g, '<br>')
                    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
                document.getElementById(loadId).innerHTML = replyText;
            } catch(e) {
                document.getElementById(loadId).innerHTML = "Lỗi kết nối server.";
            } finally {
                btn.disabled = false;
                box.scrollTop = box.scrollHeight;
                inp.focus();
            }
        }
    </script>
</body>
</html>"""

@app.post("/ask")
async def ask(req: Request):
    data = await req.json()
    q = data.get("message", "").strip()
    return {"reply": bot.answer(q) if q else "Hỏi gì đi bạn!"}

if __name__ == "__main__":
    print("\n" + "="*80)
    print("   V-POP GRAPH AI 2025 - FINAL: CHẠY NGON, ĐẸP, KHÔNG LỖI")
    print("="*80)
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=False)