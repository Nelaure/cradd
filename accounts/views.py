import logging
import csv
from datetime import datetime, timedelta

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, authenticate, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
from django.db.models import Q, Count
from django.http import HttpResponse
from django.urls import reverse

from .models import Utilisateur, AuditLog
from .forms import (
    UtilisateurCreationForm, UtilisateurChangeForm,
    PasswordResetRequestForm, PasswordResetVerifyForm
)
from ecoles.models import Ecole, Niveau, Classe
from eleves.models import Eleve

logger = logging.getLogger(__name__)


# ===================== FONCTIONS UTILITAIRES =====================

def log_audit(user, action, model_name=None, object_id=None, object_repr=None,
              changes=None, ip_address=None, user_agent=None, success=True, message=None):
    """Journalise une action dans l'AuditLog."""
    try:
        AuditLog.objects.create(
            utilisateur=user,
            action=action,
            model_name=model_name,
            object_id=str(object_id) if object_id else None,
            object_repr=object_repr or '',
            changes=changes or {},
            ip_address=ip_address,
            user_agent=user_agent,
            success=success,
            message=message
        )
    except Exception as e:
        logger.error(f"Erreur lors de l'enregistrement du journal d'activité : {e}")


def get_client_ip(request):
    """Récupère l'IP réelle du client (gère les proxys)."""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


def get_user_agent(request):
    """Récupère le User-Agent tronqué à 500 caractères."""
    return request.META.get('HTTP_USER_AGENT', '')[:500]


# ===================== AUTHENTIFICATION =====================

def login_view(request):
    if request.user.is_authenticated:
        return redirect('ecoles:dashboard')

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        user = authenticate(request, username=username, password=password)

        ip = get_client_ip(request)
        user_agent = get_user_agent(request)

        if user and user.est_actif and user.is_active:
            login(request, user)
            log_audit(
                user=user,
                action=AuditLog.ActionType.LOGIN,
                ip_address=ip,
                user_agent=user_agent,
                success=True,
                message=f"Connexion depuis {ip}"
            )
            if user.est_editeur():
                return redirect('actualites:dashboard')
            return redirect(request.GET.get('next', 'ecoles:dashboard'))
        else:
            # Journaliser la tentative échouée
            if user:
                log_audit(
                    user=user,
                    action=AuditLog.ActionType.LOGIN_FAILED,
                    ip_address=ip,
                    user_agent=user_agent,
                    success=False,
                    message=f"Tentative échouée (compte inactif ou désactivé) depuis {ip}"
                )
            else:
                # Utilisateur inexistant : on journalise quand même l'IP
                logger.warning(f"LOGIN_FAILED pour username='{username}' depuis {ip}")
            messages.error(request, 'Identifiants incorrects ou compte inactif.')

    return render(request, 'accounts/login.html')


@login_required
def logout_view(request):
    ip = get_client_ip(request)
    user_agent = get_user_agent(request)
    log_audit(
        user=request.user,
        action=AuditLog.ActionType.LOGOUT,
        ip_address=ip,
        user_agent=user_agent,
        success=True,
        message=f"Déconnexion depuis {ip}"
    )
    logout(request)
    messages.info(request, 'Vous avez été déconnecté avec succès.')
    return redirect('ecoles:index')


@login_required
def profile_view(request):
    return render(request, 'accounts/profile.html', {'user': request.user})


@login_required
def change_password_view(request):
    if request.method == 'POST':
        old_password = request.POST.get('old_password')
        new_password = request.POST.get('new_password')
        confirm_password = request.POST.get('confirm_password')

        if not request.user.check_password(old_password):
            messages.error(request, 'Mot de passe actuel incorrect.')
        elif new_password != confirm_password:
            messages.error(request, 'Les nouveaux mots de passe ne correspondent pas.')
        elif len(new_password) < 8:
            messages.error(request, 'Le mot de passe doit contenir au moins 8 caractères.')
        else:
            request.user.set_password(new_password)
            request.user.save()
            update_session_auth_hash(request, request.user)

            ip = get_client_ip(request)
            user_agent = get_user_agent(request)
            log_audit(
                user=request.user,
                action=AuditLog.ActionType.PASSWORD_CHANGE,
                ip_address=ip,
                user_agent=user_agent,
                success=True,
                message="Changement de mot de passe"
            )
            messages.success(request, 'Votre mot de passe a été modifié avec succès.')
            return redirect('accounts:profile')

    return render(request, 'accounts/change_password.html')


