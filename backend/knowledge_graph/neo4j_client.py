"""
Deep Query — Neo4j Knowledge Graph Client

Manages entities, relationships, and graph queries for the knowledge
graph subsystem.

Node types: Person, Organisation, Concept, Document, Location, Event
Relationships: AUTHORED_BY, AFFILIATED_WITH, REFERENCES, DEFINES, etc.
"""

import logging
from typing import Any, Dict, List, Optional

from neo4j import GraphDatabase

from core.config import settings

logger = logging.getLogger(__name__)


class Neo4jClient:
    """Neo4j graph database client for entity and relationship management."""

    def __init__(self):
        self._driver = None

    @property
    def driver(self):
        if self._driver is None:
            self._driver = GraphDatabase.driver(
                settings.neo4j_uri,
                auth=(settings.neo4j_username, settings.neo4j_password),
            )
            logger.info(f"Connected to Neo4j at {settings.neo4j_uri}")
        return self._driver

    def close(self):
        if self._driver:
            self._driver.close()

    def ensure_schema(self) -> None:
        """Create indexes and constraints for the knowledge graph."""
        constraints = [
            "CREATE INDEX entity_name IF NOT EXISTS FOR (n:Entity) ON (n.name)",
            "CREATE INDEX entity_type IF NOT EXISTS FOR (n:Entity) ON (n.entity_type)",
            "CREATE INDEX doc_node IF NOT EXISTS FOR (n:Document) ON (n.document_id)",
        ]
        with self.driver.session() as session:
            for query in constraints:
                try:
                    session.run(query)
                except Exception as e:
                    logger.warning(f"Schema setup query failed: {e}")

    # ── Entity Management ────────────────────────────────────

    def upsert_entities(
        self, entities: List[Dict], document_id: str
    ) -> None:
        """Upsert entities into the graph.

        Each entity dict has: name, type (Person/Organisation/Concept/etc.)
        Invalidates caches for affected entities.
        """
        from core.redis_client import redis_client

        with self.driver.session() as session:
            for entity in entities:
                name = entity.get("name", "").strip()
                entity_type = entity.get("type", "Concept")
                if not name:
                    continue

                try:
                    session.run(
                        """
                        MERGE (e:Entity {name: $name})
                        ON CREATE SET e.entity_type = $entity_type,
                                      e.created_from = $doc_id,
                                      e.mention_count = 1
                        ON MATCH SET e.mention_count = e.mention_count + 1
                        WITH e
                        MERGE (d:Document {document_id: $doc_id})
                        MERGE (e)-[:MENTIONED_IN]->(d)
                        """,
                        name=name,
                        entity_type=entity_type,
                        doc_id=document_id,
                    )

                    # Invalidate cache for this entity
                    cache_key_pattern = f"neo4j:entity:{name.lower()}:*"
                    redis_client.delete_pattern(cache_key_pattern)

                except Exception as e:
                    logger.error(f"Failed to upsert entity '{name}': {e}")

    def upsert_relationships(
        self, relationships: List[Dict], document_id: str
    ) -> None:
        """Upsert relationships between entities.

        Each relationship dict has: subject, predicate, object
        """
        with self.driver.session() as session:
            for rel in relationships:
                subject = rel.get("subject", "").strip()
                predicate = rel.get("predicate", "RELATED_TO")
                obj = rel.get("object", "").strip()

                if not subject or not obj:
                    continue

                try:
                    # Create both entities if they don't exist, then create relationship
                    session.run(
                        f"""
                        MERGE (s:Entity {{name: $subject}})
                        MERGE (o:Entity {{name: $object}})
                        MERGE (s)-[r:{predicate}]->(o)
                        ON CREATE SET r.source_document = $doc_id
                        """,
                        subject=subject,
                        object=obj,
                        doc_id=document_id,
                    )
                except Exception as e:
                    logger.error(
                        f"Failed to upsert relationship {subject} -[{predicate}]-> {obj}: {e}"
                    )

    # ── Graph Queries ────────────────────────────────────────

    def find_entity(self, name: str) -> Optional[Dict]:
        """Find an entity by name (case-insensitive)."""
        with self.driver.session() as session:
            result = session.run(
                """
                MATCH (e:Entity)
                WHERE toLower(e.name) = toLower($name)
                RETURN e.name AS name, e.entity_type AS type,
                       e.mention_count AS mentions
                LIMIT 1
                """,
                name=name,
            )
            record = result.single()
            if record:
                return dict(record)
        return None

    def get_entity_context(
        self, entity_names: List[str], max_hops: int = 2
    ) -> str:
        """Traverse the graph from given entities and return a natural-language context summary.

        Uses Redis caching to avoid repeated graph traversals.

        Limited to 2 hops to avoid context explosion.
        Prioritises paths through Document nodes.

        Args:
            entity_names: List of entity names to look up.
            max_hops: Maximum traversal depth.

        Returns:
            Natural-language paragraph summarising graph relationships.
        """
        from core.redis_client import redis_client

        context_parts = []
        TTL_SECONDS = 6 * 60 * 60  # 6 hours

        with self.driver.session() as session:
            for name in entity_names:
                # Check cache first
                cache_key = f"neo4j:entity:{name.lower()}:{max_hops}"
                cached = redis_client.get(cache_key)

                if cached:
                    logger.info(f"Neo4j cache HIT for entity: {name}")
                    context_parts.append(cached)
                    continue

                logger.info(f"Neo4j cache MISS for entity: {name}")
                # Cache miss - perform graph traversal
                entity_context = ""
                try:
                    result = session.run(
                        """
                        MATCH (e:Entity)-[r]-(related)
                        WHERE toLower(e.name) = toLower($name)
                        RETURN e.name AS source, type(r) AS relationship,
                               related.name AS target, labels(related) AS target_labels,
                               related.entity_type AS target_type
                        LIMIT 20
                        """,
                        name=name,
                    )

                    relationships = []
                    for record in result:
                        rel_type = record["relationship"].replace("_", " ").lower()
                        target = record["target"]
                        if target:
                            relationships.append(f"{rel_type} {target}")

                    if relationships:
                        entity_context = f"{name} is {'; '.join(relationships[:5])}"

                    # 2-hop traversal
                    hop2_parts = []
                    if max_hops >= 2:
                        result2 = session.run(
                            """
                            MATCH (e:Entity)-[r1]-(mid)-[r2]-(far)
                            WHERE toLower(e.name) = toLower($name)
                            AND mid <> e AND far <> e
                            RETURN mid.name AS through, type(r1) AS rel1,
                                   type(r2) AS rel2, far.name AS target
                            LIMIT 10
                            """,
                            name=name,
                        )
                        for record in result2:
                            through = record["through"]
                            target = record["target"]
                            if through and target:
                                hop2_parts.append(
                                    f"{name} is connected to {target} through {through}"
                                )

                    # Combine 1-hop and 2-hop context
                    if hop2_parts:
                        entity_context += "; " + "; ".join(hop2_parts[:3])

                    # Cache the result
                    if entity_context:
                        redis_client.set(cache_key, entity_context, TTL_SECONDS)
                        context_parts.append(entity_context)

                except Exception as e:
                    logger.error(f"Graph traversal failed for '{name}': {e}")

        if not context_parts:
            return ""

        return ". ".join(context_parts[:10]) + "."

    def get_all_entities(
        self, skip: int = 0, limit: int = 50
    ) -> List[Dict]:
        """Return a paginated list of all entities."""
        with self.driver.session() as session:
            result = session.run(
                """
                MATCH (e:Entity)
                RETURN e.name AS name, e.entity_type AS type,
                       e.mention_count AS mentions
                ORDER BY e.mention_count DESC
                SKIP $skip LIMIT $limit
                """,
                skip=skip,
                limit=limit,
            )
            return [dict(record) for record in result]

    def get_entity_with_relationships(
        self, entity_name: str
    ) -> Optional[Dict]:
        """Return an entity and its direct relationships."""
        entity = self.find_entity(entity_name)
        if not entity:
            return None

        relationships = []
        with self.driver.session() as session:
            result = session.run(
                """
                MATCH (e:Entity)-[r]-(related)
                WHERE toLower(e.name) = toLower($name)
                RETURN type(r) AS relationship, related.name AS target,
                       related.entity_type AS target_type
                """,
                name=entity_name,
            )
            for record in result:
                relationships.append({
                    "relationship": record["relationship"],
                    "target": record["target"],
                    "target_type": record["target_type"],
                })

        return {"entity": entity, "relationships": relationships}

    def delete_document_entities(self, document_id: str) -> None:
        """Remove all entities and relationships sourced from a specific document."""
        with self.driver.session() as session:
            try:
                session.run(
                    """
                    MATCH (d:Document {document_id: $doc_id})
                    DETACH DELETE d
                    """,
                    doc_id=document_id,
                )
            except Exception as e:
                logger.error(f"Failed to delete document entities: {e}")

    def get_overview_graph(self, limit: int = 50) -> Dict:
        """Return the top N most-connected entities and inter-entity relationships."""
        nodes_map: Dict = {}
        edges: List[Dict] = []
        edge_ids: set = set()

        with self.driver.session() as session:
            result = session.run(
                """
                MATCH (e:Entity)
                RETURN e.name AS name, e.entity_type AS type,
                       coalesce(e.mention_count, 1) AS count
                ORDER BY count DESC
                LIMIT $limit
                """,
                limit=limit,
            )
            for record in result:
                name = record["name"]
                if not name:
                    continue
                nodes_map[name] = {
                    "id": name,
                    "label": name,
                    "group": record["type"] or "Concept",
                    "title": f'{record["type"] or "Entity"} · {record["count"]} mentions',
                    "value": max(int(record["count"] or 1), 1),
                }

            if not nodes_map:
                return {"nodes": [], "edges": [], "focal": None}

            top_names = list(nodes_map.keys())
            rels_result = session.run(
                """
                MATCH (a:Entity)-[r]-(b:Entity)
                WHERE a.name IN $names AND b.name IN $names
                  AND type(r) <> 'MENTIONED_IN'
                RETURN a.name AS source, b.name AS target, type(r) AS rel_type
                LIMIT 500
                """,
                names=top_names,
            )
            for record in rels_result:
                source = record["source"]
                target = record["target"]
                rel_type = record["rel_type"]
                if not source or not target:
                    continue
                edge_key = tuple(sorted([source, target]) + [rel_type])
                if edge_key not in edge_ids:
                    edge_ids.add(edge_key)
                    edges.append({
                        "from": source,
                        "to": target,
                        "label": rel_type,
                        "title": rel_type.replace("_", " "),
                    })

        return {"nodes": list(nodes_map.values()), "edges": edges, "focal": None}

    def search_entity_graph(
        self,
        entity: str,
        depth: int = 2,
        node_types: Optional[List[str]] = None,
        rel_types: Optional[List[str]] = None,
    ) -> Dict:
        """Return a subgraph centred on the named entity up to `depth` hops away."""
        depth = min(max(depth, 1), 3)
        nodes_map: Dict = {}
        edges: List[Dict] = []
        edge_ids: set = set()

        def _add_node(name: str, etype: str, count: int, is_focal: bool = False) -> bool:
            if not name or name in nodes_map:
                return name in nodes_map
            if node_types and etype not in node_types:
                return False
            node: Dict = {
                "id": name,
                "label": name,
                "group": etype or "Concept",
                "title": f'{etype or "Entity"} · {count or 0} mentions',
                "value": max(int(count or 1), 1),
            }
            if is_focal:
                node["color"] = {
                    "border": "#c2410c",
                    "background": "#fed7aa",
                    "highlight": {"border": "#9a3412", "background": "#fdba74"},
                }
            nodes_map[name] = node
            return True

        def _add_edge(from_name: str, to_name: str, rtype: str) -> None:
            if rel_types and rtype not in rel_types:
                return
            edge_key = tuple(sorted([from_name, to_name]) + [rtype])
            if edge_key not in edge_ids:
                edge_ids.add(edge_key)
                edges.append({
                    "from": from_name,
                    "to": to_name,
                    "label": rtype,
                    "title": rtype.replace("_", " "),
                })

        with self.driver.session() as session:
            focal_rec = session.run(
                """
                MATCH (e:Entity)
                WHERE toLower(e.name) CONTAINS toLower($name)
                RETURN e.name AS name, e.entity_type AS type,
                       coalesce(e.mention_count, 1) AS count
                ORDER BY count DESC LIMIT 1
                """,
                name=entity,
            ).single()

            if not focal_rec:
                return {"nodes": [], "edges": [], "focal": None}

            focal_name = focal_rec["name"]
            _add_node(focal_name, focal_rec["type"], focal_rec["count"], is_focal=True)

            frontier = {focal_name}
            visited = {focal_name}

            for _ in range(depth):
                if not frontier:
                    break
                result = session.run(
                    """
                    MATCH (e:Entity)-[r]-(related:Entity)
                    WHERE e.name IN $names AND type(r) <> 'MENTIONED_IN'
                    RETURN e.name AS source, related.name AS target,
                           related.entity_type AS target_type,
                           coalesce(related.mention_count, 1) AS target_count,
                           type(r) AS rel_type
                    LIMIT 200
                    """,
                    names=list(frontier),
                )
                new_frontier: set = set()
                for rec in result:
                    source = rec["source"]
                    target = rec["target"]
                    rtype = rec["rel_type"]
                    if not target:
                        continue
                    if target not in visited:
                        added = _add_node(target, rec["target_type"], rec["target_count"])
                        if added:
                            new_frontier.add(target)
                    if source in nodes_map and target in nodes_map:
                        _add_edge(source, target, rtype)

                visited.update(new_frontier)
                frontier = new_frontier

        return {
            "nodes": list(nodes_map.values()),
            "edges": edges,
            "focal": focal_name,
        }

    def get_entity_detail(self, entity_name: str) -> Optional[Dict]:
        """Return entity details: properties, direct relationships, source document IDs."""
        with self.driver.session() as session:
            entity_rec = session.run(
                """
                MATCH (e:Entity {name: $name})
                RETURN e.name AS name, e.entity_type AS type,
                       coalesce(e.mention_count, 0) AS count
                """,
                name=entity_name,
            ).single()

            if not entity_rec:
                return None

            rels_result = session.run(
                """
                MATCH (e:Entity {name: $name})-[r]-(related:Entity)
                WHERE type(r) <> 'MENTIONED_IN'
                RETURN related.name AS target, related.entity_type AS target_type,
                       type(r) AS rel_type
                LIMIT 50
                """,
                name=entity_name,
            )
            relationships = [
                {
                    "target": rec["target"],
                    "target_type": rec["target_type"],
                    "relationship": rec["rel_type"],
                }
                for rec in rels_result
                if rec["target"]
            ]

            docs_result = session.run(
                """
                MATCH (e:Entity {name: $name})-[:MENTIONED_IN]->(d:Document)
                RETURN d.document_id AS document_id
                LIMIT 20
                """,
                name=entity_name,
            )
            doc_ids = [rec["document_id"] for rec in docs_result if rec["document_id"]]

        return {
            "name": entity_rec["name"],
            "type": entity_rec["type"],
            "mention_count": entity_rec["count"],
            "relationships": relationships,
            "source_document_ids": doc_ids,
        }

    def get_entities_by_document(self, document_id: str) -> List[Dict[str, Any]]:
        """Fetch all entities extracted from a specific document.

        Returns a list of dicts with: name, type (entity_type)
        """
        entities = []
        try:
            with self.driver.session() as session:
                result = session.run(
                    """
                    MATCH (e:Entity)-[:MENTIONED_IN]->(d:Document {document_id: $doc_id})
                    RETURN e.name AS name, e.entity_type AS type
                    ORDER BY e.name
                    """,
                    doc_id=document_id,
                )
                for record in result:
                    entities.append({
                        "name": record["name"],
                        "type": record["type"],
                    })
        except Exception as e:
            logger.warning(f"Failed to fetch entities for document {document_id}: {e}")
        return entities


# ── Module-level singleton ───────────────────────────────────
neo4j_client = Neo4jClient()
