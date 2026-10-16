"""Ordered SQLite schema migrations for existing Cathedra office databases."""

from collections.abc import Callable

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

from app.salary_scale import RANK_TO_GRADE, grade_for_rank, normalize_grade, salary_for

Migration = tuple[int, str, Callable[[Connection], None]]


def _column_names(connection: Connection, table_name: str) -> set[str]:
    return {
        column["name"]
        for column in connection.execute(text(f"PRAGMA table_info({table_name})")).mappings()
    }


def migrate_current_schema(connection: Connection) -> None:
    for table_name in ("faculty_profiles", "faculty_workloads"):
        if "data_source" not in _column_names(connection, table_name):
            connection.execute(
                text(
                    f"ALTER TABLE {table_name} ADD COLUMN data_source VARCHAR(30) NOT NULL DEFAULT 'Cathedra'"
                )
            )

    faculty_columns = _column_names(connection, "faculty_profiles")
    if "monthly_salary" not in faculty_columns:
        connection.execute(text("ALTER TABLE faculty_profiles ADD COLUMN monthly_salary FLOAT"))
    if "salary_step" not in faculty_columns:
        connection.execute(
            text("ALTER TABLE faculty_profiles ADD COLUMN salary_step INTEGER NOT NULL DEFAULT 1")
        )

    workload_columns = _column_names(connection, "faculty_workloads")
    for column_name, column_type, default_value in (
        ("compensation_category", "VARCHAR(30) NOT NULL", "'Regular Faculty'"),
        ("highest_qualification", "VARCHAR(30)", "NULL"),
        ("professional_qualification", "VARCHAR(30)", "NULL"),
    ):
        if column_name not in workload_columns:
            connection.execute(
                text(
                    f"ALTER TABLE faculty_workloads ADD COLUMN {column_name} {column_type} "
                    f"DEFAULT {default_value}"
                )
            )

    workload_cost_columns = _column_names(connection, "workload_cost_settings")
    for column_name, column_type, default_value in (
        ("internal_monthly_equivalent_hours", "FLOAT", 173.33),
        ("external_base_hourly_rate", "FLOAT", 273.77),
        ("external_masters_increment", "FLOAT", 0),
        ("external_doctorate_increment", "FLOAT", 0),
        ("external_doctor_increment", "FLOAT", 0),
        ("external_lawyer_increment", "FLOAT", 0),
        ("first_semester_weeks", "INTEGER", 18),
        ("second_semester_weeks", "INTEGER", 18),
        ("summer_weeks", "INTEGER", 0),
    ):
        if column_name not in workload_cost_columns:
            connection.execute(
                text(
                    f"ALTER TABLE workload_cost_settings ADD COLUMN {column_name} "
                    f"{column_type} NOT NULL DEFAULT {default_value}"
                )
            )

    for rank, grade_number in RANK_TO_GRADE.items():
        salary_grade = f"SG {grade_number}"
        connection.execute(
            text(
                "UPDATE faculty_profiles SET salary_grade = :salary_grade "
                "WHERE trim(rank) = :rank AND (salary_grade IS NULL OR trim(salary_grade) = '')"
            ),
            {"salary_grade": salary_grade, "rank": rank},
        )
        connection.execute(
            text(
                "UPDATE faculty_profiles SET monthly_salary = :monthly_salary "
                "WHERE salary_grade = :salary_grade AND monthly_salary IS NULL"
            ),
            {"monthly_salary": salary_for(salary_grade, 1), "salary_grade": salary_grade},
        )

    profiles = connection.execute(
        text("SELECT id, rank, salary_grade, salary_step, monthly_salary FROM faculty_profiles")
    ).mappings()
    for profile in profiles:
        salary_grade = grade_for_rank(profile["rank"]) or normalize_grade(profile["salary_grade"])
        if salary_grade is None:
            continue
        salary_step = profile["salary_step"] or 1
        monthly_salary = profile["monthly_salary"] or salary_for(salary_grade, salary_step)
        connection.execute(
            text(
                "UPDATE faculty_profiles SET salary_grade = :salary_grade, "
                "salary_step = :salary_step, monthly_salary = :monthly_salary WHERE id = :profile_id"
            ),
            {
                "profile_id": profile["id"],
                "salary_grade": salary_grade,
                "salary_step": salary_step,
                "monthly_salary": monthly_salary,
            },
        )

    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_faculty_workloads_period_faculty ON faculty_workloads (academic_year, term, faculty_profile_id)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_activity_events_created_id ON activity_events (created_at, id)"
        )
    )
    connection.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_faculty_profiles_identity ON faculty_profiles (name, college, department)"
        )
    )
    connection.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_faculty_workloads_period ON faculty_workloads (faculty_profile_id, academic_year, term)"
        )
    )


