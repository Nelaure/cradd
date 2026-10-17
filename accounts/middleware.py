import re
from django.utils.deprecation import MiddlewareMixin
from django.shortcuts import redirect
from django.contrib import messages
from django.contrib.auth import logout
from django.urls import reverse

from .models import AuditLog
from .views import log_audit, get_client_ip, get_user_agent


class ActiveUserMiddleware(MiddlewareMixin):
    """
    Middleware qui déconnecte un utilisateur si son compte est désactivé (est_actif=False).
    """
    def process_request(self, request):
        if request.user.is_authenticated and not request.user.est_actif:
            logout(request)
            messages.warning(request, "Votre compte a été désactivé. Contactez l'administrateur.")
            return redirect('accounts:login')
        return None


class AuditLogMiddleware(MiddlewareMixin):
    """
    Middleware pour journaliser automatiquement les actions des utilisateurs.

    - Journalise les actions POST (création, modification, suppression) pour les
      utilisateurs authentifiés, en complément des `log_audit()` explicites des vues.
    - Journalise les visites (GET) pour tous les visiteurs (anonymes ou connectés).

    ⚠️ IMPORTANT : Le middleware reconnaît à la fois les URLs anglaises
    (`/delete/`, `/create/`, `/edit/`) ET françaises (`/supprimer/`, `/creer/`,
    `/modifier/`, `/editer/`).
    """

    IGNORE_PATHS = [
        r'^/static/',
        r'^/media/',
        r'^/accounts/login/',
        r'^/accounts/logout/',
        r'^/admin/',
        r'^/accounts/password-reset/',
        r'^/accounts/password-reset/verify/',
        r'^/accounts/audit-log/',  # éviter de polluer avec les visites d'audit
    ]

    # Chemins des actions (français + anglais)
    ACTION_PATTERNS = {
        'DELETE': ['/delete/', '/supprimer/'],
        'CREATE': ['/create/', '/creer/', '/ajouter/'],
        'UPDATE': ['/edit/', '/modifier/', '/editer/'],
    }

    # Mapping chemin → modèle (pour renseigner `model_name`)
    MODEL_PATTERNS = [
        ('/ecoles/', AuditLog.ModelName.ECOLE),
        ('/niveaux/', AuditLog.ModelName.NIVEAU),
        ('/classes/', AuditLog.ModelName.CLASSE),
        ('/sections/', AuditLog.ModelName.SECTION),
        ('/cours/', AuditLog.ModelName.COURS),
        ('/eleves/', AuditLog.ModelName.ELEVE),
        ('/resultats/', AuditLog.ModelName.EVALUATION),
        ('/provinces/', AuditLog.ModelName.PROVINCE),
        ('/annees/', AuditLog.ModelName.ANNEE_SCOLAIRE),
        ('/accounts/users/', AuditLog.ModelName.UTILISATEUR),
        ('/utilisateurs/', AuditLog.ModelName.UTILISATEUR),
    ]

    def process_request(self, request):
        pass

    def _detect_action(self, path):
        """Détecte l'action (DELETE, CREATE, UPDATE) depuis le chemin."""
        for action, patterns in self.ACTION_PATTERNS.items():
            for pattern in patterns:
                if pattern in path:
                    return action
        return None

    def _detect_model(self, path):
        """Détecte le modèle depuis le chemin."""
        for pattern, model_name in self.MODEL_PATTERNS:
            if pattern in path:
                return model_name
        return None

    def process_response(self, request, response):
        # --- 1. Journaliser les actions POST (utilisateurs authentifiés) ---
        if request.method == 'POST' and request.user.is_authenticated:
            path = request.path

            action = self._detect_action(path)
            model_name = self._detect_model(path)

            if action and model_name:
                ip = get_client_ip(request)
                user_agent = get_user_agent(request)

                # Ne journalise QUE si la vue n'a pas déjà fait un log_audit()
                # pour éviter les doublons. On considère qu'il y a doublon si une
                # entrée a été créée dans les 2 dernières secondes pour la même action.
                from django.utils import timezone
                from datetime import timedelta
                recent = AuditLog.objects.filter(
                    utilisateur=request.user,
                    action=action,
                    model_name=model_name,
                    timestamp__gte=timezone.now() - timedelta(seconds=2),
                ).exists()

                if not recent:
                    log_audit(
                        user=request.user,
                        action=action,
                        model_name=model_name,
                        ip_address=ip,
                        user_agent=user_agent,
                        success=response.status_code < 400,
                        message=f"{action} sur {model_name} ({path})"
                    )

        # --- 2. Journaliser les visites (GET) pour tous ---
        if request.method == 'GET' and response.status_code < 400:
            path = request.path
            for pattern in self.IGNORE_PATHS:
                if re.match(pattern, path):
                    return response

            user = request.user if request.user.is_authenticated else None
            ip = get_client_ip(request)
            user_agent = get_user_agent(request)

            log_audit(
                user=user,
                action=AuditLog.ActionType.VIEW,
                model_name=None,
                ip_address=ip,
                user_agent=user_agent,
                success=True,
                message=f"Visite de {path}"
            )

        return response