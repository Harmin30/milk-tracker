from flask import Flask, render_template, redirect, url_for, flash, request
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from collections import defaultdict
from flask import send_file
from datetime import datetime, timedelta
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get("SECRET_KEY", "dev_secret_key")

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# ================= DATABASE CONFIG =================

database_url = os.environ.get("DATABASE_URL")

if database_url:
    # Render gives postgres:// but SQLAlchemy needs postgresql://
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)

    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
else:
    # Local fallback (for development only)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///milk.db'


from datetime import timedelta

app.config['REMEMBER_COOKIE_DURATION'] = timedelta(days=7)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SECURE'] = os.environ.get("RENDER") is not None

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    mobile = db.Column(db.String(15), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)

    profile = db.relationship('Profile', backref='user', uselist=False)


class Profile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))

    name = db.Column(db.String(100))
    address = db.Column(db.Text)
    buffalo_price = db.Column(db.Float)
    cow_price = db.Column(db.Float)


class MilkEntry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    date = db.Column(db.Date)
    milk_type = db.Column(db.String(20))
    liters = db.Column(db.Float)
    price_per_liter = db.Column(db.Float)

    user = db.relationship('User', backref='entries')


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        mobile = request.form.get("mobile")
        password = request.form.get("password")
        confirm = request.form.get("confirm_password")

        if not mobile or not password:
            flash("All fields are required.")
            return redirect(url_for("forgot_password"))

        if password != confirm:
            flash("Passwords do not match.")
            return redirect(url_for("forgot_password"))

        user = User.query.filter_by(mobile=mobile).first()

        if user:
            user.password = generate_password_hash(password)
            db.session.commit()
            flash("Password updated successfully. Please login.")
            return redirect(url_for("login"))
        else:
            flash("Mobile number not found.")

    return render_template("forgot_password.html")

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))




@app.route("/")
def home():
    return redirect(url_for("login"))

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        mobile = request.form.get("mobile")
        password = request.form.get("password")
        confirm = request.form.get("confirm_password")

        if not mobile or not password:
            flash("All fields are required.")
            return redirect(url_for("register"))

        if len(mobile) != 10 or not mobile.isdigit():
            flash("Enter valid 10-digit mobile number.")
            return redirect(url_for("register"))

        if password != confirm:
            flash("Passwords do not match.")
            return redirect(url_for("register"))

        existing_user = User.query.filter_by(mobile=mobile).first()
        if existing_user:
            flash("Mobile number already registered.")
            return redirect(url_for("register"))

        hashed_password = generate_password_hash(password)

        new_user = User(mobile=mobile, password=hashed_password)
        db.session.add(new_user)
        db.session.commit()

        # Create empty profile
        profile = Profile(user_id=new_user.id)
        db.session.add(profile)
        db.session.commit()

        flash("Registration successful. Please login.")
        return redirect(url_for("login"))

    return render_template("register.html")



@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        mobile = request.form.get("mobile")
        password = request.form.get("password")
        remember = True if request.form.get("remember") else False

        user = User.query.filter_by(mobile=mobile).first()

        if user and check_password_hash(user.password, password):
            login_user(user, remember=remember)
            return redirect(url_for("dashboard"))
        else:
            flash("Invalid mobile or password.")

    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Logged out successfully.")
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    return render_template("dashboard.html")


@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    user_profile = current_user.profile

    if request.method == "POST":
        name = request.form.get("name")
        address = request.form.get("address")
        buffalo_price = request.form.get("buffalo_price")
        cow_price = request.form.get("cow_price")

        user_profile.name = name
        user_profile.address = address

        user_profile.buffalo_price = float(buffalo_price) if buffalo_price else None
        user_profile.cow_price = float(cow_price) if cow_price else None

        db.session.commit()

        flash("Profile updated successfully.")
        return redirect(url_for("profile"))

    return render_template("profile.html", profile=user_profile)


