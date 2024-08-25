"""Initial revision

Revision ID: 314e55f71f24
Revises: 
Create Date: 2024-08-25 13:14:33.144875

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '314e55f71f24'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
	op.create_table('cert_result',
		sa.Column('state', sa.Enum('STANDBY', 'COMPLETED', 'EXPIRED', 'FAILED', name='cert_state'), server_default='STANDBY', nullable=False),
		sa.Column('vender', sa.Enum('KAKAO', 'NAVER', 'PASS', name='cert_vender'), nullable=False),
		sa.Column('receipt_id', sa.String(), nullable=True),
		sa.Column('signed_data', sa.String(), nullable=True),
		sa.Column('cert_time', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
		sa.Column('error_stage', sa.Enum('REQUEST', 'GET_STATUS', 'VERIFY', name='cert_error_stage'), nullable=True),
		sa.Column('error_code', sa.Integer(), nullable=True),
		sa.Column('error_message', sa.String(), nullable=True),
		sa.Column('id', sa.Integer(), nullable=False),
		sa.PrimaryKeyConstraint('id')
	)
	op.create_table('document',
		sa.Column('doc_type', sa.Enum('PDF', 'JSON', name='document_type'), nullable=False),
		sa.Column('content', sa.LargeBinary(), nullable=False),
		sa.Column('sha256', sa.LargeBinary(), nullable=False),
		sa.Column('sha512', sa.LargeBinary(), nullable=False),
		sa.Column('upload_time', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
		sa.Column('id', sa.Integer(), nullable=False),
		sa.PrimaryKeyConstraint('id')
	)
	op.create_table('sender_role',
		sa.Column('company_name', sa.String(), nullable=True),
		sa.Column('company_address', sa.String(), nullable=True),
		sa.Column('id', sa.Integer(), nullable=False),
		sa.PrimaryKeyConstraint('id')
	)
	op.create_table('signature',
		sa.Column('did', sa.Integer(), nullable=False),
		sa.Column('cert_result_id', sa.Integer(), nullable=False),
		sa.Column('id', sa.Integer(), nullable=False),
		sa.ForeignKeyConstraint(['cert_result_id'], ['cert_result.id'], ),
		sa.ForeignKeyConstraint(['did'], ['document.id'], ),
		sa.PrimaryKeyConstraint('id')
	)
	op.create_table('user',
		sa.Column('register_time', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
		sa.Column('sender_role_id', sa.Integer(), nullable=True),
		sa.Column('id', sa.Integer(), nullable=False),
		sa.ForeignKeyConstraint(['sender_role_id'], ['sender_role.id'], name='user_sender_role_fkey'),
		sa.PrimaryKeyConstraint('id')
	)
	op.create_table('company',
		sa.Column('name', sa.String(), nullable=False),
		sa.Column('owner_id', sa.Integer(), nullable=False),
		sa.Column('sender_role_id', sa.Integer(), nullable=True),
		sa.Column('id', sa.Integer(), nullable=False),
		sa.ForeignKeyConstraint(['owner_id'], ['user.id'], ),
		sa.ForeignKeyConstraint(['sender_role_id'], ['sender_role.id'], name='company_sender_role_id_fkey'),
		sa.PrimaryKeyConstraint('id'),
		sa.UniqueConstraint('name', name='company_unique_name')
	)
	op.create_table('driver_role',
		sa.Column('uid', sa.Integer(), nullable=False),
		sa.Column('name', sa.String(), nullable=False),
		sa.Column('HP', sa.String(), nullable=False),
		sa.Column('birthday', sa.Date(), nullable=False),
		sa.Column('vehicle_id', sa.String(), nullable=False),
		sa.Column('vehicle_type', sa.Enum('TRUCK_1T', 'TRUCK_1_4T', 'TRUCK_2_5T', 'TRUCK_3_5T', 'TRUCK_5T', 'TRUCK_11T', 'TRUCK_18T', 'TRUCK_25T', name='vehicle_type'), nullable=False),
		sa.Column('id', sa.Integer(), nullable=False),
		sa.ForeignKeyConstraint(['uid'], ['user.id'], ),
		sa.PrimaryKeyConstraint('id'),
		sa.UniqueConstraint('HP'),
		sa.UniqueConstraint('uid'),
		sa.UniqueConstraint('vehicle_id')
	)
	op.create_table('user_auth',
		sa.Column('uid', sa.Integer(), nullable=False),
		sa.Column('google_id', sa.String(), nullable=True),
		sa.Column('email', sa.String(), nullable=True),
		sa.Column('has_email_verified', sa.Boolean(), server_default=sa.text('false'), nullable=False),
		sa.Column('password_salt', sa.LargeBinary(), nullable=True),
		sa.Column('password_sha512', sa.LargeBinary(), nullable=True),
		sa.Column('id', sa.Integer(), nullable=False),
		sa.ForeignKeyConstraint(['uid'], ['user.id'], ),
		sa.PrimaryKeyConstraint('id'),
		sa.UniqueConstraint('google_id')
	)
	op.create_table('company_membership',
		sa.Column('company_id', sa.Integer(), nullable=False),
		sa.Column('member_id', sa.Integer(), nullable=False),
		sa.Column('id', sa.Integer(), nullable=False),
		sa.ForeignKeyConstraint(['company_id'], ['company.id'], ),
		sa.ForeignKeyConstraint(['member_id'], ['user.id'], ),
		sa.PrimaryKeyConstraint('id'),
		sa.UniqueConstraint('member_id', name='unique_member')
	)
	op.create_table('order',
		sa.Column('did', sa.Integer(), nullable=False),
		sa.Column('sender_role_id', sa.Integer(), server_default=sa.text('NULL'), nullable=True),
		sa.Column('driver_role_id', sa.Integer(), server_default=sa.text('NULL'), nullable=True),
		sa.Column('ordered_time', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
		sa.Column('state', sa.Enum('REQUESTED', 'CANCELED', 'ALLOCATED', 'SHIPPING', 'COMPLETED', 'FAILED', name='order_state'), server_default='REQUESTED', nullable=False),
		sa.Column('id', sa.Integer(), nullable=False),
		sa.ForeignKeyConstraint(['did'], ['document.id'], ),
		sa.ForeignKeyConstraint(['driver_role_id'], ['driver_role.id'], name='order_driver_role_id_fkey'),
		sa.ForeignKeyConstraint(['sender_role_id'], ['sender_role.id'], name='order_sender_role_id_fkey'),
		sa.PrimaryKeyConstraint('id')
	)
	op.create_table('company_member_permission',
		sa.Column('company_membership_id', sa.Integer(), nullable=False),
		sa.Column('permission', sa.Enum('MANAGE_ORDER', 'MANAGE_MEMBER', name='member_permission'), nullable=False),
		sa.Column('id', sa.Integer(), nullable=False),
		sa.ForeignKeyConstraint(['company_membership_id'], ['company_membership.id'], ),
		sa.PrimaryKeyConstraint('id')
	)
	op.create_table('order_action_history',
		sa.Column('oid', sa.Integer(), nullable=False),
		sa.Column('uid', sa.Integer(), nullable=True),
		sa.Column('action', sa.Enum('ALLOCATE', 'DEALLOCATE', 'ONBOARD', 'OUTBOARD', 'CANCEL', 'SET_FAILED', name='order_action'), nullable=False),
		sa.Column('description', sa.String(), nullable=True),
		sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
		sa.Column('id', sa.Integer(), nullable=False),
		sa.ForeignKeyConstraint(['oid'], ['order.id'], ),
		sa.ForeignKeyConstraint(['uid'], ['user.id'], ),
		sa.PrimaryKeyConstraint('id')
	)
	op.create_table('order_contact',
		sa.Column('oid', sa.Integer(), nullable=False),
		sa.Column('name', sa.String(), nullable=False),
		sa.Column('HP', sa.String(), nullable=False),
		sa.Column('role', sa.Enum('SENDER', 'RECEIVER', name='order_contact_role'), nullable=False),
		sa.Column('id', sa.Integer(), nullable=False),
		sa.ForeignKeyConstraint(['oid'], ['order.id'], ),
		sa.PrimaryKeyConstraint('id')
	)

def downgrade() -> None:
	op.drop_table('order_contact')
	op.drop_table('order_action_history')
	op.drop_table('company_member_permission')
	op.drop_table('order')
	op.drop_table('company_membership')
	op.drop_table('user_auth')
	op.drop_table('driver_role')
	op.drop_table('company')
	op.drop_table('user')
	op.drop_table('signature')
	op.drop_table('sender_role')
	op.drop_table('document')
	op.drop_table('cert_result')

	op.execute('DROP TYPE cert_state')
	op.execute('DROP TYPE cert_vender')
	op.execute('DROP TYPE cert_error_stage')
	op.execute('DROP TYPE document_type')
	op.execute('DROP TYPE vehicle_type')
	op.execute('DROP TYPE member_permission')
	op.execute('DROP TYPE order_state')
	op.execute('DROP TYPE order_action')
	op.execute('DROP TYPE order_contact_role')
