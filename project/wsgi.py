"""Точка входа для uvicorn и gunicorn: `uvicorn wsgi:app`."""

from app.main import create_app

app = create_app()