# ===================== RÉINITIALISATION MOT DE PASSE =====================

def password_reset_request_view(request):
    if request.user.is_authenticated:
        return redirect('ecoles:dashboard')

    if request.method == 'POST':
        form = PasswordResetRequestForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['email']
            ip = get_client_ip(request)
            user_agent = get_user_agent(request)

            try:
                user = Utilisateur.objects.get(email__iexact=email)
                code = user.generate_reset_code()

                subject = 'Réinitialisation de votre mot de passe - Cradd'
                message = f"""
                Bonjour {user.get_full_name()},

                Vous avez demandé la réinitialisation de votre mot de passe.

                Votre code de réinitialisation est : {code}

                Ce code est valable 15 minutes.

                Si vous n'êtes pas à l'origine de cette demande, ignorez cet email.

                Cordialement,
                L'équipe Cradd
                """

                try:
                    send_mail(
                        subject,
                        message,
                        settings.DEFAULT_FROM_EMAIL,
                        [email],
                        fail_silently=False,
                    )
                    log_audit(
                        user=user,
                        action=AuditLog.ActionType.PASSWORD_RESET,
                        ip_address=ip,
                        user_agent=user_agent,
                        success=True,
                        message=f"Demande de réinitialisation envoyée à {email}"
                    )
                    request.session['reset_email'] = email
                    messages.success(
                        request,
                        f'Un code de réinitialisation a été envoyé à {email}. '
                        'Veuillez vérifier votre boîte mail (pensez à vérifier les spams).'
                    )
                    return redirect('accounts:password_reset_verify')

                except Exception as e:
                    logger.error(f"Erreur SMTP lors de l'envoi à {email} : {str(e)}")
                    if settings.DEBUG:
                        messages.error(
                            request,
                            f"Erreur d'envoi : {str(e)}. Vérifiez votre configuration SMTP."
                        )
                    else:
                        messages.error(
                            request,
                            "Une erreur est survenue lors de l'envoi de l'email. "
                            "Veuillez réessayer plus tard ou contacter l'administrateur."
                        )

            except Utilisateur.DoesNotExist:
                # Message générique pour ne pas révéler l'existence de l'email
                messages.success(
                    request,
                    'Si un compte existe avec cet email, '
                    'un code de réinitialisation vous a été envoyé.'
                )
                return redirect('accounts:password_reset_verify')
        else:
            messages.error(request, 'Veuillez corriger les erreurs du formulaire.')
    else:
        form = PasswordResetRequestForm()

    return render(request, 'accounts/password_reset_request.html', {'form': form})