def migrate_workload_approval_workflow(connection: Connection) -> None:
    workload_columns = _column_names(connection, "faculty_workloads")
    for column_name, column_type in (
        ("workflow_status", "VARCHAR(20) NOT NULL DEFAULT 'Draft'"),
        ("reviewed_at", "DATETIME"),
        ("reviewed_by", "VARCHAR(80)"),
        ("approved_at", "DATETIME"),
        ("approved_by", "VARCHAR(80)"),
        ("approval_snapshot", "TEXT"),
        ("reopened_at", "DATETIME"),
        ("reopened_by", "VARCHAR(80)"),
        ("reopen_reason", "TEXT"),
    ):
        if column_name not in workload_columns:
            connection.execute(
                text(f"ALTER TABLE faculty_workloads ADD COLUMN {column_name} {column_type}")
            )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_faculty_workloads_workflow_status ON faculty_workloads (workflow_status)"
        )
    )


def migrate_retired_feature_step(connection: Connection) -> None:
    pass


def migrate_standard_teaching_weeks(connection: Connection) -> None:
    for column, weeks in (
        ("first_semester_weeks", 18),
        ("second_semester_weeks", 18),
        ("summer_weeks", 6),
    ):
        connection.execute(
            text(
                f"UPDATE workload_cost_settings SET {column} = :weeks "
                f"WHERE {column} IS NULL OR {column} = 0"
            ),
            {"weeks": weeks},
        )


def migrate_workload_source_values(connection: Connection) -> None:
    for table, column, kind in (
        ("faculty_profiles", "salary_source", "TEXT"),
        ("faculty_workloads", "imported_overload_hours", "FLOAT"),
        ("faculty_workloads", "import_provenance", "TEXT"),
    ):
        if column not in _column_names(connection, table):
            connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {kind}"))


def migrate_other_professional_credential(connection: Connection) -> None:
    if "professional_qualification_other" not in _column_names(connection, "faculty_workloads"):
        connection.execute(
            text(
                "ALTER TABLE faculty_workloads ADD COLUMN professional_qualification_other VARCHAR(200)"
            )
        )


