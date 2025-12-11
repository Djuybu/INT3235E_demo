from neo4j import GraphDatabase
import random

URI = "bolt://localhost:7687"
AUTH = ("neo4j", "12345678")
driver = GraphDatabase.driver(URI, auth=AUTH)

# -----------------------------------
# HÀM LẤY DỮ LIỆU 2-HOP PHỨC TẠP
# -----------------------------------
def fetch_two_hop_hard(tx):
    query = """
    // 1. Origin + Genre
    MATCH (s1:Singer)-[:BELONGS_TO_ORIGIN]->(o:Origin),
          (s1)-[:HAS_GENRE]->(g:Genre),
          (s2:Singer)-[:BELONGS_TO_ORIGIN]->(o),
          (s2)-[:HAS_GENRE]->(g)
    WHERE s1 <> s2
    RETURN 'origin_genre' AS type, s1.name AS a, o.name AS mid1, g.name AS mid2, s2.name AS b
    UNION

    // 2. Band + Genre
    MATCH (s1:Singer)<-[:HAS_MEMBER]-(b:Band)-[:HAS_MEMBER]->(s2:Singer),
          (s1)-[:HAS_GENRE]->(g:Genre),
          (s2)-[:HAS_GENRE]->(g)
    WHERE s1 <> s2
    RETURN 'band_genre' AS type, s1.name AS a, b.name AS mid1, g.name AS mid2, s2.name AS b
    UNION

    // 3. Origin + Band
    MATCH (s1:Singer)-[:BELONGS_TO_ORIGIN]->(o:Origin),
          (s1)<-[:HAS_MEMBER]-(b:Band)-[:HAS_MEMBER]->(s2:Singer),
          (s2)-[:BELONGS_TO_ORIGIN]->(o)
    WHERE s1 <> s2
    RETURN 'origin_band' AS type, s1.name AS a, o.name AS mid1, b.name AS mid2, s2.name AS b
    """
    result = tx.run(query)
    return [record.data() for record in result]

# -----------------------------------
# HÀM TẠO CÂU HỎI
# -----------------------------------
def generate_question_hard(r):
    t = r["type"]
    a = r["a"]
    mid1 = r["mid1"]
    mid2 = r["mid2"]
    b = r["b"]

    if t == "origin_genre":
        return f"{a} sinh ở {mid1} và theo dòng nhạc {mid2}. Ai khác cũng có quê quán và dòng nhạc này? → {b}"
    if t == "band_genre":
        return f"{a} từng thuộc nhóm {mid1} và theo dòng nhạc {mid2}. Nghệ sĩ nào khác cũng giống? → {b}"
    if t == "origin_band":
        return f"{a} sinh ở {mid1} và từng là thành viên của nhóm {mid2}. Ai khác cũng có đặc điểm này? → {b}"
    return None

# -----------------------------------
# CHẠY
# -----------------------------------
with driver.session() as session:
    rows = session.execute_read(fetch_two_hop_hard)

# Phân loại theo type
origin_genre_list = [r for r in rows if r["type"] == "origin_genre"]
band_genre_list   = [r for r in rows if r["type"] == "band_genre"]
origin_band_list  = [r for r in rows if r["type"] == "origin_band"]

sample = []
# Lấy 1-2 record mỗi loại, nếu đủ
if origin_genre_list:
    sample.extend(random.sample(origin_genre_list, k=min(7, len(origin_genre_list))))
if band_genre_list:
    sample.extend(random.sample(band_genre_list, k=min(7, len(band_genre_list))))
if origin_band_list:
    sample.extend(random.sample(origin_band_list, k=min(6, len(origin_band_list))))  # tổng = 20

random.shuffle(sample)  # trộn để không theo thứ tự type

print("\n=== 20 CÂU HỎI TWO-HOP KHÓ HƠN (ĐẦY ĐỦ 3 LOẠI) ===\n")
for i, r in enumerate(sample, 1):
    print(f"{i}. {generate_question_hard(r)}")
