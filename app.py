from datetime import datetime, date
import os
import smtplib
from email.message import EmailMessage
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy

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
    tasks = db.relationship('Task', backref='plant', cascade='all,delete-orphan', lazy=True)


class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    plant_id = db.Column(db.Integer, db.ForeignKey('plant.id'), nullable=False)
    activity = db.Column(db.String(120), nullable=False)
    due_date = db.Column(db.Date, nullable=False)
    completed_on = db.Column(db.Date, nullable=True)


@app.route('/')
def index():
    plants = Plant.query.order_by(Plant.name.asc()).all()
    due_tasks = Task.query.filter(Task.completed_on.is_(None), Task.due_date <= date.today()).order_by(Task.due_date.asc()).all()
    return render_template('index.html', plants=plants, due_tasks=due_tasks, today=date.today())


@app.route('/plants', methods=['POST'])
def add_plant():
    plant = Plant(
        name=request.form['name'].strip(),
        location=request.form.get('location', '').strip(),
        notes=request.form.get('notes', '').strip(),
    )
    db.session.add(plant)
    db.session.commit()
    flash('Plant added.')
    return redirect(url_for('index'))


@app.route('/tasks', methods=['POST'])
def add_task():
    due = datetime.strptime(request.form['due_date'], '%Y-%m-%d').date()
    task = Task(
        plant_id=int(request.form['plant_id']),
        activity=request.form['activity'].strip(),
        due_date=due,
    )
    db.session.add(task)
    db.session.commit()
    flash('Maintenance activity scheduled.')
    return redirect(url_for('index'))


@app.post('/tasks/<int:task_id>/complete')
def complete_task(task_id: int):
    task = Task.query.get_or_404(task_id)
    task.completed_on = date.today()
    db.session.commit()
    flash('Task marked complete.')
    return redirect(url_for('index'))


def send_due_email() -> None:
    to_addr = os.getenv('NOTIFY_EMAIL_TO')
    from_addr = os.getenv('NOTIFY_EMAIL_FROM')
    smtp_host = os.getenv('SMTP_HOST')
    smtp_port = int(os.getenv('SMTP_PORT', '587'))
    smtp_user = os.getenv('SMTP_USER')
    smtp_password = os.getenv('SMTP_PASSWORD')

    if not all([to_addr, from_addr, smtp_host, smtp_user, smtp_password]):
        print('Email settings not fully configured; skipping email send.')
        return

    due_tasks = Task.query.join(Plant).filter(Task.completed_on.is_(None), Task.due_date <= date.today()).order_by(Task.due_date.asc()).all()
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

    if os.getenv('SEND_DUE_EMAIL') == '1':
        with app.app_context():
            send_due_email()
    else:
        app.run(host='0.0.0.0', port=8000, debug=False)