def migrate_qualification_rate_drafts(connection: Connection) -> None:
    connection.execute(
        text(
            "CREATE TABLE IF NOT EXISTS qualification_rate_drafts (id INTEGER PRIMARY KEY, revision INTEGER NOT NULL, combination_rule VARCHAR(30) NOT NULL, rates_json TEXT NOT NULL, updated_by VARCHAR(80) NOT NULL, updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        )
    )


def migrate_approval_revisions(connection: Connection) -> None:
    connection.execute(
        text(
            "CREATE TABLE IF NOT EXISTS workload_approval_revisions (id INTEGER PRIMARY KEY, workload_id INTEGER NOT NULL REFERENCES faculty_workloads(id), snapshot TEXT NOT NULL, approved_by VARCHAR(80) NOT NULL, approved_at DATETIME NOT NULL)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_workload_approval_revisions_workload_id ON workload_approval_revisions (workload_id)"
        )
    )
    connection.execute(
        text(
            "INSERT INTO workload_approval_revisions (workload_id, snapshot, approved_by, approved_at) SELECT id, approval_snapshot, COALESCE(approved_by, 'Legacy approval'), COALESCE(approved_at, CURRENT_TIMESTAMP) FROM faculty_workloads WHERE approval_snapshot IS NOT NULL AND approval_snapshot != '' AND NOT EXISTS (SELECT 1 FROM workload_approval_revisions WHERE workload_id = faculty_workloads.id)"
        )
    )


def migrate_record_revisions(connection: Connection) -> None:
    for table_name in ("faculty_profiles", "faculty_workloads", "workload_cost_settings"):
        if "revision" not in _column_names(connection, table_name):
            connection.execute(
                text(f"ALTER TABLE {table_name} ADD COLUMN revision INTEGER NOT NULL DEFAULT 0")
            )


def migrate_account_lifecycle(connection: Connection) -> None:
    for column_name, definition in (
        ("is_active", "BOOLEAN NOT NULL DEFAULT 1"),
        ("must_change_password", "BOOLEAN NOT NULL DEFAULT 0"),
    ):
        if column_name not in _column_names(connection, "local_users"):
            connection.execute(
                text(f"ALTER TABLE local_users ADD COLUMN {column_name} {definition}")
            )


def migrate_structured_activity(connection: Connection) -> None:
    for column_name, definition in (
        ("record_type", "VARCHAR(80)"),
        ("record_id", "INTEGER"),
        ("operation", "VARCHAR(40)"),
        ("changed_fields", "TEXT"),
    ):
        if column_name not in _column_names(connection, "activity_events"):
            connection.execute(
                text(f"ALTER TABLE activity_events ADD COLUMN {column_name} {definition}")
            )


def migrate_faculty_campus(connection: Connection) -> None:
    if "campus" not in _column_names(connection, "faculty_profiles"):
        connection.execute(text("ALTER TABLE faculty_profiles ADD COLUMN campus VARCHAR(80)"))


def migrate_semester_overload_budgets(connection: Connection) -> None:
    connection.execute(
        text(
            "CREATE TABLE IF NOT EXISTS semester_overload_budgets (id INTEGER PRIMARY KEY, academic_year VARCHAR(20) NOT NULL, term VARCHAR(40) NOT NULL, amount_centavos INTEGER NOT NULL CHECK (amount_centavos > 0), UNIQUE (academic_year, term))"
        )
    )
    connection.execute(
        text(
            "INSERT INTO semester_overload_budgets (academic_year, term, amount_centavos) SELECT '2026-2027', 'First Semester', 1607680424 FROM projection_settings WHERE id = 1 AND academic_year = '2026-2027' AND term IN ('First Semester', '1st Semester') AND NOT EXISTS (SELECT 1 FROM semester_overload_budgets WHERE academic_year = '2026-2027' AND term = 'First Semester')"
        )
    )


def migrate_faculty_no_teaching_confirmations(connection: Connection) -> None:
    connection.execute(
        text(
            "CREATE TABLE IF NOT EXISTS faculty_no_teaching_confirmations (id INTEGER PRIMARY KEY, faculty_id INTEGER NOT NULL REFERENCES faculty_profiles(id), academic_year VARCHAR(20) NOT NULL, term VARCHAR(40) NOT NULL, confirmed_by VARCHAR(100) NOT NULL, confirmed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE (faculty_id, academic_year, term))"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_faculty_no_teaching_confirmations_faculty_id ON faculty_no_teaching_confirmations (faculty_id)"
        )
    )


def migrate_confirmation_period_index(connection: Connection) -> None:
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_faculty_no_teaching_confirmations_period_faculty "
            "ON faculty_no_teaching_confirmations (academic_year, term, faculty_id)"
        )
    )


def migrate_faculty_profile_roster_fields(connection: Connection) -> None:
    definitions = (
        ("service_status", "VARCHAR(20) NOT NULL DEFAULT 'Active'"),
        ("item_number", "VARCHAR(100)"),
        ("bachelors_degree", "VARCHAR(300)"),
        ("masters_degree", "VARCHAR(300)"),
        ("doctoral_degree", "VARCHAR(300)"),
        ("eligibility", "VARCHAR(300)"),
        ("remarks", "TEXT"),
    )
    existing = _column_names(connection, "faculty_profiles")
    for name, definition in definitions:
        if name not in existing:
            connection.execute(text(f"ALTER TABLE faculty_profiles ADD COLUMN {name} {definition}"))
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_faculty_profiles_service_status ON faculty_profiles (service_status)"
        )
    )


