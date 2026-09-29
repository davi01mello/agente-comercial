"""Os testes usam um banco temporário, nunca o banco de desenvolvimento."""
import os
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.gettempdir()}/cerebro_test.db"
