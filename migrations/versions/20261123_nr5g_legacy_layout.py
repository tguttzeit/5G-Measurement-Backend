"""Correct NR5G samples stored with the old shared AT+QENG column layout.

Revision ID: 20261123_nr5g_legacy_layout
Revises: 20261122_rename_waiting_mode
Create Date: 2026-11-23 12:00:00.000000

"""

import logging

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20261123_nr5g_legacy_layout"
down_revision: str | None = "20261122_rename_waiting_mode"
branch_labels: str | None = None
depends_on: str | None = None

logger = logging.getLogger("alembic.runtime.migration")

# Older firmware parsed NR5G-NSA and NR5G-SA servingcell lines with one shared column layout.
# Current firmware always reports `dl_bandwidth_index`, and AT+QSCAN samples carry no extras, so
# `scs_index` without `dl_bandwidth_index` identifies exactly the rows in the old layout. That
# also makes a second run a no-op.
OLD_LAYOUT = """
    raw_data -> 'cell_sample' -> 'vendor_specific_extras' ? 'scs_index'
    AND NOT raw_data -> 'cell_sample' -> 'vendor_specific_extras' ? 'dl_bandwidth_index'
"""

# The old `tac` held the PCI and the old `scs_index` the DL bandwidth index; the real SCS was
# never stored. The signal values were in the right place.
CORRECT_NSA = f"""
    UPDATE measurements
    SET raw_data = jsonb_set(
        raw_data,
        '{{cell_sample}}',
        raw_data -> 'cell_sample' || jsonb_build_object(
            'pci', raw_data -> 'cell_sample' -> 'tac',
            'tac', NULL,
            'vendor_specific_extras',
            raw_data -> 'cell_sample' -> 'vendor_specific_extras' || jsonb_build_object(
                'dl_bandwidth_index',
                raw_data -> 'cell_sample' -> 'vendor_specific_extras' -> 'scs_index',
                'scs_index', NULL
            )
        )
    )
    WHERE rat = 'NR5G-NSA' AND {OLD_LAYOUT}
"""

# The SA line starts with the duplex mode, so every field was read one column too early: the MCC
# sits in `mnc`, the MNC in `tac` and the PCI in `sinr`. The old `rsrp`/`rsrq` held the cell id and
# TAC, and the real signal values were never stored, so they are cleared in the JSON and in the
# columns, and the extras record why.
CORRECT_SA = f"""
    UPDATE measurements
    SET rsrp = NULL,
        rsrq = NULL,
        sinr = NULL,
        raw_data = jsonb_set(
            raw_data,
            '{{cell_sample}}',
            raw_data -> 'cell_sample' || jsonb_build_object(
                'mcc', raw_data -> 'cell_sample' -> 'mnc',
                'mnc', raw_data -> 'cell_sample' -> 'tac',
                'pci', to_jsonb(round((raw_data -> 'cell_sample' ->> 'sinr')::numeric)::integer),
                'tac', NULL,
                'cell_id', NULL,
                'rsrp', NULL,
                'rsrq', NULL,
                'sinr', NULL,
                'vendor_specific_extras',
                raw_data -> 'cell_sample' -> 'vendor_specific_extras' || jsonb_build_object(
                    'dl_bandwidth_index',
                    raw_data -> 'cell_sample' -> 'vendor_specific_extras' -> 'scs_index',
                    'scs_index', NULL,
                    'legacy_layout_signal_lost', true
                )
            )
        )
    WHERE rat = 'NR5G-SA' AND {OLD_LAYOUT}
"""


def upgrade() -> None:
    bind = op.get_bind()
    nsa_rows = bind.exec_driver_sql(CORRECT_NSA).rowcount
    sa_rows = bind.exec_driver_sql(CORRECT_SA).rowcount
    logger.info(
        "Corrected %d NR5G-NSA and %d NR5G-SA measurements stored in the old layout",
        nsa_rows,
        sa_rows,
    )


def downgrade() -> None:
    # The values the old layout overwrote cannot be reconstructed, and the misplaced ones are not
    # worth restoring.
    pass
