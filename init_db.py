import os
from sqlalchemy import select
from werkzeug.security import generate_password_hash
from app import Base, engine, DB, Employee

def initialise():
    Base.metadata.create_all(engine)
    with DB.begin() as db:
        if db.scalar(select(Employee).where(Employee.admin == True)):
            return
        password = os.getenv('ADMIN_PASSWORD', '')
        if len(password) < 12:
            raise RuntimeError('Set ADMIN_PASSWORD to a unique password of at least 12 characters.')
        db.add(Employee(code=os.getenv('ADMIN_USERNAME', 'admin').lower().strip(), name='Cosmos Admin',
                        department='Administration', admin=True, password=generate_password_hash(password)))

if __name__ == '__main__':
    initialise()
