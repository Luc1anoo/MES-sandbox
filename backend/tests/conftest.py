import os
os.environ['DATABASE_URL']='sqlite://'
import pytest
from fastapi.testclient import TestClient
from app.core import Base,engine
from app.main import app
@pytest.fixture
def client():
    Base.metadata.drop_all(engine);Base.metadata.create_all(engine)
    with TestClient(app) as c:yield c
