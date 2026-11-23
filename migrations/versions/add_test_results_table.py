"""Add test_results table for testing visualization.

This migration adds the test_results table. The table stores test results from manual
integration testing with a is_testing flag to distinguish from production data.

Revision ID: add_test_results_table
Revises: 4e08ede19f9f
Create Date: 2024-01-15 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'add_test_results_table'
down_revision = '4e08ede19f9f'
branch_labels = None
depends_on = None


def upgrade():
    """Create the test_results table."""
    # Create the test_types enum
    test_types_enum = postgresql.ENUM('modem', 'gps', 'collector', 'uploader', 'heartbeat', name='testtype')
    test_types_enum.create(op.get_bind())
    test_types_enum.create_type = False

    # Create the test_status enum
    test_status_enum = postgresql.ENUM('passed', 'failed', 'running', 'skipped', name='teststatus')
    test_status_enum.create(op.get_bind())
    test_status_enum.create_type = False
    
    # Create the test_results table
    op.create_table(
        'test_results',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('device_id', sa.String(), nullable=False, index=True),
        sa.Column('test_type', test_types_enum, nullable=False, index=True),
        sa.Column('status', test_status_enum, nullable=False),
        sa.Column('executed_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('is_testing', sa.Boolean(), nullable=False, server_default=sa.true(), index=True),
        sa.Column('duration_ms', sa.BigInteger(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('details', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['device_id'], ['devices.device_id'], ondelete='CASCADE'),
        comment='Stores test results from manual integration testing. Test data is marked with is_testing=True to separate from production data.'
    )


def downgrade():
    """Drop the test_results table and enums."""
    op.drop_table('test_results')
    
    # Drop enums
    test_types_enum = postgresql.ENUM(name='testtype')
    test_types_enum.drop(op.get_bind())
    
    test_status_enum = postgresql.ENUM(name='teststatus')
    test_status_enum.drop(op.get_bind())