def migrate_faculty_status_effective_date(connection: Connection) -> None:
    if "service_status_effective_date" not in _column_names(connection, "faculty_profiles"):
        connection.execute(
            text("ALTER TABLE faculty_profiles ADD COLUMN service_status_effective_date DATE")
        )


def migrate_saved_projections(connection: Connection) -> None:
    connection.execute(
        text(
            "CREATE TABLE IF NOT EXISTS saved_projections ("
            "id INTEGER PRIMARY KEY, academic_year VARCHAR(20) NOT NULL, term VARCHAR(40), "
            "period VARCHAR(20) NOT NULL, created_by VARCHAR(80) NOT NULL, "
            "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, projection_json TEXT NOT NULL)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_saved_projections_period "
            "ON saved_projections (academic_year, term, created_at)"
        )
    )


def migrate_semester_closeout_estimates(connection: Connection) -> None:
    connection.execute(
        text(
            "CREATE TABLE IF NOT EXISTS semester_closeout_estimates ("
            "id INTEGER PRIMARY KEY, academic_year VARCHAR(20) NOT NULL, "
            "term VARCHAR(40) NOT NULL, projection_id INTEGER NOT NULL UNIQUE "
            "REFERENCES saved_projections(id), UNIQUE (academic_year, term))"
        )
    )


RETIRED_TABLES = (
    "scholar_requirements",
    "fsdp_participations",
    "scholar_assignments",
    "fsdp_records",
    "scholars",
    "programs",
    "assignments",
)


def migrate_remove_retired_feature_tables(connection: Connection) -> None:
    existing = set(inspect(connection).get_table_names())
    populated = [
        table
        for table in RETIRED_TABLES
        if table in existing
        and connection.exec_driver_sql(f'SELECT COUNT(*) FROM "{table}"').scalar()
    ]
    if populated:
        raise RuntimeError(
            "Retired feature tables contain records. Preserve and export them before cleanup: "
            + ", ".join(populated)
        )
    for table in RETIRED_TABLES:
        if table in existing:
            connection.exec_driver_sql(f'DROP TABLE "{table}"')


def migrate_shared_setting_revisions(connection: Connection) -> None:
    for table in ("projection_settings", "semester_overload_budgets"):
        columns = {column["name"] for column in inspect(connection).get_columns(table)}
        if "revision" not in columns:
            connection.exec_driver_sql(
                f'ALTER TABLE "{table}" ADD COLUMN revision INTEGER NOT NULL DEFAULT 0'
            )


def migrate_deleted_resource_revisions(connection: Connection) -> None:
    connection.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS resource_revisions (resource TEXT NOT NULL, "
        "record_key TEXT NOT NULL, revision INTEGER NOT NULL, PRIMARY KEY(resource, record_key))"
    )
    for table in ("faculty_profiles", "faculty_workloads", "semester_overload_budgets"):
        key_new = (
            "NEW.academic_year || ':' || NEW.term"
            if table == "semester_overload_budgets"
            else "CAST(NEW.id AS TEXT)"
        )
        key_old = (
            "OLD.academic_year || ':' || OLD.term"
            if table == "semester_overload_budgets"
            else "CAST(OLD.id AS TEXT)"
        )
        connection.exec_driver_sql(f"""
            CREATE TRIGGER IF NOT EXISTS remember_deleted_{table} AFTER DELETE ON {table}
            BEGIN
                INSERT INTO resource_revisions(resource, record_key, revision)
                VALUES('{table}', {key_old}, OLD.revision)
                ON CONFLICT(resource, record_key) DO UPDATE
                SET revision=MAX(resource_revisions.revision, excluded.revision);
            END
        """)
        connection.exec_driver_sql(f"""
            CREATE TRIGGER IF NOT EXISTS preserve_recreated_{table} AFTER INSERT ON {table}
            WHEN EXISTS(SELECT 1 FROM resource_revisions WHERE resource='{table}' AND record_key={key_new})
            BEGIN
                UPDATE {table} SET revision=MAX(NEW.revision,
                    (SELECT revision + 1 FROM resource_revisions WHERE resource='{table}' AND record_key={key_new}))
                WHERE id=NEW.id;
            END
        """)


