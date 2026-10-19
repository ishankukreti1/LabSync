import os
import json

CONFIG_FILE = os.path.join(os.path.dirname(__file__), 'db_config.json')

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'change-me-for-local-development')
    MYSQL_HOST = '127.0.0.1'
    MYSQL_PORT = 3309
    MYSQL_USER = 'root'
    MYSQL_PASSWORD = ''
    MYSQL_DB = 'labsync'

    @classmethod
    def load(cls):
        # Environment variables
        cls.MYSQL_HOST = os.environ.get('MYSQL_HOST', cls.MYSQL_HOST)
        cls.MYSQL_PORT = int(os.environ.get('MYSQL_PORT', cls.MYSQL_PORT))
        cls.MYSQL_USER = os.environ.get('MYSQL_USER', cls.MYSQL_USER)
        env_pw = os.environ.get('MYSQL_PASSWORD')
        if env_pw is not None:
            cls.MYSQL_PASSWORD = env_pw
        cls.MYSQL_DB = os.environ.get('MYSQL_DB', cls.MYSQL_DB)

        # JSON config file if present
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    cls.MYSQL_HOST = data.get('MYSQL_HOST', cls.MYSQL_HOST)
                    cls.MYSQL_PORT = int(data.get('MYSQL_PORT', cls.MYSQL_PORT))
                    cls.MYSQL_USER = data.get('MYSQL_USER', cls.MYSQL_USER)
                    saved_pw = data.get('MYSQL_PASSWORD')
                    if saved_pw:
                        cls.MYSQL_PASSWORD = saved_pw
                    cls.MYSQL_DB = data.get('MYSQL_DB', cls.MYSQL_DB)
            except Exception:
                pass

    @classmethod
    def save(cls, host, port, user, password, database):
        cls.MYSQL_HOST = host
        cls.MYSQL_PORT = int(port)
        cls.MYSQL_USER = user
        cls.MYSQL_PASSWORD = password
        cls.MYSQL_DB = database
        data = {
            'MYSQL_HOST': host,
            'MYSQL_PORT': int(port),
            'MYSQL_USER': user,
            'MYSQL_DB': database
        }
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4)

Config.load()
