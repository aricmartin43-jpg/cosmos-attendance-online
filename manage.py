"""Administrator maintenance. Run from a trusted Render shell, never a public route."""
import argparse
import getpass
from sqlalchemy import select
from werkzeug.security import generate_password_hash
from app import DB, Employee

parser = argparse.ArgumentParser(description='Cosmos administrator maintenance')
parser.add_argument('command', choices=['reset-password'])
parser.add_argument('employee_id', help='Employee login ID, such as admin or ces001')
args = parser.parse_args()
password = getpass.getpass('New password (12+ characters): ')
if len(password) < 12 or len(password) > 128 or password != getpass.getpass('Confirm password: '):
    raise SystemExit('Passwords must match and be 12–128 characters.')
with DB.begin() as db:
    employee = db.scalar(select(Employee).where(Employee.code == args.employee_id.lower()))
    if not employee:
        raise SystemExit('Employee not found.')
    employee.password = generate_password_hash(password)
print('Password updated. Existing sign-ins have been invalidated.')
