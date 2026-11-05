"""Durable singleton launch fence; no automatic installation provisioning."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0011_docx_analysis_supervisor"
down_revision = "0010_docx_analysis_storage"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "docx_analysis_supervisor",
        sa.Column("slot_key", sa.SmallInteger(), nullable=False, autoincrement=False),
        sa.Column("revision", sa.BigInteger(), nullable=False, server_default=sa.text("1")),
        sa.Column("phase", sa.Text(), nullable=False, server_default=sa.text("'unprovisioned'")),
        *(
            sa.Column(name, postgresql.UUID(as_uuid=True), nullable=True)
            for name in (
                "installation_id",
                "owner_epoch",
                "launch_id",
                "document_id",
                "run_id",
                "attempt_id",
                "worker_instance_id",
            )
        ),
        sa.Column("claim_fence", sa.SmallInteger(), nullable=True),
        sa.PrimaryKeyConstraint("slot_key", name="pk_docx_analysis_supervisor"),
        sa.CheckConstraint("slot_key = 1", name="ck_dasv_singleton"),
        sa.CheckConstraint("revision > 0", name="ck_dasv_revision"),
        sa.CheckConstraint(
            "(phase = 'unprovisioned' AND installation_id IS NULL AND owner_epoch IS NULL "
            "AND launch_id IS NULL AND document_id IS NULL AND run_id IS NULL "
            "AND attempt_id IS NULL AND worker_instance_id IS NULL AND claim_fence IS NULL) OR "
            "(phase = 'clean' AND installation_id IS NOT NULL "
            "AND launch_id IS NULL AND document_id IS NULL AND run_id IS NULL "
            "AND attempt_id IS NULL AND worker_instance_id IS NULL AND claim_fence IS NULL) OR "
            "(phase IN ('armed', 'drained') AND installation_id IS NOT NULL "
            "AND owner_epoch IS NOT NULL AND launch_id IS NOT NULL AND document_id IS NOT NULL "
            "AND run_id IS NOT NULL AND attempt_id IS NOT NULL AND worker_instance_id IS NOT NULL "
            "AND claim_fence IS NOT NULL AND claim_fence = 1)",
            name="ck_dasv_shape",
        ),
    )
    op.execute("INSERT INTO docx_analysis_supervisor(slot_key) VALUES (1)")


def downgrade():
    conn = op.get_bind()
    conn.exec_driver_sql("LOCK TABLE docx_analysis_supervisor IN ACCESS EXCLUSIVE MODE")
    counts = conn.exec_driver_sql(
        "SELECT count(*),count(*) FILTER (WHERE slot_key=1 AND revision>0 "
        "AND phase='unprovisioned' AND installation_id IS NULL AND owner_epoch IS NULL "
        "AND launch_id IS NULL AND document_id IS NULL AND run_id IS NULL "
        "AND attempt_id IS NULL AND worker_instance_id IS NULL AND claim_fence IS NULL) "
        "FROM docx_analysis_supervisor"
    ).one()
    if counts != (1, 1):
        raise RuntimeError("Cannot downgrade a provisioned analysis supervisor")
    op.drop_table("docx_analysis_supervisor")
