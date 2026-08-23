import re
from django.utils.deprecation import MiddlewareMixin
from django.shortcuts import redirect
from django.contrib import messages
from django.contrib.auth import logout
from django.urls import reverse

from .models import AuditLog
from .views import log_audit, get_client_ip


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
    - Journalise les actions POST (création, modification, suppression) pour les utilisateurs authentifiés.
    - Journalise les visites (GET) pour tous les visiteurs (anonymes ou connectés) sur les pages importantes.
    """

    # URLs à ignorer (pour éviter la pollution du journal)
    IGNORE_PATHS = [
        r'^/static/',
        r'^/media/',
        r'^/accounts/login/',
        r'^/accounts/logout/',
        r'^/admin/',
        r'^/accounts/password-reset/',
        r'^/accounts/password-reset/verify/',
    ]

    def process_request(self, request):
        # Cette méthode peut être utilisée pour d'autres traitements, mais nous laissons vide pour l'instant
        pass

    def process_response(self, request, response):
        # --- 1. Journaliser les actions POST (authentifiés) ---
        if request.method == 'POST' and request.user.is_authenticated:
            path = request.path

            # Déterminer le type d'action
            action = None
            model_name = None

            if '/delete/' in path:
                action = AuditLog.ActionType.DELETE
            elif '/create/' in path or '/creer/' in path:
                action = AuditLog.ActionType.CREATE
            elif '/edit/' in path or '/modifier/' in path:
                action = AuditLog.ActionType.UPDATE

            # Déterminer le modèle
            if '/ecoles/' in path:
                model_name = AuditLog.ModelName.ECOLE
            elif '/niveaux/' in path:
                model_name = AuditLog.ModelName.NIVEAU
            elif '/classes/' in path:
                model_name = AuditLog.ModelName.CLASSE
            elif '/cours/' in path:
                model_name = AuditLog.ModelName.COURS
            elif '/eleves/' in path:
                model_name = AuditLog.ModelName.ELEVE
            elif '/resultats/' in path:
                model_name = AuditLog.ModelName.EVALUATION
            elif '/users/' in path:
                model_name = AuditLog.ModelName.UTILISATEUR
            elif '/provinces/' in path:
                model_name = AuditLog.ModelName.PROVINCE
            elif '/domaines/' in path:
                model_name = AuditLog.ModelName.DOMAINE

            if action and model_name:
                ip = get_client_ip(request)
                user_agent = request.META.get('HTTP_USER_AGENT', '')

                log_audit(
                    user=request.user,
                    action=action,
                    model_name=model_name,
                    ip_address=ip,
                    user_agent=user_agent,
                    success=response.status_code < 400,
                    message=f"{action} sur {model_name}"
                )

        # --- 2. Journaliser les visites (GET) pour tous ---
        if request.method == 'GET' and response.status_code < 400:
            path = request.path
            # Ignorer les chemins statiques et ceux définis
            for pattern in self.IGNORE_PATHS:
                if re.match(pattern, path):
                    return response

            # On enregistre pour toutes les pages, sauf les ressources statiques, pour avoir une vue complète des visiteurs.
            # Option : limiter aux pages importantes pour réduire le volume.
            # Ici on enregistre tout GET (hors IGNORE_PATHS).
            user = request.user if request.user.is_authenticated else None
            ip = get_client_ip(request)
            user_agent = request.META.get('HTTP_USER_AGENT', '')

            # On peut ajouter un message contenant le chemin
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