def migrate_case_insensitive_usernames(connection: Connection) -> None:
    collisions = connection.exec_driver_sql(
        "SELECT COUNT(*) FROM (SELECT lower(username) FROM local_users "
        "GROUP BY lower(username) HAVING COUNT(*) > 1)"
    ).scalar_one()
    if collisions:
        raise RuntimeError(
            "Local account names conflict under case-insensitive login. "
            "Preserve a backup and have an administrator resolve the conflicting accounts "
            "before upgrading; no accounts have been renamed or merged."
        )
    connection.exec_driver_sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_local_users_login_name "
        "ON local_users (lower(username))"
    )


MIGRATIONS: list[Migration] = [
    (1, "current-schema", migrate_current_schema),
    (2, "workload-approval-workflow", migrate_workload_approval_workflow),
    (3, "scholar-requirements", migrate_retired_feature_step),
    (4, "standard-teaching-weeks", migrate_standard_teaching_weeks),
    (5, "workload-source-values", migrate_workload_source_values),
    (6, "other-professional-credential", migrate_other_professional_credential),
    (7, "qualification-rate-drafts", migrate_qualification_rate_drafts),
    (8, "participation-institution", migrate_retired_feature_step),
    (9, "approval-revisions", migrate_approval_revisions),
    (10, "record-revisions", migrate_record_revisions),
    (11, "account-lifecycle", migrate_account_lifecycle),
    (12, "structured-activity", migrate_structured_activity),
    (13, "faculty-campus", migrate_faculty_campus),
    (14, "semester-overload-budgets", migrate_semester_overload_budgets),
    (15, "faculty-no-teaching-confirmations", migrate_faculty_no_teaching_confirmations),
    (16, "confirmation-period-index", migrate_confirmation_period_index),
    (17, "faculty-profile-roster-fields", migrate_faculty_profile_roster_fields),
    (18, "faculty-status-effective-date", migrate_faculty_status_effective_date),
    (19, "saved-projections", migrate_saved_projections),
    (20, "semester-closeout-estimates", migrate_semester_closeout_estimates),
    (21, "remove-retired-feature-tables", migrate_remove_retired_feature_tables),
    (22, "shared-setting-revisions", migrate_shared_setting_revisions),
    (23, "deleted-resource-revisions", migrate_deleted_resource_revisions),
    (24, "case-insensitive-usernames", migrate_case_insensitive_usernames),
]


def validate_migration_history(connection: Connection) -> None:
    if not inspect(connection).has_table("schema_migrations"):
        return
    known = {version: name for version, name, _ in MIGRATIONS}
    recorded = connection.execute(text("SELECT version, name FROM schema_migrations")).all()
    for version, name in recorded:
        expected_name = known.get(version)
        if expected_name is None:
            raise RuntimeError(
                f"Database migration {version} is not supported by this Cathedra version. "
                "Open it with the matching or newer application."
            )
        if name != expected_name:
            raise RuntimeError(
                f"Database migration {version} has an unexpected name; startup is blocked."
            )


def run_migrations(connection: Connection) -> None:
    validate_migration_history(connection)
    connection.execute(
        text(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version INTEGER PRIMARY KEY, name VARCHAR(100) NOT NULL, applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        )
    )
    applied = set(connection.execute(text("SELECT version FROM schema_migrations")).scalars())
    for version, name, migrate in MIGRATIONS:
        if version in applied:
            continue
        migrate(connection)
        connection.execute(
            text("INSERT INTO schema_migrations (version, name) VALUES (:version, :name)"),
            {"version": version, "name": name},
        )
