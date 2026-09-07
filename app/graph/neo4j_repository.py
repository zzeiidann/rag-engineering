from typing import Any

from neo4j import GraphDatabase

from app.auth.models import Principal
from app.graph.models import KnowledgeGraphFragment
from app.models import Candidate, Chunk, Document
from app.retrieval.text import terms


class Neo4jGraphRepository:
    def __init__(self, uri: str, user: str, password: str):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        self.driver.verify_connectivity()
        for label in ["Resource", "Entity", "Chunk", "Client", "Department", "User", "Role"]:
            self.run(f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{label}) REQUIRE n.id IS UNIQUE")

    def run(self, query: str, **params: Any) -> list[dict[str, Any]]:
        records, _, _ = self.driver.execute_query(query, parameters_=params, database_="neo4j")
        return [dict(record) for record in records]

    def replace(
        self, document: Document, chunks: list[Chunk], fragment: KnowledgeGraphFragment
    ) -> None:
        key = f"{document.id}:{document.version}"
        entities = [
            dict(id=f"{key}:{e.id}", local_id=e.id, kind=e.kind, name=e.name)
            for e in fragment.entities
        ]
        edges = [
            dict(source=f"{key}:{e.source}", target=f"{key}:{e.target}", kind=e.kind)
            for e in fragment.edges
        ]

        def write(tx: Any) -> None:
            tx.run("MATCH (n) WHERE n.document_id=$id DETACH DELETE n", id=document.id).consume()
            tx.run(
                "CREATE (r:Resource {id:$key, document_id:$id, "
                "title:$title, visibility:$visibility})",
                key=key,
                id=document.id,
                title=document.title,
                visibility=document.metadata.visibility,
            ).consume()
            tx.run(
                "UNWIND $chunks AS c MATCH (r:Resource {id:$key}) "
                "CREATE (n:Chunk {id:c.id, document_id:$id, resource_key:$key, "
                "payload:c.payload}) CREATE (r)-[:HAS_CHUNK]->(n)",
                chunks=[dict(id=c.id, payload=c.model_dump_json()) for c in chunks],
                key=key,
                id=document.id,
            ).consume()
            tx.run(
                "UNWIND $entities AS e MATCH (r:Resource {id:$key}) "
                "CREATE (n:Entity {id:e.id, local_id:e.local_id, kind:e.kind, name:e.name, "
                "document_id:$id, resource_key:$key}) CREATE (n)-[:DESCRIBED_BY]->(r)",
                entities=entities,
                key=key,
                id=document.id,
            ).consume()
            # Relationship types are from the validated enum, never user query strings.
            for edge in edges:
                tx.run(
                    "MATCH (a:Entity {id:$source}), (b:Entity {id:$target}) "
                    f"CREATE (a)-[:{edge['kind']} {{category:'knowledge'}}]->(b)",
                    source=edge["source"],
                    target=edge["target"],
                ).consume()
            if document.metadata.owner_client_id:
                tx.run(
                    "MERGE (c:Client {id:$owner}) WITH c MATCH (r:Resource {id:$key}) "
                    "CREATE (c)-[:OWNS {category:'authorization'}]->(r)",
                    owner=document.metadata.owner_client_id,
                    key=key,
                ).consume()
                tx.run(
                    "MATCH (c:Client {id:$owner}), (e:Entity {resource_key:$key}) "
                    "WHERE e.kind='Policy' CREATE (c)-[:OWNS {category:'authorization'}]->(e)",
                    owner=document.metadata.owner_client_id,
                    key=key,
                ).consume()
                tx.run(
                    "MATCH (c:Client {id:$owner}), (e:Entity {resource_key:$key}) "
                    "WHERE e.kind='Contract' "
                    "CREATE (c)-[:HAS_CONTRACT {category:'knowledge'}]->(e)",
                    owner=document.metadata.owner_client_id,
                    key=key,
                ).consume()
            for department in document.metadata.allowed_departments:
                tx.run(
                    "MERGE (d:Department {id:$department}) WITH d "
                    "MATCH (r:Resource {id:$key}) "
                    "CREATE (d)-[:CAN_ACCESS {category:'authorization'}]->(r)",
                    department=department,
                    key=key,
                ).consume()
                tx.run(
                    "MATCH (d:Department {id:$department}), (e:Entity {resource_key:$key}) "
                    "WHERE e.kind='Procedure' CREATE (d)-[:MANAGES {category:'knowledge'}]->(e)",
                    department=department,
                    key=key,
                ).consume()

        with self.driver.session(database="neo4j") as session:
            session.execute_write(write)

    def seed_identity(self, principal: Principal) -> None:
        self.run(
            "MERGE (u:User {id:$id}) WITH u OPTIONAL MATCH "
            "(u)-[old:MEMBER_OF|CLIENT_OF|HAS_ROLE]->() DELETE old",
            id=principal.user_id,
        )
        self.run(
            "MATCH (u:User {id:$id}) MERGE (r:Role {id:$role}) "
            "MERGE (u)-[:HAS_ROLE {category:'authorization'}]->(r)",
            id=principal.user_id,
            role=principal.role,
        )
        if principal.client_id:
            self.run(
                "MATCH (u:User {id:$id}) MERGE (c:Client {id:$client}) "
                "MERGE (u)-[:CLIENT_OF {category:'authorization'}]->(c)",
                id=principal.user_id,
                client=principal.client_id,
            )
        if principal.department:
            self.run(
                "MATCH (u:User {id:$id}) MERGE (d:Department {id:$department}) "
                "MERGE (u)-[:MEMBER_OF {category:'authorization'}]->(d)",
                id=principal.user_id,
                department=principal.department,
            )

    def get_allowed_resources(self, principal: Principal, scope: list[str]) -> list[str]:
        # The graph can only narrow the catalog's scope, never grant additional access.
        return [
            r["id"]
            for r in self.run(
                "MATCH (r:Resource) WHERE r.id IN $scope AND "
                "(r.visibility <> 'client' OR $role='internal' OR "
                "EXISTS { MATCH (:Client {id:$client})-[:OWNS]->(r) }) RETURN r.id AS id",
                scope=scope,
                role=principal.role,
                client=principal.client_id,
            )
        ]

    def expand_context(self, query: str, scope: list[str], top_k: int) -> list[Candidate]:
        if not scope or not terms(query):
            return []
        rows = self.run(
            "MATCH (seed:Entity) WHERE seed.resource_key IN $scope "
            "AND any(t IN $terms WHERE toLower(seed.name) CONTAINS t) "
            "MATCH path=(seed)-[:COVERS|EXCLUDES|HAS_LIMIT|RELATED_TO|DESCRIBES|REFERENCES|"
            "PRICED_BY*0..2]-(related:Entity) "
            "WHERE all(n IN nodes(path) WHERE n.resource_key IN $scope) "
            "MATCH (related)-[:DESCRIBED_BY]->(r:Resource)-[:HAS_CHUNK]->(c:Chunk) "
            "WHERE r.id IN $scope AND c.resource_key IN $scope "
            "WITH c, max(1.0 / (1 + length(path))) AS score "
            "RETURN c.payload AS payload, score ORDER BY score DESC, c.id LIMIT $limit",
            scope=scope,
            terms=sorted(terms(query)),
            limit=top_k,
        )
        return [
            Candidate(chunk=Chunk.model_validate_json(r["payload"]), graph_score=r["score"])
            for r in rows
        ]

    def get_related_entities(self, entity_id: str, scope: list[str]) -> list[dict[str, Any]]:
        return self.run(
            "MATCH (e:Entity) WHERE (e.id=$id OR e.local_id=$id) AND e.resource_key IN $scope "
            "OPTIONAL MATCH (e)-[r]-(other:Entity) "
            "WHERE other.resource_key IN $scope AND r.category='knowledge' "
            "RETURN e.id AS id, e.name AS name, e.kind AS kind, "
            "collect({relationship:type(r), name:other.name, id:other.id}) AS related",
            id=entity_id,
            scope=scope,
        )
