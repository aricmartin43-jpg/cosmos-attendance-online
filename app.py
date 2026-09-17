import base64
import csv
import io
import hashlib
import json
import math
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps
from zoneinfo import ZoneInfo

import cloudinary
import cloudinary.uploader
import numpy as np
from cryptography.fernet import Fernet
from flask import Flask, Response, abort, jsonify, render_template, request, session
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, ForeignKey, create_engine, select, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from werkzeug.exceptions import HTTPException
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix

UTC = timezone.utc
LOCAL = ZoneInfo(os.getenv('TZ_NAME', 'Asia/Kolkata'))
PRODUCTION = os.getenv('APP_ENV', 'production') == 'production'
DB_URL = os.getenv('DATABASE_URL', '')
if not DB_URL:
    raise RuntimeError('DATABASE_URL must point to your Neon database.')
if DB_URL.startswith('postgres://'):
    DB_URL = DB_URL.replace('postgres://', 'postgresql://', 1)
if PRODUCTION and not DB_URL.startswith('postgresql://'):
    raise RuntimeError('Production requires PostgreSQL; local storage is disabled.')
if PRODUCTION and ('sslmode=' not in DB_URL or 'sslmode=disable' in DB_URL):
    raise RuntimeError('Use a Neon connection URL with SSL enabled.')
SECRET = os.getenv('SECRET_KEY', '')
if len(SECRET) < 32:
    raise RuntimeError('Set a random SECRET_KEY with at least 32 characters.')
CIPHER = Fernet(os.environ['FACE_ENCRYPTION_KEY'].encode())
THRESHOLD = float(os.getenv('FACE_THRESHOLD', '0.48'))
if not 0.3 <= THRESHOLD <= 0.6:
    raise RuntimeError('FACE_THRESHOLD must be between 0.3 and 0.6.')
engine = create_engine(DB_URL, pool_pre_ping=True)
DB = sessionmaker(engine, expire_on_commit=False)
cloudinary.config(secure=True)


class Base(DeclarativeBase):
    pass


