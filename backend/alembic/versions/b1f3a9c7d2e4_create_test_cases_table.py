"""create test_cases table

Revision ID: b1f3a9c7d2e4
Revises:
Create Date: 2026-07-28 00:00:00.000000

NOTE: 이 리비전은 `alembic revision --autogenerate` 실행 환경(Bash)이 없어
`app/models/test_case.py`의 컬럼 정의를 그대로 옮겨 수기로 작성했다.
backend-agent가 다음 웨이브에서 `alembic upgrade head`로 실제 적용/검증하고,
필요 시 autogenerate로 diff가 없는지(모델과 일치하는지) 재확인하길 권장한다.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b1f3a9c7d2e4"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "test_cases",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "category",
            sa.Enum("volte", "mcptt", name="testcasecategory", native_enum=False, length=16),
            nullable=False,
        ),
        sa.Column(
            "test_type",
            sa.Enum(
                "basic_call",
                "performance",
                "abnormal",
                name="testcasetype",
                native_enum=False,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("config_ref", sa.String(length=512), nullable=False),
        sa.Column("protocol_params", sa.JSON(), nullable=False),
        sa.Column("pass_criteria", sa.JSON(), nullable=False),
        sa.Column("yaml_path", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_test_cases_name"), "test_cases", ["name"], unique=True)
    op.create_index(op.f("ix_test_cases_category"), "test_cases", ["category"], unique=False)
    op.create_index(op.f("ix_test_cases_test_type"), "test_cases", ["test_type"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_test_cases_test_type"), table_name="test_cases")
    op.drop_index(op.f("ix_test_cases_category"), table_name="test_cases")
    op.drop_index(op.f("ix_test_cases_name"), table_name="test_cases")
    op.drop_table("test_cases")
