from neo4j import GraphDatabase

uri = "bolt://localhost:7687"
user = "neo4j"
password = "12345678"

driver = GraphDatabase.driver(uri, auth=(user, password))

def run_shortest_path(driver, source_name, target_name):
    with driver.session() as session:

        # Drop graph if it already exists
        session.execute_write(lambda tx: tx.run("""
            CALL gds.graph.drop('singer_graph', false)
        """))

        # 1. Tạo graph tạm using new Cypher projection
        session.execute_write(lambda tx: tx.run("""
            MATCH (source:Singer)-[r:DIJKSTRA_COST]->(target:Singer)
            WITH gds.graph.project(
              'singer_graph',
              source,
              target,
              {
                sourceNodeLabels: ['Singer'],
                targetNodeLabels: ['Singer'],
                relationshipType: 'DIJKSTRA_COST',
                relationshipProperties: { weight: r.weight }
              }
            ) AS g
            RETURN g.graphName, g.nodeCount, g.relationshipCount
        """))

        # 2. Chạy Dijkstra
        result = session.execute_read(lambda tx: [
            record.values() for record in tx.run(f"""
            MATCH (source:Singer {{name:'{source_name}'}}), (target:Singer {{name:'{target_name}'}})
            WITH source, target
            CALL gds.shortestPath.dijkstra.stream(
                'singer_graph',
                {{ sourceNode: id(source), targetNode: id(target), relationshipWeightProperty:'weight' }}
            )
            YIELD index, sourceNode, targetNode, totalCost, nodeIds, costs
            RETURN 
                gds.util.asNode(sourceNode).name AS from,
                gds.util.asNode(targetNode).name AS to,
                totalCost,
                [nodeId IN nodeIds | gds.util.asNode(nodeId).name] AS pathNodes,
                costs
        """)
        ])

        # 3. Xóa graph tạm
        session.execute_write(lambda tx: tx.run("""
            CALL gds.graph.drop('singer_graph', false)
        """))

        return result

# --- Chạy với input từ ngoài ---
source_name = input("Nhập tên ca sĩ nguồn: ").strip()
target_name = input("Nhập tên ca sĩ đích: ").strip()

result = run_shortest_path(driver, source_name, target_name)

if result:
    row = result[0]  # Giả sử chỉ có 1 path
    print(f"Đường đi ngắn nhất từ {row[0]} đến {row[1]}:")
    print(f"Tổng chi phí: {row[2]}")
    print(f"Path: {' -> '.join(row[3])}")
else:
    print("Không tìm thấy đường đi.")

driver.close()