class Employee(Base):
    __tablename__ = 'employees'
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    department: Mapped[str] = mapped_column(String(40))
    password: Mapped[str] = mapped_column(Text)
    admin: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    encoding: Mapped[str | None] = mapped_column(Text, nullable=True)
    photo_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    capture_token: Mapped[str | None] = mapped_column(String(100), nullable=True)
    capture_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Attendance(Base):
    __tablename__ = 'attendance'
    __table_args__ = (UniqueConstraint('employee_id', 'work_date', name='one_shift_per_day'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey('employees.id'), index=True)
    work_date: Mapped[str] = mapped_column(String(10), index=True)
    in_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    in_lat: Mapped[float] = mapped_column(Float)
    in_lng: Mapped[float] = mapped_column(Float)
    in_accuracy: Mapped[float] = mapped_column(Float)
    out_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    out_lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    out_accuracy: Mapped[float | None] = mapped_column(Float, nullable=True)
    in_photo: Mapped[str] = mapped_column(Text)
    out_photo: Mapped[str | None] = mapped_column(Text, nullable=True)
    in_distance: Mapped[float] = mapped_column(Float)
    out_distance: Mapped[float | None] = mapped_column(Float, nullable=True)


app = Flask(__name__)
app.config.update(SECRET_KEY=SECRET, MAX_CONTENT_LENGTH=3 * 1024 * 1024,
                  SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SECURE=PRODUCTION,
                  SESSION_COOKIE_SAMESITE='Lax', PERMANENT_SESSION_LIFETIME=timedelta(hours=12))
# Render terminates HTTPS at one trusted reverse proxy. Do not expose Gunicorn directly.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
# Deliberately one Gunicorn worker: memory-backed throttles are per process.
limiter = Limiter(get_remote_address, app=app, default_limits=['200 per minute'], storage_uri='memory://')


def now():
    return datetime.now(UTC)


def aware(dt):
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt


def person(e):
    return dict(id=e.id, code=e.code, name=e.name, department=e.department,
                admin=e.admin, active=e.active, enrolled=bool(e.encoding))


def record(r, e):
    hours = (aware(r.out_at) - aware(r.in_at)).total_seconds() / 3600 if r.out_at else None
    return dict(id=r.id, employee=e.name, code=e.code, department=e.department, date=r.work_date,
                check_in=aware(r.in_at).isoformat(), check_out=aware(r.out_at).isoformat() if r.out_at else None,
                hours=round(hours, 2) if hours is not None else None,
                in_location=dict(lat=r.in_lat, lng=r.in_lng, accuracy=r.in_accuracy),
                out_location=dict(lat=r.out_lat, lng=r.out_lng, accuracy=r.out_accuracy) if r.out_at else None)


def login_required(admin=False):
    def decorate(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            with DB() as db:
                e = db.get(Employee, session.get('uid', -1))
                if not e or not e.active:
                    abort(401, 'Please sign in.')
                if session.get('auth') != hashlib.sha256(e.password.encode()).hexdigest():
                    abort(401, 'Your password changed. Please sign in again.')
                if admin and not e.admin:
                    abort(403, 'Administrator access required.')
                request.employee = e
            return fn(*args, **kwargs)
        return wrapped
    return decorate


@app.before_request
def csrf():
    if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
        token = request.headers.get('X-CSRF-Token', '')
        if not token or not secrets.compare_digest(token, session.get('csrf', '')):
            abort(403, 'Session expired. Refresh the page and try again.')


@app.after_request
def headers(response):
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'same-origin'
    response.headers['Permissions-Policy'] = 'camera=(self), geolocation=(self), microphone=()'
    response.headers['Content-Security-Policy'] = "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; media-src 'self' blob:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    if PRODUCTION:
        response.headers['Strict-Transport-Security'] = 'max-age=31536000'
    return response


@app.errorhandler(HTTPException)
def http_error(e):
    return jsonify(error=e.description), e.code


@app.errorhandler(Exception)
def unexpected(e):
    app.logger.exception('Request failed')
    return jsonify(error='The request could not be saved. Please try again or contact your administrator.'), 503


@app.get('/')
def index():
    return render_template('index.html')


@app.get('/health')
@limiter.exempt
def health():
    with DB() as db:
        db.execute(select(Employee.id).limit(1))
    return {'status': 'ok'}


@app.get('/api/session')
def current_session():
    session.setdefault('csrf', secrets.token_urlsafe(32))
    with DB() as db:
        e = db.get(Employee, session.get('uid', -1))
        valid = e and e.active and session.get('auth') == hashlib.sha256(e.password.encode()).hexdigest()
        return dict(csrf=session['csrf'], user=person(e) if valid else None,
                    timezone=str(LOCAL), today=now().astimezone(LOCAL).date().isoformat())


@app.post('/api/login')
@limiter.limit('5 per minute; 30 per hour')
def login():
    data = request.get_json()
    with DB() as db:
        e = db.scalar(select(Employee).where(Employee.code == str(data.get('code', '')).strip().lower()))
        valid = check_password_hash(e.password if e else DUMMY_PASSWORD, str(data.get('password', '')))
        if not e or not e.active or not valid:
            abort(401, 'Employee ID or password is incorrect.')
        session.clear()
        session.update(uid=e.id, csrf=secrets.token_urlsafe(32), auth=hashlib.sha256(e.password.encode()).hexdigest())
        session.permanent = True
        return dict(user=person(e), csrf=session['csrf'])


DUMMY_PASSWORD = generate_password_hash(secrets.token_urlsafe(32))


@app.post('/api/logout')
def logout():
    session.clear()
    return {'ok': True}


def clean_text(data, key, limit):
    value = str(data.get(key, '')).strip()
    if not value or len(value) > limit:
        abort(400, f'{key.replace("_", " ").title()} must be between 1 and {limit} characters.')
    return value


@app.get('/api/employees')
@login_required(admin=True)
def employees():
    with DB() as db:
        return jsonify([person(e) for e in db.scalars(select(Employee).where(Employee.admin == False).order_by(Employee.name))])


@app.post('/api/employees')
@login_required(admin=True)
def add_employee():
    data = request.get_json()
    code = clean_text(data, 'code', 40).lower()
    if not re.fullmatch(r'[a-z0-9_-]+', code):
        abort(400, 'Employee ID may contain letters, numbers, hyphens and underscores.')
    password = clean_text(data, 'password', 128)
    if len(password) < 12:
        abort(400, 'Use a password of at least 12 characters.')
    with DB.begin() as db:
        if db.scalar(select(Employee).where(Employee.code == code)):
            abort(409, 'That employee ID already exists.')
        e = Employee(code=code, name=clean_text(data, 'name', 100),
                     department=clean_text(data, 'department', 40), password=generate_password_hash(password))
        db.add(e)
        db.flush()
        return person(e), 201


@app.post('/api/employees/<int:employee_id>/active')
@login_required(admin=True)
def active_employee(employee_id):
    data = request.get_json()
    if type(data.get('active')) is not bool:
        abort(400, 'Choose an active status.')
    with DB.begin() as db:
        e = db.get(Employee, employee_id)
        if not e or e.admin:
            abort(404)
        if not data['active'] and db.scalar(select(Attendance.id).where(Attendance.employee_id == e.id, Attendance.out_at == None)):
            abort(409, 'This employee must check out before deactivation.')
        e.active = data['active']
        return person(e)


def face_image(value):
    if not isinstance(value, str) or not value.startswith('data:image/jpeg;base64,'):
        abort(400, 'Take a fresh camera photo.')
    try:
        raw = base64.b64decode(value.split(',', 1)[1], validate=True)
        if len(raw) > 1500000:
            abort(400, 'Photo is too large.')
        img = Image.open(io.BytesIO(raw))
        if img.width * img.height > 2000000:
            abort(400, 'Photo dimensions are too large.')
        img = ImageOps.exif_transpose(img).convert('RGB')
        img.thumbnail((800, 800))
        import face_recognition
        pixels = np.array(img)
        locations = face_recognition.face_locations(pixels, model='hog')
        if len(locations) != 1:
            abort(400, 'Exactly one face must be visible. Face the camera in good light.')
        encoding = face_recognition.face_encodings(pixels, locations)[0]
        output = io.BytesIO()
        img.save(output, format='JPEG', quality=85)
        return encoding, output.getvalue()
    except (ValueError, UnidentifiedImageError, Image.DecompressionBombError):
        abort(400, 'Invalid photo. Please take another photo.')


def upload_photo(raw):
    if not os.getenv('CLOUDINARY_URL'):
        abort(503, 'Photo storage is not configured. Contact your administrator.')
    # Private delivery: never persist or return a public image URL.
    result = cloudinary.uploader.upload(io.BytesIO(raw), resource_type='image', type='authenticated',
                                        folder='cosmos-attendance', public_id=secrets.token_hex(16), overwrite=False)
    return result['public_id']


def remove_photo(public_id):
    if public_id:
        try:
            cloudinary.uploader.destroy(public_id, type='authenticated', invalidate=True)
        except Exception:
            app.logger.warning('Cloudinary cleanup pending for asset %s', public_id)


@app.post('/api/employees/<int:employee_id>/enrol')
@login_required(admin=True)
@limiter.limit('10 per minute')
def enrol(employee_id):
    data = request.get_json()
    if data.get('consent') is not True:
        abort(400, 'Record the employee’s consent before enrolment.')
    with DB() as db:
        e = db.get(Employee, employee_id)
        if not e or e.admin or not e.active:
            abort(404)
    encoding, raw = face_image(data.get('photo'))
    photo = upload_photo(raw)
    old = None
    try:
        with DB.begin() as db:
            e = db.scalar(select(Employee).where(Employee.id == employee_id).with_for_update())
            if not e or not e.active:
                abort(409, 'Employee is no longer active.')
            old = e.photo_id
            e.photo_id = photo
            e.encoding = CIPHER.encrypt(json.dumps(encoding.tolist()).encode()).decode()
            e.consent_at = now()
    except Exception:
        remove_photo(photo)
        raise
    remove_photo(old)
    return {'ok': True}


def gps(data):
    try:
        lat, lng, accuracy = float(data['lat']), float(data['lng']), float(data['accuracy'])
        age = abs(now().timestamp() * 1000 - float(data['timestamp']))
        if not all(math.isfinite(x) for x in (lat, lng, accuracy, age)):
            raise ValueError()
        if not (-90 <= lat <= 90 and -180 <= lng <= 180 and 0 <= accuracy <= 10000 and age <= 120000):
            raise ValueError()
        return lat, lng, accuracy
    except (KeyError, ValueError, TypeError):
        abort(400, 'A fresh GPS location is required. Allow location access and try again.')


@app.post('/api/attendance')
@login_required()
@limiter.limit('6 per minute')
def mark_attendance():
    data = request.get_json()
    action = data.get('action')
    if action not in ('in', 'out'):
        abort(400, 'Choose check-in or check-out.')
    lat, lng, accuracy = gps(data.get('location', {}))
    if request.employee.admin or not request.employee.encoding:
        abort(403, 'Ask your administrator to enrol your face first.')
    # Validate again under the employee row lock before committing attendance.
    if not request.employee.capture_token or data.get('challenge') != request.employee.capture_token or (now() - aware(request.employee.capture_at)).total_seconds() > 120:
        abort(400, 'Camera session expired. Start the camera again.')
    encoding, raw = face_image(data.get('photo'))
    stored = np.array(json.loads(CIPHER.decrypt(request.employee.encoding.encode())))
    distance = float(np.linalg.norm(stored - encoding))
    if not math.isfinite(distance) or distance > THRESHOLD:
        abort(403, 'Face did not match your registered photo. Try better lighting or contact your administrator.')
    photo = None
    try:
        with DB.begin() as db:
            e = db.scalar(select(Employee).where(Employee.id == request.employee.id).with_for_update())
            if not e.active or e.encoding != request.employee.encoding:
                abort(409, 'Your employee profile changed. Sign in again.')
            if not e.capture_token or not secrets.compare_digest(str(data.get('challenge', '')), e.capture_token) or (now() - aware(e.capture_at)).total_seconds() > 120:
                abort(409, 'This camera session expired or was already used. Try again.')
            open_record = db.scalar(select(Attendance).where(Attendance.employee_id == e.id, Attendance.out_at == None))
            stamp = now()
            day = stamp.astimezone(LOCAL).date().isoformat()
            if action == 'in':
                if open_record:
                    abort(409, 'You are already checked in. Check out first.')
                if db.scalar(select(Attendance.id).where(Attendance.employee_id == e.id, Attendance.work_date == day)):
                    abort(409, 'Attendance is complete for today. One shift per day is supported.')
            elif not open_record:
                abort(409, 'You do not have an open check-in.')
            photo = upload_photo(raw)
            e.capture_token, e.capture_at = None, None
            if action == 'in':
                r = Attendance(employee_id=e.id, work_date=day, in_at=stamp, in_lat=lat, in_lng=lng,
                               in_accuracy=accuracy, in_photo=photo, in_distance=distance)
                db.add(r)
            else:
                r = open_record
                r.out_at, r.out_lat, r.out_lng, r.out_accuracy = stamp, lat, lng, accuracy
                r.out_photo, r.out_distance = photo, distance
            db.flush()
            result = record(r, e)
    except Exception:
        remove_photo(photo)
        raise
    return result, 201


@app.post('/api/capture')
@login_required()
def capture_challenge():
    token = secrets.token_urlsafe(32)
    with DB.begin() as db:
        e = db.scalar(select(Employee).where(Employee.id == request.employee.id).with_for_update())
        e.capture_token, e.capture_at = token, now()
    return {'challenge': token}


def filtered_records(db):
    query = select(Attendance, Employee).join(Employee, Employee.id == Attendance.employee_id)
    if not request.employee.admin:
        query = query.where(Employee.id == request.employee.id)
    month = request.args.get('month')
    day = request.args.get('date')
    if month:
        try:
            datetime.strptime(month, '%Y-%m')
            if len(month) != 7:
                raise ValueError()
        except ValueError:
            abort(400, 'Choose a valid month.')
        query = query.where(Attendance.work_date.startswith(month + '-'))
    elif day:
        try:
            datetime.strptime(day, '%Y-%m-%d')
        except ValueError:
            abort(400, 'Choose a valid date.')
        query = query.where(Attendance.work_date == day)
    else:
        query = query.where(Attendance.work_date == now().astimezone(LOCAL).date().isoformat())
    return db.execute(query.order_by(Attendance.in_at.desc())).all()


@app.get('/api/attendance')
@login_required()
def get_attendance():
    with DB() as db:
        return jsonify([record(r, e) for r, e in filtered_records(db)])


@app.get('/api/my-status')
@login_required()
def my_status():
    with DB() as db:
        r = db.scalar(select(Attendance).where(Attendance.employee_id == request.employee.id, Attendance.out_at == None))
        return dict(open_shift=record(r, request.employee) if r else None)


@app.get('/api/export')
@login_required(admin=True)
def export():
    if not request.args.get('month'):
        abort(400, 'Select a month to export.')
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(['Employee ID', 'Name', 'Department', 'Work date', f'Check-in ({LOCAL})', f'Check-out ({LOCAL})',
                     'Hours', 'In latitude', 'In longitude', 'In GPS accuracy (m)', 'Out latitude', 'Out longitude', 'Out GPS accuracy (m)'])
    def safe(value):
        value = str(value) if value is not None else ''
        return "'" + value if value.startswith(('=', '+', '-', '@', '\t', '\r', '\n')) else value
    with DB() as db:
        for r, e in filtered_records(db):
            writer.writerow([safe(e.code), safe(e.name), safe(e.department), r.work_date,
                             aware(r.in_at).astimezone(LOCAL).strftime('%Y-%m-%d %H:%M:%S'),
                             aware(r.out_at).astimezone(LOCAL).strftime('%Y-%m-%d %H:%M:%S') if r.out_at else '',
                             record(r, e)['hours'], r.in_lat, r.in_lng, r.in_accuracy, r.out_lat, r.out_lng, r.out_accuracy])
    return Response('\ufeff' + out.getvalue(), mimetype='text/csv',
                    headers={'Content-Disposition': f'attachment; filename=cosmos-attendance-{request.args["month"]}.csv'})
