from datetime import datetime, date, timedelta
import os
import uuid
import smtplib
from email.message import EmailMessage
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret')
default_db_path = os.path.join(app.root_path, 'data', 'plants.db')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', f"sqlite:///{default_db_path}")
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

def _ensure_sqlite_directory() -> None:
    uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
    if not uri.startswith('sqlite:///'):
        return
    db_path = uri.replace('sqlite:///', '', 1)
    if db_path == ':memory:':
        return
    os.makedirs(os.path.dirname(db_path), exist_ok=True)


_ensure_sqlite_directory()

class Plant(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    location = db.Column(db.String(120), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    image_path = db.Column(db.String(255), nullable=True)
    archived_on = db.Column(db.Date, nullable=True)
    tasks = db.relationship('Task', backref='plant', cascade='all,delete-orphan', lazy=True)
    photos = db.relationship('PlantPhoto', backref='plant', cascade='all,delete-orphan', lazy=True)


class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    plant_id = db.Column(db.Integer, db.ForeignKey('plant.id'), nullable=False)
    activity = db.Column(db.String(120), nullable=False)
    due_date = db.Column(db.Date, nullable=False)
    completed_on = db.Column(db.Date, nullable=True)
    recurrence_days = db.Column(db.Integer, nullable=True)
    start_date = db.Column(db.Date, nullable=True)
    end_date = db.Column(db.Date, nullable=True)
    reminder_timing = db.Column(db.String(24), nullable=True, default='none')


class PlantPhoto(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    plant_id = db.Column(db.Integer, db.ForeignKey('plant.id'), nullable=False)
    image_path = db.Column(db.String(255), nullable=False)
    note = db.Column(db.String(255), nullable=True)
    taken_on = db.Column(db.Date, nullable=False, default=date.today)


class ReminderLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sent_on = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    recipients = db.Column(db.String(255), nullable=False)
    task_count = db.Column(db.Integer, nullable=False, default=0)


class AppSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    notify_email_to = db.Column(db.String(255), nullable=True)
    notify_email_from = db.Column(db.String(255), nullable=True)
    smtp_host = db.Column(db.String(255), nullable=True)
    smtp_port = db.Column(db.Integer, nullable=True, default=587)
    smtp_user = db.Column(db.String(255), nullable=True)
    smtp_password = db.Column(db.String(255), nullable=True)
    smtp_sender_name = db.Column(db.String(255), nullable=True)
    smtp_helo_ident = db.Column(db.String(255), nullable=True)
    smtp_auth_mode = db.Column(db.String(32), nullable=True, default='none')
    smtp_security = db.Column(db.String(32), nullable=True, default='tls_if_available')
    smtp_tls_method = db.Column(db.String(32), nullable=True, default='auto')


def _ensure_schema_updates() -> None:
    if 'sqlite' not in app.config['SQLALCHEMY_DATABASE_URI']:
        return
    columns = [row[1] for row in db.session.execute(text("PRAGMA table_info(task)"))]
    plant_columns = [row[1] for row in db.session.execute(text("PRAGMA table_info(plant)"))]
    if 'recurrence_days' not in columns:
        db.session.execute(text('ALTER TABLE task ADD COLUMN recurrence_days INTEGER'))
    if 'start_date' not in columns:
        db.session.execute(text('ALTER TABLE task ADD COLUMN start_date DATE'))
    if 'end_date' not in columns:
        db.session.execute(text('ALTER TABLE task ADD COLUMN end_date DATE'))
    if 'reminder_timing' not in columns:
        db.session.execute(text("ALTER TABLE task ADD COLUMN reminder_timing VARCHAR(24) DEFAULT 'none'"))
    if 'archived_on' not in plant_columns:
        db.session.execute(text('ALTER TABLE plant ADD COLUMN archived_on DATE'))
    if 'image_path' not in plant_columns:
        db.session.execute(text('ALTER TABLE plant ADD COLUMN image_path VARCHAR(255)'))

    settings_columns = [row[1] for row in db.session.execute(text("PRAGMA table_info(app_settings)"))]
    if 'smtp_sender_name' not in settings_columns:
        db.session.execute(text('ALTER TABLE app_settings ADD COLUMN smtp_sender_name VARCHAR(255)'))
    if 'smtp_helo_ident' not in settings_columns:
        db.session.execute(text('ALTER TABLE app_settings ADD COLUMN smtp_helo_ident VARCHAR(255)'))
    if 'smtp_auth_mode' not in settings_columns:
        db.session.execute(text("ALTER TABLE app_settings ADD COLUMN smtp_auth_mode VARCHAR(32) DEFAULT 'none'"))
    if 'smtp_security' not in settings_columns:
        db.session.execute(text("ALTER TABLE app_settings ADD COLUMN smtp_security VARCHAR(32) DEFAULT 'tls_if_available'"))
    if 'smtp_tls_method' not in settings_columns:
        db.session.execute(text("ALTER TABLE app_settings ADD COLUMN smtp_tls_method VARCHAR(32) DEFAULT 'auto'"))
    db.session.commit()




def _save_uploaded_image(image):
    ext = os.path.splitext(image.filename)[1].lower()
    allowed_extensions = {'.png', '.jpg', '.jpeg', '.gif', '.webp'}
    if ext not in allowed_extensions:
        return None
    upload_dir = os.path.join(app.static_folder, 'uploads')
    os.makedirs(upload_dir, exist_ok=True)
    filename = f"{uuid.uuid4().hex}{ext}"
    save_path = os.path.join(upload_dir, filename)
    image.save(save_path)
    return f'uploads/{filename}'


def _plant_care_summary(plant: Plant):
    open_tasks = [t for t in plant.tasks if t.completed_on is None]
    completed_tasks = [t for t in plant.tasks if t.completed_on]
    next_due = min((t.due_date for t in open_tasks), default=None)
    last_done = max((t.completed_on for t in completed_tasks), default=None)
    today = date.today()
    if next_due is None:
        status = 'On track'
    elif next_due < today:
        status = 'Overdue'
    elif next_due <= today + timedelta(days=3):
        status = 'Due soon'
    else:
        status = 'On track'
    return {'next_due': next_due, 'last_done': last_done, 'status': status}

def _get_settings() -> AppSettings:
    settings = AppSettings.query.get(1)
    if not settings:
        settings = AppSettings(id=1, smtp_port=587, smtp_auth_mode='none', smtp_security='tls_if_available', smtp_tls_method='auto')
        db.session.add(settings)
        db.session.commit()
    return settings


def _smtp_config_from_settings(settings: AppSettings) -> dict:
    return {
        'to_addr': settings.notify_email_to or os.getenv('NOTIFY_EMAIL_TO'),
        'from_addr': settings.notify_email_from or os.getenv('NOTIFY_EMAIL_FROM'),
        'smtp_host': settings.smtp_host or os.getenv('SMTP_HOST'),
        'smtp_port': int(settings.smtp_port or os.getenv('SMTP_PORT', '587')),
        'smtp_user': settings.smtp_user or os.getenv('SMTP_USER'),
        'smtp_password': settings.smtp_password or os.getenv('SMTP_PASSWORD'),
        'smtp_sender_name': settings.smtp_sender_name or os.getenv('SMTP_SENDER_NAME', ''),
        'smtp_helo_ident': settings.smtp_helo_ident or os.getenv('SMTP_HELO_IDENT', ''),
        'smtp_auth_mode': settings.smtp_auth_mode or os.getenv('SMTP_AUTH_MODE', 'none'),
        'smtp_security': settings.smtp_security or os.getenv('SMTP_SECURITY', 'tls_if_available'),
    }


def _send_email_with_config(config: dict, msg: EmailMessage) -> None:
    with smtplib.SMTP(
        config['smtp_host'],
        config['smtp_port'],
        timeout=20,
        local_hostname=config['smtp_helo_ident'] or None,
    ) as server:
        if config['smtp_security'] == 'tls_if_available':
            server.ehlo()
            if server.has_extn('starttls'):
                server.starttls()
                server.ehlo()
        if config['smtp_auth_mode'] != 'none':
            server.login(config['smtp_user'], config['smtp_password'])
        server.send_message(msg)


_schema_initialized = False


def _initialize_database() -> None:
    global _schema_initialized
    if _schema_initialized:
        return
    with app.app_context():
        db.create_all()
        _ensure_schema_updates()
    _schema_initialized = True


@app.before_request
def _initialize_database_before_request():
    _initialize_database()


@app.route('/')
def index():
    return redirect(url_for('upcoming_page'))


@app.route('/add')
def add_page():
    view_mode = request.args.get('view', 'manage')
    plants = Plant.query.filter(Plant.archived_on.is_(None)).order_by(Plant.name.asc()).all()
    archived_plants = Plant.query.filter(Plant.archived_on.isnot(None)).order_by(Plant.name.asc()).all()
    care_summaries = {plant.id: _plant_care_summary(plant) for plant in plants}
    today = date.today()
    return render_template(
        'add.html',
        plants=plants,
        archived_plants=archived_plants,
        active_page='add',
        care_summaries=care_summaries,
        view_mode=view_mode if view_mode in {'manage', 'overview'} else 'manage',
        today=today,
    )


@app.route('/settings', methods=['GET', 'POST'])
def settings_page():
    settings = _get_settings()
    if request.method == 'POST':
        settings.notify_email_to = request.form.get('notify_email_to', '').strip()
        settings.notify_email_from = request.form.get('notify_email_from', '').strip()
        settings.smtp_host = request.form.get('smtp_host', '').strip()
        settings.smtp_port = int(request.form.get('smtp_port', '587') or '587')
        settings.smtp_user = request.form.get('smtp_user', '').strip()
        settings.smtp_password = request.form.get('smtp_password', '').strip()
        settings.smtp_sender_name = request.form.get('smtp_sender_name', '').strip()
        settings.smtp_helo_ident = request.form.get('smtp_helo_ident', '').strip()
        settings.smtp_auth_mode = request.form.get('smtp_auth_mode', 'none').strip() or 'none'
        settings.smtp_security = request.form.get('smtp_security', 'tls_if_available').strip() or 'tls_if_available'
        settings.smtp_tls_method = request.form.get('smtp_tls_method', 'auto').strip() or 'auto'
        db.session.commit()
        flash('Settings saved.')
        return redirect(url_for('settings_page'))
    return render_template('settings.html', settings=settings, active_page='settings')


@app.post('/settings/test-email')
def test_settings_email():
    settings = _get_settings()
    config = _smtp_config_from_settings(settings)
    if not all([config['to_addr'], config['from_addr'], config['smtp_host']]):
        flash('Cannot send test email: recipient, sender, and SMTP host are required.')
        return redirect(url_for('settings_page'))
    if config['smtp_auth_mode'] != 'none' and not all([config['smtp_user'], config['smtp_password']]):
        flash('Cannot send test email: SMTP authentication is enabled but credentials are missing.')
        return redirect(url_for('settings_page'))

    msg = EmailMessage()
    msg['Subject'] = f'SMTP test from FertilizerTracker ({date.today().isoformat()})'
    msg['From'] = f"{config['smtp_sender_name']} <{config['from_addr']}>" if config['smtp_sender_name'] else config['from_addr']
    msg['To'] = config['to_addr']
    msg.set_content(
        'This is a test email from FertilizerTracker settings.\n'
        f"Sent at {datetime.utcnow().isoformat()}Z."
    )

    try:
        _send_email_with_config(config, msg)
    except Exception as exc:
        flash(f'Test email failed: {exc}')
        return redirect(url_for('settings_page'))

    flash(f"Test email sent to {config['to_addr']}.")
    return redirect(url_for('settings_page'))


@app.route('/upcoming')
def upcoming_page():
    status_filter = request.args.get('status', '').strip()
    history_range = request.args.get('history_range', '30').strip()
    history_plant = request.args.get('history_plant', 'all').strip()
    open_tasks_query = Task.query.filter(
        Task.plant.has(Plant.archived_on.is_(None)),
        Task.completed_on.is_(None),
        db.or_(Task.start_date.is_(None), Task.due_date >= Task.start_date),
        db.or_(Task.end_date.is_(None), Task.due_date <= Task.end_date),
    )
    today = date.today()
    if status_filter == 'due_week':
        open_tasks_query = open_tasks_query.filter(Task.due_date <= today + timedelta(days=7))
    elif status_filter == 'overdue':
        open_tasks_query = open_tasks_query.filter(Task.due_date < today)
    open_tasks = open_tasks_query.order_by(Task.due_date.asc()).all()

    completed_tasks_query = Task.query.join(Plant).filter(Task.completed_on.isnot(None))
    if history_plant != 'all' and history_plant.isdigit():
        completed_tasks_query = completed_tasks_query.filter(Task.plant_id == int(history_plant))
    if history_range != 'all':
        try:
            days_back = int(history_range)
            completed_tasks_query = completed_tasks_query.filter(Task.completed_on >= today - timedelta(days=days_back))
        except ValueError:
            history_range = '30'
            completed_tasks_query = completed_tasks_query.filter(Task.completed_on >= today - timedelta(days=30))
    completed_tasks = completed_tasks_query.order_by(Task.completed_on.desc(), Task.due_date.desc()).all()

    completed_count = len(completed_tasks)
    recent_window_start = today - timedelta(days=7)
    completed_last_week = sum(1 for t in completed_tasks if t.completed_on and t.completed_on >= recent_window_start)
    plants = Plant.query.order_by(Plant.name.asc()).all()
    return render_template(
        'upcoming.html',
        plants=plants,
        open_tasks=open_tasks,
        completed_tasks=completed_tasks,
        completed_count=completed_count,
        completed_last_week=completed_last_week,
        today=today,
        active_page='upcoming',
        status_filter=status_filter,
        history_range=history_range,
        history_plant=history_plant,
    )


@app.post('/plants/<int:plant_id>/archive')
def archive_plant(plant_id: int):
    plant = Plant.query.get_or_404(plant_id)
    plant.archived_on = date.today()
    db.session.commit()
    flash('Plant archived with its task history.')
    return redirect(url_for('add_page'))


@app.post('/plants/<int:plant_id>/delete')
def delete_plant(plant_id: int):
    plant = Plant.query.get_or_404(plant_id)
    db.session.delete(plant)
    db.session.commit()
    flash('Plant and all task history deleted.')
    return redirect(url_for('add_page'))


@app.route('/plants', methods=['POST'])
def add_plant():
    image = request.files.get('image')
    image_path = None
    if image and image.filename:
        image_path = _save_uploaded_image(image)
        if not image_path:
            flash('Unsupported image format. Use PNG, JPG, GIF, or WEBP.')
            return redirect(url_for('add_page'))

    plant = Plant(
        name=request.form['name'].strip(),
        location=request.form.get('location', '').strip(),
        notes=request.form.get('notes', '').strip(),
        image_path=image_path,
    )
    db.session.add(plant)
    db.session.commit()
    flash('Plant added.')
    return redirect(url_for('add_page'))


@app.post('/plants/<int:plant_id>/edit')
def edit_plant(plant_id: int):
    plant = Plant.query.get_or_404(plant_id)
    plant.name = request.form.get('name', plant.name).strip()
    plant.location = request.form.get('location', '').strip()
    plant.notes = request.form.get('notes', '').strip()
    image = request.files.get('image')
    if image and image.filename:
        saved = _save_uploaded_image(image)
        if not saved:
            flash('Unsupported image format. Use PNG, JPG, GIF, or WEBP.')
            return redirect(url_for('add_page'))
        plant.image_path = saved
    timeline_image = request.files.get('timeline_image')
    if timeline_image and timeline_image.filename:
        saved = _save_uploaded_image(timeline_image)
        if saved:
            db.session.add(PlantPhoto(plant_id=plant.id, image_path=saved, note=request.form.get('timeline_note', '').strip(), taken_on=date.today()))
    db.session.commit()
    flash('Plant updated.')
    return redirect(url_for('add_page'))


@app.route('/tasks', methods=['POST'])
def add_task():
    due = datetime.strptime(request.form['due_date'], '%Y-%m-%d').date()
    recurrence_raw = request.form.get('recurrence', 'none')
    recurrence_days = int(recurrence_raw) if recurrence_raw != 'none' else None
    start_date_raw = request.form.get('start_date', '').strip()
    end_date_raw = request.form.get('end_date', '').strip()
    start_date = datetime.strptime(start_date_raw, '%Y-%m-%d').date() if start_date_raw else None
    end_date = datetime.strptime(end_date_raw, '%Y-%m-%d').date() if end_date_raw else None
    reminder_timing = request.form.get('reminder_timing', 'none').strip() or 'none'
    task = Task(
        plant_id=int(request.form['plant_id']),
        activity=request.form['activity'].strip(),
        due_date=due,
        recurrence_days=recurrence_days,
        start_date=start_date,
        end_date=end_date,
        reminder_timing=reminder_timing,
    )
    db.session.add(task)
    db.session.commit()
    flash('Maintenance activity scheduled.')
    return redirect(url_for('add_page'))


@app.post('/tasks/<int:task_id>/complete')
def complete_task(task_id: int):
    task = Task.query.get_or_404(task_id)
    task.completed_on = date.today()

    if task.recurrence_days:
        next_due_date = task.due_date + timedelta(days=task.recurrence_days)
        if task.start_date and next_due_date < task.start_date:
            next_due_date = task.start_date
        if task.end_date and next_due_date > task.end_date:
            db.session.commit()
            flash('Task marked complete.')
            return redirect(url_for('upcoming_page'))
        next_task = Task(
            plant_id=task.plant_id,
            activity=task.activity,
            due_date=next_due_date,
            recurrence_days=task.recurrence_days,
            start_date=task.start_date,
            end_date=task.end_date,
            reminder_timing=task.reminder_timing,
        )
        db.session.add(next_task)

    db.session.commit()
    flash('Task marked complete.')
    return redirect(url_for('upcoming_page'))


@app.post('/tasks/<int:task_id>/edit')
def edit_task(task_id: int):
    task = Task.query.get_or_404(task_id)
    task.activity = request.form.get('activity', task.activity).strip()
    task.due_date = datetime.strptime(request.form['due_date'], '%Y-%m-%d').date()
    recurrence_raw = request.form.get('recurrence', 'none')
    task.recurrence_days = int(recurrence_raw) if recurrence_raw != 'none' else None
    start_date_raw = request.form.get('start_date', '').strip()
    end_date_raw = request.form.get('end_date', '').strip()
    task.start_date = datetime.strptime(start_date_raw, '%Y-%m-%d').date() if start_date_raw else None
    task.end_date = datetime.strptime(end_date_raw, '%Y-%m-%d').date() if end_date_raw else None
    task.reminder_timing = request.form.get('reminder_timing', 'none').strip() or 'none'
    db.session.commit()
    flash('Scheduled activity updated.')
    return redirect(url_for('add_page'))


@app.post('/tasks/<int:task_id>/delete')
def delete_task(task_id: int):
    task = Task.query.get_or_404(task_id)
    db.session.delete(task)
    db.session.commit()
    flash('Scheduled activity removed.')
    return redirect(url_for('add_page'))


@app.get('/export')
def export_data():
    plants = []
    for p in Plant.query.order_by(Plant.id.asc()).all():
        plants.append({
            'id': p.id, 'name': p.name, 'location': p.location, 'notes': p.notes, 'image_path': p.image_path,
            'archived_on': p.archived_on.isoformat() if p.archived_on else None,
            'tasks': [{'activity': t.activity, 'due_date': t.due_date.isoformat(), 'completed_on': t.completed_on.isoformat() if t.completed_on else None, 'recurrence_days': t.recurrence_days} for t in p.tasks],
            'photos': [{'image_path': ph.image_path, 'note': ph.note, 'taken_on': ph.taken_on.isoformat()} for ph in p.photos],
        })
    logs = [{'sent_on': l.sent_on.isoformat(), 'recipients': l.recipients, 'task_count': l.task_count} for l in ReminderLog.query.order_by(ReminderLog.sent_on.desc()).all()]
    return jsonify({'plants': plants, 'reminder_logs': logs})


@app.post('/import')
def import_data():
    payload = request.get_json(silent=True) or {}
    for item in payload.get('plants', []):
        plant = Plant(name=item.get('name', 'Unnamed plant'), location=item.get('location'), notes=item.get('notes'), image_path=item.get('image_path'))
        db.session.add(plant)
        db.session.flush()
        for t in item.get('tasks', []):
            db.session.add(Task(plant_id=plant.id, activity=t['activity'], due_date=datetime.strptime(t['due_date'], '%Y-%m-%d').date(), completed_on=datetime.strptime(t['completed_on'], '%Y-%m-%d').date() if t.get('completed_on') else None, recurrence_days=t.get('recurrence_days')))
        for ph in item.get('photos', []):
            db.session.add(PlantPhoto(plant_id=plant.id, image_path=ph['image_path'], note=ph.get('note'), taken_on=datetime.strptime(ph['taken_on'], '%Y-%m-%d').date()))
    db.session.commit()
    return {'ok': True}


def send_due_email() -> None:
    settings = _get_settings()
    config = _smtp_config_from_settings(settings)

    if not all([config['to_addr'], config['from_addr'], config['smtp_host']]):
        print('Email settings not fully configured; skipping email send.')
        return
    if config['smtp_auth_mode'] != 'none' and not all([config['smtp_user'], config['smtp_password']]):
        print('SMTP authentication enabled but credentials are missing; skipping email send.')
        return

    due_tasks = Task.query.join(Plant).filter(
        Task.completed_on.is_(None),
        Task.reminder_timing.in_(['on_due_date', 'after_due_date']),
        db.or_(Task.start_date.is_(None), Task.due_date >= Task.start_date),
        db.or_(Task.end_date.is_(None), Task.due_date <= Task.end_date),
    ).order_by(Task.due_date.asc()).all()
    today = date.today()
    matching_tasks = [
        task for task in due_tasks
        if (task.reminder_timing == 'on_due_date' and task.due_date == today)
        or (task.reminder_timing == 'after_due_date' and task.due_date < today)
    ]
    if not matching_tasks:
        print('No due tasks.')
        return

    lines = ['The following plant maintenance tasks are due:']
    for task in matching_tasks:
        lines.append(f"- {task.plant.name}: {task.activity} (due {task.due_date.isoformat()})")

    msg = EmailMessage()
    msg['Subject'] = f'Plant upkeep due tasks ({date.today().isoformat()})'
    msg['From'] = f"{config['smtp_sender_name']} <{config['from_addr']}>" if config['smtp_sender_name'] else config['from_addr']
    msg['To'] = config['to_addr']
    msg.set_content('\n'.join(lines))

    _send_email_with_config(config, msg)

    db.session.add(ReminderLog(recipients=config['to_addr'], task_count=len(matching_tasks)))
    db.session.commit()
    print(f"Sent reminder email to {config['to_addr']} with {len(matching_tasks)} due task(s).")


if __name__ == '__main__':
    if os.getenv('SEND_DUE_EMAIL') == '1':
        with app.app_context():
            send_due_email()
    else:
        app.run(host='0.0.0.0', port=8000, debug=False)
