import os
from pathlib import Path
import dj_database_url
from dotenv import load_dotenv

# Cloudinary
import cloudinary
import cloudinary.uploader
import cloudinary.api

load_dotenv(encoding='utf-8')

BASE_DIR = Path(__file__).resolve().parent.parent

# ---------- SECRET_KEY ----------
SECRET_KEY = os.getenv('SECRET_KEY')
if not SECRET_KEY:
    if os.getenv('DEBUG', 'False') == 'True':
        SECRET_KEY = 'django-insecure-8#v^1*(0(3+5&k$9z^#7c&f+h3r2!a'
        print("⚠️  SECRET_KEY par défaut (développement)")
    else:
        raise ValueError("SECRET_KEY manquante dans .env")

DEBUG = os.getenv('DEBUG', 'False') == 'True'
ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', 'localhost,127.0.0.1,.onrender.com').split(',')
CSRF_TRUSTED_ORIGINS = os.getenv('CSRF_TRUSTED_ORIGINS', 'https://*.onrender.com').split(',')

# ---------- APPLICATIONS ----------
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'whitenoise.runserver_nostatic',
    # Cloudinary
    'cloudinary_storage',
    'cloudinary',
    # Crispy Forms
    'crispy_forms',
    # Apps du projet
    'accounts',
    'ecoles',
    'eleves',
    'actualites',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'accounts.middleware.ActiveUserMiddleware',
    'accounts.middleware.AuditLogMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'cradd.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'django.template.context_processors.media',
                'ecoles.utils.trash_count',
            ],
        },
    },
]

WSGI_APPLICATION = 'cradd.wsgi.application'

# ---------- BASE DE DONNÉES ----------
if DEBUG:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }
else:
    DATABASES = {
        'default': dj_database_url.config(conn_max_age=600)
    }

# ---------- VALIDATION MDP ----------
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# ---------- INTERNATIONALISATION ----------
LANGUAGE_CODE = 'fr-fr'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# ---------- STATIQUES & MEDIAS ----------
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# Dossier pour les fichiers statiques (CSS, JS, images)
STATICFILES_DIRS = [
    BASE_DIR / 'static',
]

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# ---------- CLOUDINARY ----------
# Configuration simplifiée via CLOUDINARY_URL
# Si la variable d'environnement est définie, cloudinary.config() la lit automatiquement
cloudinary.config()

# Vérification optionnelle (pour le debug)
if not DEBUG and not os.getenv('CLOUDINARY_URL'):
    import logging
    logging.warning("⚠️  CLOUDINARY_URL non définie en production ! Les uploads d'images échoueront.")

# En production, utiliser Cloudinary ; en développement, le système de fichiers local
if not DEBUG:
    DEFAULT_FILE_STORAGE = 'cloudinary_storage.storage.MediaCloudinaryStorage'
else:
    DEFAULT_FILE_STORAGE = 'django.core.files.storage.FileSystemStorage'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ---------- AUTH ----------
AUTH_USER_MODEL = 'accounts.Utilisateur'
LOGIN_URL = 'accounts:login'
LOGIN_REDIRECT_URL = 'ecoles:dashboard'
LOGOUT_REDIRECT_URL = 'ecoles:index'

# ---------- CRISPY FORMS ----------
CRISPY_TEMPLATE_PACK = 'bootstrap4'

# ---------- EMAIL ----------
EMAIL_BACKEND = os.getenv('EMAIL_BACKEND', 'django.core.mail.backends.console.EmailBackend')
EMAIL_HOST = os.getenv('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', 587))
EMAIL_USE_TLS = os.getenv('EMAIL_USE_TLS', 'True') == 'True'
EMAIL_USE_SSL = os.getenv('EMAIL_USE_SSL', 'False') == 'True'
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '')
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', EMAIL_HOST_USER)

if EMAIL_BACKEND != 'django.core.mail.backends.console.EmailBackend':
    if not EMAIL_HOST_USER or not EMAIL_HOST_PASSWORD:
        raise ValueError("EMAIL_HOST_USER et EMAIL_HOST_PASSWORD requis")

# ---------- LOGGING ----------
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {'class': 'logging.StreamHandler'},
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'django.core.mail': {'handlers': ['console'], 'level': 'DEBUG', 'propagate': False},
        'accounts.views': {'handlers': ['console'], 'level': 'DEBUG', 'propagate': False},
    },
}

# ---------- SÉCURITÉ HTTPS ----------
if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')