@app.route("/add-entry", methods=["GET", "POST"])
@login_required
def add_entry():
    profile = current_user.profile

    # Restriction logic
    if not profile.buffalo_price or not profile.cow_price:
        flash("Please set milk prices in your profile first.")
        return redirect(url_for("profile"))

    if request.method == "POST":
        date_str = request.form.get("date")
        milk_type = request.form.get("milk_type")
        liters = request.form.get("liters")

        if not date_str or not milk_type or not liters:
            flash("All fields are required.")
            return redirect(url_for("add_entry"))

        date = datetime.strptime(date_str, "%Y-%m-%d").date()
        # 🔒 Prevent future dates
        if date > datetime.today().date():
            flash("Future dates are not allowed.")
            return redirect(url_for("add_entry"))

        liters = float(liters)

        # Auto-set price based on type
        if milk_type == "Buffalo":
            price = profile.buffalo_price
        else:
            price = profile.cow_price

        entry = MilkEntry(
            user_id=current_user.id,
            date=date,
            milk_type=milk_type,
            liters=liters,
            price_per_liter=price
        )

        db.session.add(entry)
        db.session.commit()

        flash("Milk entry added successfully.")
        return redirect(url_for("add_entry"))

    return render_template("add_entry.html", profile=profile, datetime=datetime)



@app.route("/records")
@login_required
def records():
    page = request.args.get('page', 1, type=int)

    entries = (
        MilkEntry.query
        .filter_by(user_id=current_user.id)
        .order_by(
            MilkEntry.date.desc(),
            MilkEntry.id.desc()   # ensures newest entry first if same date
        )
        .paginate(page=page, per_page=5)
    )

    return render_template("records.html", entries=entries)


@app.route("/delete-entry/<int:entry_id>")
@login_required
def delete_entry(entry_id):
    entry = MilkEntry.query.get_or_404(entry_id)

    # Security check (very important)
    if entry.user_id != current_user.id:
        flash("Unauthorized action.")
        return redirect(url_for("records"))

    db.session.delete(entry)
    db.session.commit()

    flash("Entry deleted successfully.")
    return redirect(url_for("records"))



@app.route("/edit-entry/<int:entry_id>", methods=["GET", "POST"])
@login_required
def edit_entry(entry_id):
    entry = MilkEntry.query.get_or_404(entry_id)

    # Security check
    if entry.user_id != current_user.id:
        flash("Unauthorized action.")
        return redirect(url_for("records"))

    profile = current_user.profile

    if request.method == "POST":
        date_str = request.form.get("date")
        milk_type = request.form.get("milk_type")
        liters = request.form.get("liters")

        if not date_str or not milk_type or not liters:
            flash("All fields are required.")
            return redirect(url_for("edit_entry", entry_id=entry.id))

        new_date = datetime.strptime(date_str, "%Y-%m-%d").date()

        # 🔒 Prevent future dates
        if new_date > datetime.today().date():
            flash("Future dates are not allowed.")
            return redirect(url_for("edit_entry", entry_id=entry.id))

        entry.date = new_date
        entry.milk_type = milk_type
        entry.liters = float(liters)

        # Update price automatically based on type
        if milk_type == "Buffalo":
            entry.price_per_liter = profile.buffalo_price
        else:
            entry.price_per_liter = profile.cow_price

        db.session.commit()

        flash("Entry updated successfully.")
        return redirect(url_for("records"))

    return render_template("edit_entry.html", entry=entry, datetime=datetime)



@app.route("/summary")
@login_required
def summary():

    page = request.args.get('page', 1, type=int)
    per_page = 3   # months per page

    entries = (
        MilkEntry.query
        .filter_by(user_id=current_user.id)
        .order_by(MilkEntry.date.desc())
        .all()
    )

    # Group by month
    monthly_data = {}

    for entry in entries:
        month_key = entry.date.strftime("%B %Y")

        if month_key not in monthly_data:
            monthly_data[month_key] = {
                "Buffalo_liters": 0,
                "Buffalo_amount": 0,
                "Cow_liters": 0,
                "Cow_amount": 0,
                "Grand_total": 0
            }

        total = entry.liters * entry.price_per_liter

        if entry.milk_type == "Buffalo":
            monthly_data[month_key]["Buffalo_liters"] += entry.liters
            monthly_data[month_key]["Buffalo_amount"] += total
        else:
            monthly_data[month_key]["Cow_liters"] += entry.liters
            monthly_data[month_key]["Cow_amount"] += total

        monthly_data[month_key]["Grand_total"] += total

    # Convert to list for pagination
    month_list = list(monthly_data.items())

    total_months = len(month_list)
    start = (page - 1) * per_page
    end = start + per_page

    paginated_months = month_list[start:end]

    total_pages = (total_months + per_page - 1) // per_page

    return render_template(
        "summary.html",
        summary_data=paginated_months,
        page=page,
        total_pages=total_pages
    )