def password_reset_verify_view(request):
    if request.user.is_authenticated:
        return redirect('ecoles:dashboard')

    email = request.session.get('reset_email')

    if request.method == 'POST':
        form = PasswordResetVerifyForm(request.POST)
        if form.is_valid():
            code = form.cleaned_data['code']
            new_password = form.cleaned_data['new_password']

            try:
                user = Utilisateur.objects.get(
                    reset_code=code,
                    reset_code_used=False
                )

                if user.verify_reset_code(code):
                    user.set_password(new_password)
                    user.reset_code = None
                    user.reset_code_created_at = None
                    user.reset_code_used = True
                    user.save()

                    ip = get_client_ip(request)
                    user_agent = get_user_agent(request)
                    log_audit(
                        user=user,
                        action=AuditLog.ActionType.PASSWORD_RESET,
                        ip_address=ip,
                        user_agent=user_agent,
                        success=True,
                        message="Mot de passe réinitialisé avec succès"
                    )

                    messages.success(
                        request,
                        'Votre mot de passe a été réinitialisé avec succès. '
                        'Vous pouvez maintenant vous connecter.'
                    )

                    if 'reset_email' in request.session:
                        del request.session['reset_email']

                    return redirect('accounts:login')
                else:
                    messages.error(request, 'Code invalide ou expiré.')

            except Utilisateur.DoesNotExist:
                messages.error(request, 'Code invalide ou expiré.')
        else:
            messages.error(request, 'Veuillez corriger les erreurs ci-dessous.')
    else:
        form = PasswordResetVerifyForm()

    return render(request, 'accounts/password_reset_verify.html', {
        'form': form,
        'email': email
    })


# ===================== GESTION DES UTILISATEURS =====================

@login_required
def user_list_view(request):
    if not request.user.est_administrateur():
        messages.error(request, 'Accès non autorisé.')
        return redirect('ecoles:dashboard')

    users_qs = Utilisateur.objects.select_related(
        'ecole_affectation', 'province_affectation',
        'niveau_affectation', 'classe_affectation'
    ).order_by('-date_creation')

    # Filtres optionnels
    search = request.GET.get('q', '').strip()
    role = request.GET.get('role')
    est_actif = request.GET.get('est_actif')

    if search:
        users_qs = users_qs.filter(
            Q(username__icontains=search) |
            Q(nom__icontains=search) |
            Q(postnom__icontains=search) |
            Q(prenom__icontains=search) |
            Q(email__icontains=search)
        )
    if role:
        users_qs = users_qs.filter(role=role)
    if est_actif in ('0', '1'):
        users_qs = users_qs.filter(est_actif=(est_actif == '1'))

    paginator = Paginator(users_qs, 20)
    page = request.GET.get('page')
    users = paginator.get_page(page)

    context = {
        'users': users,
        'roles': Utilisateur.Role.choices,
        'search_query': search,
        'selected_role': role,
        'selected_est_actif': est_actif,
    }
    return render(request, 'accounts/user_list.html', context)


@login_required
def user_create_view(request):
    if not request.user.est_administrateur():
        messages.error(request, 'Accès non autorisé.')
        return redirect('ecoles:dashboard')

    if request.method == 'POST':
        form = UtilisateurCreationForm(request.POST, user=request.user)
        if form.is_valid():
            user = form.save()

            ip = get_client_ip(request)
            user_agent = get_user_agent(request)
            log_audit(
                user=request.user,
                action=AuditLog.ActionType.CREATE,
                model_name=AuditLog.ModelName.UTILISATEUR,
                object_id=user.id,
                object_repr=str(user),
                ip_address=ip,
                user_agent=user_agent,
                success=True,
                message=f"Création de l'utilisateur {user.username}"
            )

            messages.success(request, f"Utilisateur '{user.username}' créé avec succès.")
            return redirect('accounts:user_list')
        else:
            messages.error(request, 'Veuillez corriger les erreurs ci-dessous.')
    else:
        form = UtilisateurCreationForm(user=request.user)

    return render(request, 'accounts/user_form.html', {
        'form': form,
        'title': 'Créer un utilisateur'
    })


@login_required
def user_edit_view(request, pk):
    if not request.user.est_administrateur():
        messages.error(request, 'Accès non autorisé.')
        return redirect('ecoles:dashboard')

    user = get_object_or_404(Utilisateur, pk=pk)

    if request.method == 'POST':
        form = UtilisateurChangeForm(request.POST, instance=user, user=request.user)
        if form.is_valid():
            form.save()

            ip = get_client_ip(request)
            user_agent = get_user_agent(request)
            log_audit(
                user=request.user,
                action=AuditLog.ActionType.UPDATE,
                model_name=AuditLog.ModelName.UTILISATEUR,
                object_id=user.id,
                object_repr=str(user),
                ip_address=ip,
                user_agent=user_agent,
                success=True,
                message=f"Modification de l'utilisateur {user.username}"
            )

            messages.success(request, f"Utilisateur '{user.username}' modifié avec succès.")
            return redirect('accounts:user_list')
        else:
            messages.error(request, 'Veuillez corriger les erreurs ci-dessous.')
    else:
        form = UtilisateurChangeForm(instance=user, user=request.user)

    return render(request, 'accounts/user_form.html', {
        'form': form,
        'title': 'Modifier un utilisateur'
    })


