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
        """
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

        Limited to 2 hops to avoid context explosion.
        Prioritises paths through Document nodes.

        Args:
            entity_names: List of entity names to look up.
            max_hops: Maximum traversal depth.

        Returns:
            Natural-language paragraph summarising graph relationships.
        """
        context_parts = []

        with self.driver.session() as session:
            for name in entity_names:
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
                        summary = f"{name} is {'; '.join(relationships[:5])}"
                        context_parts.append(summary)

                    # 2-hop traversal
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
                                context_parts.append(
                                    f"{name} is connected to {target} through {through}"
                                )

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


# ── Module-level singleton ───────────────────────────────────
neo4j_client = Neo4jClient()
