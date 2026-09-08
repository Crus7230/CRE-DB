from pathlib import Path
import sqlite3
import unittest


ROOT = Path(__file__).parents[1]
SQLITE = ROOT / "db/v2/migrations/3.5.0_institutional_selection_assessment.sqlite.sql"
POSTGRES = ROOT / "db/v2/migrations/3.5.0_institutional_selection_assessment.sql"
SCHEMA = ROOT / "db/v2/schema.sql"
SEED = ROOT / "db/v2/seed.sql"


def base(version: str = "3.5.0") -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.executescript(f"""
      CREATE TABLE schema_meta(schema_key TEXT PRIMARY KEY,schema_value TEXT NOT NULL);
      INSERT INTO schema_meta VALUES('schema_version','{version}');
      CREATE TABLE predicate_definitions(
        predicate_code TEXT PRIMARY KEY,name_ko TEXT,subject_scope TEXT,value_kind TEXT,
        default_unit_code TEXT,is_multivalued INTEGER,description TEXT
      );
      CREATE TABLE claim_role_definitions(
        role_code TEXT PRIMARY KEY,name_ko TEXT,allowed_kind TEXT,description TEXT
      );
      CREATE TABLE claims(
        claim_id TEXT PRIMARY KEY,predicate_code TEXT,review_status TEXT,verification_status TEXT
      );
      CREATE TABLE claim_arguments(
        claim_argument_id TEXT PRIMARY KEY,claim_id TEXT,role_code TEXT,text_value TEXT
      );
    """)
    return connection


class InstitutionalSelectionAssessmentSchemaTest(unittest.TestCase):
    def test_additive_migrations_define_bid_and_deployment_inference_without_promoting_selection(self) -> None:
        sqlite_sql = SQLITE.read_text(encoding="utf-8")
        postgres_sql = POSTGRES.read_text(encoding="utf-8")
        for token in (
            "LP_MANDATE_MANAGER_BID_PARTICIPANT",
            "LP_MANDATE_MANAGER_INFERRED_FROM_DEPLOYMENT",
            "MANDATE_CODE",
            "MANDATE_TRACK",
            "FOLLOW_UP_ACTION",
            "FUNDING_BASIS",
            "LINKED_VEHICLE",
            "LINKED_DEAL",
            "CONTRADICTION_NOTE",
            "INFERENCE_RULE_VERSION",
        ):
            self.assertIn(token, sqlite_sql)
            self.assertIn(token, postgres_sql)
        self.assertNotIn("insert into lp_mandate_selections", sqlite_sql.lower())
        self.assertNotIn("insert into market_intelligence.lp_mandate_selections", postgres_sql.lower())

    def test_sqlite_migration_is_version_gated_and_additive(self) -> None:
        connection = base()
        try:
            connection.executescript(SQLITE.read_text(encoding="utf-8"))
            predicates = {row[0] for row in connection.execute("select predicate_code from predicate_definitions")}
            roles = {row[0] for row in connection.execute("select role_code from claim_role_definitions")}
            self.assertIn("LP_MANDATE_MANAGER_BID_PARTICIPANT", predicates)
            self.assertIn("LP_MANDATE_MANAGER_INFERRED_FROM_DEPLOYMENT", predicates)
            self.assertLessEqual({"MANDATE_CODE", "FOLLOW_UP_ACTION", "FUNDING_BASIS", "LINKED_VEHICLE", "LINKED_DEAL"}, roles)
            self.assertEqual(
                "3.5.0",
                connection.execute("select schema_value from schema_meta where schema_key='schema_version'").fetchone()[0],
            )
        finally:
            connection.close()

        wrong = base("WRONG")
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                wrong.executescript(SQLITE.read_text(encoding="utf-8"))
        finally:
            wrong.close()

    def test_fresh_schema_and_seed_contain_assessment_contract(self) -> None:
        schema = SCHEMA.read_text(encoding="utf-8")
        seed = SEED.read_text(encoding="utf-8")
        self.assertIn("ix_claims_lp_manager_assessment", schema)
        self.assertIn("ix_claim_arguments_mandate_assessment", schema)
        self.assertIn("LP_MANDATE_MANAGER_BID_PARTICIPANT", seed)
        self.assertIn("LP_MANDATE_MANAGER_INFERRED_FROM_DEPLOYMENT", seed)
