"""Create the initial ownership, documents and version history schema."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_initial_documents"
down_revision = None
branch_labels = None
depends_on = None


def identity_columns():
    return (
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def upgrade():
    op.create_table("users", *identity_columns())
    op.create_table(
        "projects",
        *identity_columns(),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], name="fk_projects_owner"),
    )
    op.create_index("ix_projects_owner_id", "projects", ["owner_id"])
    op.create_table(
        "documents",
        *identity_columns(),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("current_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_documents_project"),
    )
    op.create_index("ix_documents_project_id", "documents", ["project_id"])
    op.create_table(
        "document_versions",
        *identity_columns(),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parent_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("content_markdown", sa.Text(), nullable=False),
        sa.Column(
            "blocks", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column(
            "provenance", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "import_omissions",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.ForeignKeyConstraint(
            ["document_id"], ["documents.id"], name="fk_document_versions_document"
        ),
        sa.UniqueConstraint("document_id", "id", name="uq_document_versions_document_id_id"),
        sa.ForeignKeyConstraint(
            ["document_id", "parent_version_id"],
            ["document_versions.document_id", "document_versions.id"],
            name="fk_document_versions_parent",
        ),
        sa.CheckConstraint("parent_version_id <> id", name="ck_document_versions_not_self_parent"),
        sa.CheckConstraint(
            "jsonb_typeof(blocks) = 'array'", name="ck_document_versions_blocks_array"
        ),
        sa.CheckConstraint(
            "jsonb_typeof(provenance) = 'object'", name="ck_document_versions_provenance_object"
        ),
        sa.CheckConstraint(
            "jsonb_typeof(import_omissions) = 'array'",
            name="ck_document_versions_import_omissions_array",
        ),
    )
    op.create_foreign_key(
        "fk_documents_current_version",
        "documents",
        "document_versions",
        ["id", "current_version_id"],
        ["document_id", "id"],
    )


def downgrade():
    op.drop_constraint("fk_documents_current_version", "documents", type_="foreignkey")
    op.drop_table("document_versions")
    op.drop_index("ix_documents_project_id", table_name="documents")
    op.drop_table("documents")
    op.drop_index("ix_projects_owner_id", table_name="projects")
    op.drop_table("projects")
    op.drop_table("users")