@login_required
def user_delete_view(request, pk):
    if not request.user.est_administrateur():
        messages.error(request, 'Accès non autorisé.')
        return redirect('ecoles:dashboard')

    user = get_object_or_404(Utilisateur, pk=pk)

    if user.is_superuser:
        messages.error(request, "Cet utilisateur est un administrateur principal et ne peut pas être supprimé.")
        return redirect('accounts:user_list')

    if user == request.user:
        messages.error(request, "Vous ne pouvez pas supprimer votre propre compte.")
        return redirect('accounts:user_list')

    if request.method == 'POST':
        username = user.username
        user_id = user.id
        user_repr = str(user)

        ip = get_client_ip(request)
        user_agent = get_user_agent(request)
        log_audit(
            user=request.user,
            action=AuditLog.ActionType.DELETE,
            model_name=AuditLog.ModelName.UTILISATEUR,
            object_id=user_id,
            object_repr=user_repr,
            ip_address=ip,
            user_agent=user_agent,
            success=True,
            message=f"Suppression de l'utilisateur {username} (ID={user_id})"
        )

        user.delete()
        messages.success(request, f"Utilisateur '{username}' supprimé avec succès.")
        return redirect('accounts:user_list')

    return render(request, 'accounts/user_confirm_delete.html', {'user': user})


# ===================== JOURNAL D'ACTIVITÉ =====================

