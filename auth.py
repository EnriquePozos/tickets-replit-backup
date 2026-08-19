# ==============================================================================
# SISTEMA DE AUTENTICACIÓN SIMPLE
# ==============================================================================
import os
from werkzeug.security import check_password_hash, generate_password_hash
from flask_login import UserMixin


class User(UserMixin):
    """Clase simple para usuarios del sistema."""
    
    def __init__(self, username, password_hash=None):
        self.id = username
        self.username = username
        self.password_hash = password_hash
    
    def check_password(self, password):
        """Verificar la contraseña del usuario."""
        if self.password_hash is None:
            return False
        return check_password_hash(self.password_hash, password)


class UserManager:
    """Manager para usuarios autorizados del sistema."""
    
    def __init__(self):
        # Usuarios autorizados definidos aquí o cargados desde variables de entorno
        self.authorized_users = self._load_authorized_users()
    
    def _load_authorized_users(self):
        """Carga los usuarios autorizados desde variables de entorno o configuración."""
        users = {}
        
        # Usuarios autorizados del sistema
        default_users = {
            'admin': 'admin123',
        }
        
        # Cargar usuarios desde variables de entorno si están disponibles
        env_users_str = os.environ.get('AUTHORIZED_USERS')
        if env_users_str:
            try:
                # Formato esperado: "usuario1:password1,usuario2:password2"
                pairs = env_users_str.split(',')
                for pair in pairs:
                    username, password = pair.strip().split(':')
                    users[username] = generate_password_hash(password)
            except Exception as e:
                print(f"Error al cargar usuarios desde entorno: {e}")
        
        # Si no hay usuarios en entorno, usar los predeterminados
        if not users:
            for username, password in default_users.items():
                users[username] = generate_password_hash(password)
        
        return users
    
    def get_user(self, username):
        """Obtener un usuario por su nombre de usuario."""
        if username in self.authorized_users:
            return User(username, self.authorized_users[username])
        return None
    
    def verify_user(self, username, password):
        """Verificar credenciales de usuario."""
        user = self.get_user(username)
        if user and user.check_password(password):
            return user
        return None
    
    def add_user(self, username, password):
        """Agregar un nuevo usuario autorizado."""
        self.authorized_users[username] = generate_password_hash(password)
    
    def remove_user(self, username):
        """Remover un usuario autorizado."""
        if username in self.authorized_users:
            del self.authorized_users[username]
    
    def list_users(self):
        """Listar todos los usuarios autorizados."""
        return list(self.authorized_users.keys())


# Instancia global del manager de usuarios
user_manager = UserManager()