from datetime import datetime, date, timedelta
import os
import uuid
import smtplib
from email.message import EmailMessage
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:////data/plants.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)


class Plant(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    location = db.Column(db.String(120), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    image_path = db.Column(db.String(255), nullable=True)
    archived_on = db.Column(db.Date, nullable=True)
    tasks = db.relationship('Task', backref='plant', cascade='all,delete-orphan', lazy=True)


class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    plant_id = db.Column(db.Integer, db.ForeignKey('plant.id'), nullable=False)
    activity = db.Column(db.String(120), nullable=False)
    due_date = db.Column(db.Date, nullable=False)
    completed_on = db.Column(db.Date, nullable=True)
    recurrence_days = db.Column(db.Integer, nullable=True)
    start_date = db.Column(db.Date, nullable=True)
    end_date = db.Column(db.Date, nullable=True)


class AppSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    notify_email_to = db.Column(db.String(255), nullable=True)
    notify_email_from = db.Column(db.String(255), nullable=True)
    smtp_host = db.Column(db.String(255), nullable=True)
    smtp_port = db.Column(db.Integer, nullable=True, default=587)
    smtp_user = db.Column(db.String(255), nullable=True)
    smtp_password = db.Column(db.String(255), nullable=True)


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
    if 'archived_on' not in plant_columns:
        db.session.execute(text('ALTER TABLE plant ADD COLUMN archived_on DATE'))
    if 'image_path' not in plant_columns:
        db.session.execute(text('ALTER TABLE plant ADD COLUMN image_path VARCHAR(255)'))
    db.session.commit()


def _get_settings() -> AppSettings:
    settings = AppSettings.query.get(1)
    if not settings:
        settings = AppSettings(id=1, smtp_port=587)
        db.session.add(settings)
        db.session.commit()
    return settings


@app.route('/')
def index():
    return redirect(url_for('upcoming_page'))


@app.route('/add')
def add_page():
    plants = Plant.query.filter(Plant.archived_on.is_(None)).order_by(Plant.name.asc()).all()
    archived_plants = Plant.query.filter(Plant.archived_on.isnot(None)).order_by(Plant.name.asc()).all()
    return render_template('add.html', plants=plants, archived_plants=archived_plants, active_page='add')


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
        db.session.commit()
        flash('Settings saved.')
        return redirect(url_for('settings_page'))
    return render_template('settings.html', settings=settings, active_page='settings')


@app.route('/upcoming')
def upcoming_page():
    plants = Plant.query.filter(Plant.archived_on.is_(None)).order_by(Plant.name.asc()).all()
    open_tasks = Task.query.filter(
        Task.plant.has(Plant.archived_on.is_(None)),
        Task.completed_on.is_(None),
        db.or_(Task.start_date.is_(None), Task.due_date >= Task.start_date),
        db.or_(Task.end_date.is_(None), Task.due_date <= Task.end_date),
    ).order_by(Task.due_date.asc()).all()
    return render_template('upcoming.html', plants=plants, open_tasks=open_tasks, today=date.today(), active_page='upcoming')


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
        ext = os.path.splitext(image.filename)[1].lower()
        allowed_extensions = {'.png', '.jpg', '.jpeg', '.gif', '.webp'}
        if ext not in allowed_extensions:
            flash('Unsupported image format. Use PNG, JPG, GIF, or WEBP.')
            return redirect(url_for('add_page'))
        upload_dir = os.path.join(app.static_folder, 'uploads')
        os.makedirs(upload_dir, exist_ok=True)
        filename = f"{uuid.uuid4().hex}{ext}"
        save_path = os.path.join(upload_dir, filename)
        image.save(save_path)
        image_path = f'uploads/{filename}'

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


@app.route('/tasks', methods=['POST'])
def add_task():
    due = datetime.strptime(request.form['due_date'], '%Y-%m-%d').date()
    recurrence_raw = request.form.get('recurrence', 'none')
    recurrence_days = int(recurrence_raw) if recurrence_raw != 'none' else None
    start_date_raw = request.form.get('start_date', '').strip()
    end_date_raw = request.form.get('end_date', '').strip()
    start_date = datetime.strptime(start_date_raw, '%Y-%m-%d').date() if start_date_raw else None
    end_date = datetime.strptime(end_date_raw, '%Y-%m-%d').date() if end_date_raw else None
    task = Task(
        plant_id=int(request.form['plant_id']),
        activity=request.form['activity'].strip(),
        due_date=due,
        recurrence_days=recurrence_days,
        start_date=start_date,
        end_date=end_date,
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
        )
        db.session.add(next_task)

    db.session.commit()
    flash('Task marked complete.')
    return redirect(url_for('upcoming_page'))


def send_due_email() -> None:
    settings = _get_settings()
    to_addr = settings.notify_email_to or os.getenv('NOTIFY_EMAIL_TO')
    from_addr = settings.notify_email_from or os.getenv('NOTIFY_EMAIL_FROM')
    smtp_host = settings.smtp_host or os.getenv('SMTP_HOST')
    smtp_port = int(settings.smtp_port or os.getenv('SMTP_PORT', '587'))
    smtp_user = settings.smtp_user or os.getenv('SMTP_USER')
    smtp_password = settings.smtp_password or os.getenv('SMTP_PASSWORD')

    if not all([to_addr, from_addr, smtp_host, smtp_user, smtp_password]):
        print('Email settings not fully configured; skipping email send.')
        return

    due_tasks = Task.query.join(Plant).filter(
        Task.completed_on.is_(None),
        Task.due_date <= date.today(),
        db.or_(Task.start_date.is_(None), Task.due_date >= Task.start_date),
        db.or_(Task.end_date.is_(None), Task.due_date <= Task.end_date),
    ).order_by(Task.due_date.asc()).all()
    if not due_tasks:
        print('No due tasks.')
        return

    lines = ['The following plant maintenance tasks are due:']
    for task in due_tasks:
        lines.append(f"- {task.plant.name}: {task.activity} (due {task.due_date.isoformat()})")

    msg = EmailMessage()
    msg['Subject'] = f'Plant upkeep due tasks ({date.today().isoformat()})'
    msg['From'] = from_addr
    msg['To'] = to_addr
    msg.set_content('\n'.join(lines))

    with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as server:
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.send_message(msg)

    print(f'Sent reminder email to {to_addr} with {len(due_tasks)} due task(s).')


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        _ensure_schema_updates()

    if os.getenv('SEND_DUE_EMAIL') == '1':
        with app.app_context():
            send_due_email()
    else:
        app.run(host='0.0.0.0', port=8000, debug=False)