@login_required
def audit_log_view(request):
    """Vue améliorée du journal d'activité avec filtres, tri, recherche et export CSV."""
    if not request.user.est_administrateur():
        messages.error(request, 'Accès non autorisé.')
        return redirect('ecoles:dashboard')

    # --- Récupération des filtres ---
    action = request.GET.get('action', '').strip()
    user_id = request.GET.get('user', '').strip()
    model = request.GET.get('model', '').strip()
    success_filter = request.GET.get('success', '').strip()
    date_from = request.GET.get('date_from', '').strip()
    date_to = request.GET.get('date_to', '').strip()
    search_query = request.GET.get('q', '').strip()
    sort_by = request.GET.get('sort', 'timestamp')
    sort_order = request.GET.get('order', 'desc')
    export_format = request.GET.get('export', '').strip()

    # --- Queryset de base ---
    logs = AuditLog.objects.select_related('utilisateur').all()

    # --- Application des filtres ---
    if action:
        logs = logs.filter(action=action)
    if user_id:
        try:
            logs = logs.filter(utilisateur_id=int(user_id))
        except (ValueError, TypeError):
            pass
    if model:
        logs = logs.filter(model_name=model)
    if success_filter in ('0', '1'):
        logs = logs.filter(success=(success_filter == '1'))
    if date_from:
        try:
            logs = logs.filter(timestamp__date__gte=date_from)
        except Exception:
            pass
    if date_to:
        try:
            logs = logs.filter(timestamp__date__lte=date_to)
        except Exception:
            pass

    # --- Recherche textuelle ---
    if search_query:
        logs = logs.filter(
            Q(message__icontains=search_query) |
            Q(object_repr__icontains=search_query) |
            Q(ip_address__icontains=search_query) |
            Q(user_agent__icontains=search_query) |
            Q(utilisateur__username__icontains=search_query) |
            Q(utilisateur__nom__icontains=search_query) |
            Q(utilisateur__prenom__icontains=search_query)
        )

    # --- Tri ---
    sort_field = 'timestamp'
    if sort_by in ('timestamp', 'action', 'model_name', 'success'):
        sort_field = sort_by
    if sort_order == 'asc':
        logs = logs.order_by(sort_field)
    else:
        logs = logs.order_by(f'-{sort_field}')

    # --- Export CSV (avant la pagination !) ---
    if export_format == 'csv':
        return _export_audit_csv(logs, request)

    # --- Statistiques ---
    today = timezone.now().date()
    seven_days_ago = today - timedelta(days=7)

    # On utilise un queryset non filtré pour les stats globales, mais avec les mêmes
    # filtres utilisateur/modèle pour la cohérence
    stats_qs = AuditLog.objects.all()
    if user_id:
        try:
            stats_qs = stats_qs.filter(utilisateur_id=int(user_id))
        except (ValueError, TypeError):
            pass
    if model:
        stats_qs = stats_qs.filter(model_name=model)

    stats = {
        'total': stats_qs.count(),
        'total_delete': stats_qs.filter(action='DELETE').count(),
        'total_login_failed': stats_qs.filter(action='LOGIN_FAILED').count(),
        'total_users': Utilisateur.objects.filter(est_actif=True).count(),
    }

    # --- Pagination ---
    paginator = Paginator(logs, 50)
    page = request.GET.get('page')
    logs_page = paginator.get_page(page)

    # --- Construction des query params pour la pagination ---
    query_params = request.GET.copy()
    if 'page' in query_params:
        del query_params['page']
    query_string = query_params.urlencode()

    context = {
        'logs': logs_page,
        'users': Utilisateur.objects.all().order_by('username'),
        'actions': AuditLog.ActionType.choices,
        'models': AuditLog.ModelName.choices,
        'selected_action': action,
        'selected_user': user_id,
        'selected_model': model,
        'selected_success': success_filter,
        'selected_date_from': date_from,
        'selected_date_to': date_to,
        # Alias pour compatibilité template
        'date_from': date_from,
        'date_to': date_to,
        'search_query': search_query,
        'sort_by': sort_by,
        'sort_order': sort_order,
        'stats': stats,
        'today': today,
        'seven_days_ago': seven_days_ago,
        'query_string': query_string,
    }

    return render(request, 'accounts/audit_log.html', context)


def _export_audit_csv(logs, request):
    """Exporte les logs d'audit en CSV."""
    # Journaliser l'export
    ip = get_client_ip(request)
    user_agent = get_user_agent(request)
    log_audit(
        user=request.user,
        action=AuditLog.ActionType.EXPORT,
        ip_address=ip,
        user_agent=user_agent,
        success=True,
        message=f"Export CSV du journal d'activité ({logs.count()} entrées)"
    )

    response = HttpResponse(content_type='text/csv; charset=utf-8')
    filename = f"audit_log_{timezone.now().strftime('%Y%m%d_%H%M%S')}.csv"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    # BOM UTF-8 pour Excel
    response.write('\ufeff')

    writer = csv.writer(response, delimiter=';', quoting=csv.QUOTE_MINIMAL)
    writer.writerow([
        'Date', 'Heure', 'Utilisateur', 'Nom complet', 'Rôle',
        'Action', 'Modèle', 'Objet', 'ID objet',
        'IP', 'Statut', 'Message', 'User-Agent'
    ])

    for log in logs.iterator():
        u = log.utilisateur
        writer.writerow([
            log.timestamp.strftime('%d/%m/%Y'),
            log.timestamp.strftime('%H:%M:%S'),
            u.username if u else 'Anonyme',
            u.get_full_name() if u else '—',
            u.get_role_display() if u else '—',
            log.get_action_display(),
            log.get_model_name_display() or '—',
            log.object_repr or '—',
            log.object_id or '—',
            log.ip_address or '—',
            'OK' if log.success else 'Échec',
            log.message or '—',
            log.user_agent or '—',
        ])

    return response