from app import create_app, db
from flask.cli import FlaskGroup

app = create_app()
cli = FlaskGroup(create_app=lambda: app)

@cli.command("create_db")
def create_db():
    """Creates the database tables."""
    db.create_all()
    print("Database tables created.")

@cli.command("seed_db")
def seed_db():
    """Seeds the database with initial data."""
    # Add seed logic here
    print("Database seeded.")

if __name__ == "__main__":
    cli()
