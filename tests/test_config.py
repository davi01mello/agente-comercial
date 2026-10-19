import pytest

from app.config import Settings


@pytest.mark.parametrize("entrada", ["postgres://u:s@h:5432/db", "postgresql://u:s@h:5432/db"])
def test_url_do_postgres_da_railway_ganha_o_driver(entrada):
    assert Settings(database_url=entrada).database_url == "postgresql+psycopg://u:s@h:5432/db"


@pytest.mark.parametrize("url", ["sqlite:///./data/cerebro.db", "postgresql+psycopg://u:s@h/db"])
def test_outras_urls_nao_mudam(url):
    assert Settings(database_url=url).database_url == url
