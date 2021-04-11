import datetime
import random

import pytest
from faker import Faker
from sqlalchemy import event

from src.app import create_app
from src.extensions import db as _db
from src.models import CustomerMachine
from src.models.machine_model import MachineModel
from src.models.user import User
from config import settings
from src.resources.auth import authentication_manager
from src.services.machine_model import MachineModelService
from src.services.operating_time import OperatingTimeService
from src.services.rotation import RotationService
from src.services.user import UserService

fake = Faker()


@pytest.yield_fixture(scope='session')
def app():
    """
    Setup our flask test app, this only gets executed once.

    :return: Flask app
    """
    db_uri = '{0}_test'.format(settings.SQLALCHEMY_DATABASE_URI)

    params = {
        'DEBUG': False,
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': db_uri
    }

    _app = create_app(settings_override=params)

    # Establish an application context before running the tests.
    ctx = _app.app_context()
    ctx.push()

    yield _app

    ctx.pop()


@pytest.yield_fixture(scope='function')
def client(app):
    """
    Setup an app client, this gets executed for each test function.

    :param app: Pytest fixture
    :return: Flask app client
    """
    yield app.test_client()


@pytest.fixture(scope='session')
def db(app):
    """
    Setup our database, this only gets executed once per session.

    :param app: Pytest fixture
    :return: SQLAlchemy database session
    """
    _db.drop_all()
    _db.create_all()

    return _db


@pytest.fixture(scope='session')
def users(db):
    # Create users because a lot of tests do not mutate these users.
    # It will result in faster tests.
    users = [
        {
            'role': User.ROLE_ADMIN,
            'email': settings.SEED_ADMIN_EMAIL,
            'password': settings.SEED_ADMIN_PASSWORD,
            'profile': {
                'name': 'admin name',
                'name_kana': 'admin kana'
            }
        },
        {
            'role': User.ROLE_CLIENT,
            'email': 'client@endo.com',
            'password': 'client@password',
            'profile': {
                'name': 'client name',
                'name_kana': 'client kana'
            }
        },
        {
            'role': User.ROLE_CLIENT,
            'email': 'client2@endo.com',
            'password': 'client2@password',
            'profile': {
                'name': 'client2 name',
                'name_kana': 'client2 kana'
            }
        },
        {
            'role': User.ROLE_IOT,
            'email': 'iot@endo.com',
            'password': 'iot@password',
            'profile': {
                'name': 'iot name',
                'name_kana': 'iot kana'
            }
        },
        {
            'role': User.ROLE_CLIENT,
            'email': 'disabled@endo.com',
            'password': 'disabled@password',
            'is_active': False,
            'profile': {
                'name': 'disable name',
                'name_kana': 'disable kana'
            }
        }
    ]

    for user in users:
        user.pop('profile')
        db.session.add(User(**user))

    db.session.commit()


@pytest.fixture(scope='function')
def password_reset_token(db):
    """
    Serialize a JWS token.

    :param db: Pytest fixture
    :return: JWS token
    """
    user = User.find_by_identity('client@endo.com')
    return authentication_manager.serialize_token(user)


@pytest.yield_fixture(scope='function')
def session(app, db):
    """
    Allow very fast tests by using rollbacks and nested sessions. This does
    require that your database supports SQL savepoints.

    Read more about this at:
    http://stackoverflow.com/a/26624146

    :param db: Pytest fixture
    :return: None
    """
    """
       Returns function-scoped session.
       """
    with app.app_context():
        conn = _db.engine.connect()
        txn = conn.begin()

        options = dict(bind=conn, binds={})
        sess = _db.create_scoped_session(options=options)

        # establish  a SAVEPOINT just before beginning the test
        # (http://docs.sqlalchemy.org/en/latest/orm/session_transaction.html#using-savepoint)
        sess.begin_nested()

        @event.listens_for(sess(), 'after_transaction_end')
        def restart_savepoint(sess2, trans):
            # Detecting whether this is indeed the nested transaction of the test
            if trans.nested and not trans._parent.nested:
                # The test should have normally called session.commit(),
                # but to be safe we explicitly expire the session
                sess2.expire_all()
                sess2.begin_nested()

        _db.session = sess
        yield sess

        # Cleanup
        sess.remove()
        # This instruction rollback any commit that were executed in the tests.
        txn.rollback()
        conn.close()


@pytest.yield_fixture(scope='session')
def models(db):
    for i in range(0, 5):
        data = {
            'name': f"new_model_{i}"
        }

        db.session.add(MachineModel(**data))

    db.session.commit()

    return db


@pytest.yield_fixture(scope='session')
def customer_machines(db):
    customers = UserService.get_all_customers()
    machine_models = MachineModelService.get_all()

    for i in range(0, 5):
        customer = random.choice(customers)
        model = random.choice(machine_models)

        data = {
            'code': f"new_model_{i}",
            'customer_id': customer.id,
            'model_id': model.id
        }

        db.session.add(CustomerMachine(**data))

    db.session.commit()

    return db


@pytest.yield_fixture(scope='function')
def rotations(db):
    customers = UserService.get_all_customers()

    for customer in customers:
        machines = CustomerMachine.query.filter(CustomerMachine.customer_id == customer.id)
        for machine in machines:
            for i in range(0, 10):
                date = _get_rotation_date(machine.id)
                data = {
                    'date': date,
                    'shaft_a_normal_rotation': random.randrange(200, 600),
                    'shaft_a_reverse_rotation': random.randrange(200, 600),
                    'customer_machine_id': machine.id
                }

                RotationService.create(data)


@pytest.yield_fixture(scope='function')
def operating_times(db):
    customers = UserService.get_all_customers()

    for customer in customers:
        machines = CustomerMachine.query.filter(CustomerMachine.customer_id == customer.id)
        for machine in machines:
            for i in range(0, 10):
                date = _get_operating_time_date(machine.id)
                data = {
                    'date': date,
                    'duration': random.randrange(10000, 50000),
                    'customer_machine_id': machine.id
                }

                OperatingTimeService.create(data)


@pytest.yield_fixture(scope='function')
def random_date():
    return _get_random_date()


def _get_random_date():
    today = datetime.datetime.today()
    from_date = datetime.date(year=today.year, month=1, day=1)
    to_date = datetime.date(year=today.year, month=today.month, day=today.day)

    return fake.date_between(from_date, to_date)


def _get_rotation_date(machine_id):
    date = _get_random_date().strftime("%Y-%m-%d")
    if RotationService.is_exists(date, machine_id):
        date = _get_rotation_date(machine_id)

    return date


def _get_operating_time_date(machine_id):
    date = _get_random_date().strftime("%Y-%m-%d")
    if OperatingTimeService.is_exists(date, machine_id):
        date = _get_operating_time_date(machine_id)

    return date