from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import inch
from datetime import datetime
from flask import send_file, flash, redirect, url_for, render_template, request
from flask_login import login_required, current_user


@app.route("/generate-bill", methods=["GET", "POST"])
@login_required
def generate_bill():

    profile = current_user.profile

    if not profile.buffalo_price or not profile.cow_price:
        flash("Please set milk prices in your profile first.")
        return redirect(url_for("profile"))

    # Get all distinct months from entries
    entries = (
        MilkEntry.query
        .filter_by(user_id=current_user.id)
        .order_by(MilkEntry.date.desc())
        .all()
    )

    available_months = set()

    for e in entries:
        month_start = e.date.replace(day=1)
        available_months.add(month_start)

    # Remove current month (only allow completed months)
    today = datetime.today().date()
    current_month_start = today.replace(day=1)

    completed_months = sorted(
        [m for m in available_months if m < current_month_start],
        reverse=True
    )

    if request.method == "POST":

        bill_type = request.form.get("bill_type")

        if bill_type == "monthly":

            selected_month = request.form.get("month")

            if not selected_month:
                flash("Please select a month.")
                return redirect(url_for("generate_bill"))

            from_date = datetime.strptime(selected_month, "%Y-%m").date()
            to_date = (
                from_date.replace(day=28) + 
                timedelta(days=4)
            ).replace(day=1) - timedelta(days=1)

        else:
            # Custom range
            from_date = datetime.strptime(request.form.get("from_date"), "%Y-%m-%d").date()
            to_date = datetime.strptime(request.form.get("to_date"), "%Y-%m-%d").date()

        # Fetch entries for date range
        entries = (
            MilkEntry.query
            .filter(
                MilkEntry.user_id == current_user.id,
                MilkEntry.date >= from_date,
                MilkEntry.date <= to_date
            )
            .order_by(MilkEntry.date)
            .all()
        )

        if not entries:
            flash("No records found for selected dates.")
            return redirect(url_for("generate_bill"))

        # ================= CALCULATIONS =================
        buffalo_total = cow_total = 0
        buffalo_liters = cow_liters = 0

        for e in entries:
            amount = e.liters * e.price_per_liter
            if e.milk_type == "Buffalo":
                buffalo_total += amount
                buffalo_liters += e.liters
            else:
                cow_total += amount
                cow_liters += e.liters

        grand_total = buffalo_total + cow_total
        total_liters = buffalo_liters + cow_liters

        # (Keep your existing PDF logic here)
        # Just reuse your PDF generation part

        # IMPORTANT: Replace billing period with:
        billing_period_text = f"{from_date.strftime('%d %b %Y')} - {to_date.strftime('%d %b %Y')}"

        # continue your existing PDF logic here...

        # ================= PDF =================

        file_path = f"milk_bill_{current_user.id}.pdf"

        doc = SimpleDocTemplate(
            file_path,
            pagesize=A4,
            rightMargin=40,
            leftMargin=40,
            topMargin=40,
            bottomMargin=40
        )

        elements = []
        styles = getSampleStyleSheet()

        # -------- Styles --------

        title_style = ParagraphStyle(
            'TitleStyle',
            parent=styles['Title'],
            fontSize=18,
            alignment=1
        )

        big_total_style = ParagraphStyle(
            'BigTotal',
            parent=styles['Heading2'],
            fontSize=14,
            textColor=colors.black,
        )

        normal_style = styles["Normal"]

        # ===== HEADER BAR =====

        header = Table(
            [[Paragraph("<b>MILK BILL</b>", title_style)]],
            colWidths=[480]
        )

        header.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#eeeeee")),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 18),
            ("TOPPADDING", (0, 0), (-1, -1), 18),
        ]))

        elements.append(header)
        elements.append(Spacer(1, 0.2 * inch))

        # ===== BILL INFO =====

        bill_info = Table([
            [
                Paragraph(
                    f"<b>{profile.name}</b><br/>"
                    f"Mobile: {current_user.mobile}<br/><br/>"
                    f"{profile.address}",
                    normal_style
                ),
                Paragraph(
                    f"<b>Billing Period</b><br/>"
                    f"{from_date.strftime('%d %b %Y')} - {to_date.strftime('%d %b %Y')}<br/><br/>"
                    f"<b>Rates</b><br/>"
                    f"Buffalo: Rs. {profile.buffalo_price}/L<br/>"
                    f"Cow: Rs. {profile.cow_price}/L",
                    normal_style
                )
            ]
        ], colWidths=[260, 220])

        bill_info.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.6, colors.lightgrey),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 14),
            ("RIGHTPADDING", (0, 0), (-1, -1), 14),
            ("TOPPADDING", (0, 0), (-1, -1), 14),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
        ]))

        elements.append(bill_info)
        elements.append(Spacer(1, 0.25 * inch))

        # ===== SUMMARY TABLE =====

        summary_data = [
            ["Milk Type", "Liters", "Amount"],
            ["Buffalo", buffalo_liters, f"Rs. {buffalo_total:.2f}"],
            ["Cow", cow_liters, f"Rs. {cow_total:.2f}"],
            ["TOTAL", total_liters, f"Rs. {grand_total:.2f}"],
        ]

        summary_table = Table(summary_data, colWidths=[240, 100, 140])

        summary_table.setStyle(TableStyle([
    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")),
    ("GRID", (0, 0), (-1, -1), 0.3, colors.lightgrey),

    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
    ("ALIGN", (0, 0), (-1, 0), "CENTER"),

    ("ALIGN", (0, 1), (0, -1), "LEFT"),
    ("ALIGN", (1, 1), (-1, -1), "RIGHT"),

    ("FONTNAME", (0, 3), (-1, 3), "Helvetica-Bold"),
]))

        elements.append(summary_table)
        elements.append(Spacer(1, 0.3 * inch))

        # ===== DETAILED TABLE =====

        data = [["Date", "Liters", "Type", "Rate", "Amount"]]

        for e in entries:
            total = e.liters * e.price_per_liter
            data.append([
                e.date.strftime("%d %b %Y"),
                e.liters,
                e.milk_type,
                f"Rs. {e.price_per_liter}",
                f"Rs. {total:.2f}"
            ])

        main_table = Table(data, colWidths=[110, 70, 90, 90, 110])

        main_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f2f2f2")),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.lightgrey),

            # Header style
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("ALIGN", (0, 0), (-1, 0), "CENTER"),

            # Text columns LEFT
            ("ALIGN", (0, 1), (0, -1), "LEFT"),   # Date
            ("ALIGN", (2, 1), (2, -1), "LEFT"),   # Type

            # Numeric columns RIGHT
            ("ALIGN", (1, 1), (1, -1), "RIGHT"),  # Liters
            ("ALIGN", (3, 1), (3, -1), "RIGHT"),  # Rate
            ("ALIGN", (4, 1), (4, -1), "RIGHT"),  # Amount
            ]))

        elements.append(main_table)
        elements.append(Spacer(1, 0.2 * inch))

                # ===== FOOTER SECTION =====

        elements.append(Spacer(1, 0.1 * inch))

        # Divider Line
        divider = Table([[""]], colWidths=[500])
        divider.setStyle(TableStyle([
            ("LINEABOVE", (0, 0), (-1, -1), 0.7, colors.grey),
        ]))
        elements.append(divider)

        elements.append(Spacer(1, 0.02 * inch))

        # ===== TOTAL BILL (Perfectly Right Aligned) =====

        total_table = Table(
            [[
                Paragraph("<b>Total Bill</b>", styles["Heading2"]),
                Paragraph(f"<b>Rs. {grand_total:.2f}</b>", big_total_style )
            ]],
            colWidths=[400, 100]   # left wide, right tight
        )

        total_table.setStyle(TableStyle([
            ("ALIGN", (0, 0), (0, 0), "LEFT"),
            ("ALIGN", (1, 0), (1, 0), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))

        elements.append(total_table)

        # elements.append(Spacer(1, 0.8 * inch))

        # # Generated On Text
        # elements.append(
        #     Paragraph(
        #         f"<font size=9 color=grey>"
        #         f"Generated on {datetime.now().strftime('%d %b %Y, %H:%M')}"
        #         f"</font>",
        #         normal_style
        #     )
        # )


        doc.build(elements)

        return send_file(file_path, as_attachment=True)

    return render_template(
        "generate_bill.html",
        completed_months=completed_months
    )


# Create tables automatically when app starts
with app.app_context():
    db.create_all()