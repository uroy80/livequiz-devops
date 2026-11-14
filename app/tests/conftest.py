import os, sys
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["ADMIN_PASSWORD"] = "test-admin-pass"
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
